"""
Módulo de IA: REVISIÓN DEL PROYECTO (antes de exportar) y CONTINUIDAD.

No cambia nada: solo avisa. Cada aviso tiene gravedad:
  "error"   → casi seguro un fallo (archivo que falta)
  "warning" → posible problema (pantalla negra, audio saturado, inconsistencia visual…)
  "info"    → sugerencia (plano largo, clip repetido…)
"""
from __future__ import annotations

import json
import os

import numpy as np

from ..core import black_frames, cut_check, mapping
from ..core.media import PEAK_RATE
from ..core.model import KIND_IMAGE, KIND_VIDEO, SUG_PENDING, TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO, Project
from ..core.paths import cache_dir

BLACK_MIN = 1.0         # un negro de menos de esto (segundos) dentro de un clip no se avisa
JUMP_DB = 12.0          # salto de volumen entre dos clips de voz seguidos a partir de esto (dB)
JUMP_WIN = 0.5          # ventana (segundos) a cada lado del empalme para medir el volumen
JUMP_MIN_DB = -40.0     # por debajo de esto es silencio: no se compara
JUMP_GAP = 0.25         # dos clips separados más que esto (segundos) no son «seguidos»

# Qué se espera ver cuando hablas de cada tema (para avisar de posibles inconsistencias)
TOPIC_EXPECT = {
    "COMBATE": {"tags": {"combate", "jefe", "arma"}, "types": {"Gameplay"}},
    "JUGABILIDAD": {"tags": set(), "types": {"Gameplay"}},
    "CINEMATOGRAFÍA": {"tags": set(), "types": {"Cinemáticas"}},
    "HISTORIA Y NARRATIVA": {"tags": {"diálogo", "personaje"}, "types": {"Cinemáticas"}},
    "PERSONAJES": {"tags": {"personaje", "diálogo"}, "types": {"Cinemáticas"}},
    "DISEÑO DE NIVELES": {"tags": {"exploración", "paisaje"}, "types": {"Gameplay"}},
}


def _issue(severity: str, category: str, time: float | None, message: str, detail: str = "",
           target: str | None = None) -> dict:
    return {"severity": severity, "category": category, "time": time, "message": message, "detail": detail,
            "target": target}


def _coverage_gaps(p: Project, kinds: set[str], total: float, min_gap: float) -> list[tuple[float, float]]:
    spans = sorted((c.start, c.end) for c in p.clips.values()
                   if c.enabled and p.track(c.track_id).kind in kinds and not p.track(c.track_id).hidden
                   and not (p.track(c.track_id).kind == TRACK_AUDIO and p.track(c.track_id).muted))
    gaps, t = [], 0.0
    for a, b in spans:
        if a - t >= min_gap:
            gaps.append((t, a))
        t = max(t, b)
    if total - t >= min_gap:
        gaps.append((t, total))
    return gaps


def _negros_en_cache(path: str) -> list[list[float]] | None:
    """Tramos completamente negros del archivo SI ya se detectaron antes (sin lanzar FFmpeg: es barato). None si no."""
    from ..core import media as media_tools
    key = f"{media_tools.cache_key(path)}_{black_frames.PIX_TH}_{black_frames.PIC_TH}.json"
    try:
        with open(os.path.join(str(cache_dir("negros")), key), encoding="utf-8") as f:
            return [list(x) for x in json.load(f)]
    except (OSError, ValueError):
        return None


def _nivel_db(pk: np.ndarray, a: float, b: float, vol: float) -> float | None:
    """Nivel (dB) de la parte [a, b) segundos del archivo, con el volumen del clip. None si no hay datos."""
    seg = pk[int(a * PEAK_RATE):int(b * PEAK_RATE)]
    if not len(seg):
        return None
    return 20 * np.log10(float(np.percentile(seg, 90)) * vol + 1e-9)


def run_audit(p: Project, missing: set[str], peaks: dict[str, np.ndarray],
              clip_vecs: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
              max_static: float = 8.0) -> tuple[list[dict], int]:
    """Devuelve (avisos, número de elementos revisados)."""
    issues: list[dict] = []
    checked = 0
    total = p.duration()
    if total <= 0:
        return [_issue("info", "Proyecto", None, "La timeline está vacía.")], 0

    # 0) YouTube Shorts
    if p.format in ("short", "edit"):
        checked += 1
        if total > 180:
            issues.append(_issue("warning", "Short", None, f"El Short dura {total:.0f} s",
                                 "YouTube solo acepta Shorts de hasta 3 minutos."))
        for c in p.clips.values():
            m = p.media_of(c)
            if c.text is None and m and m.kind != "audio" and c.layout is None and m.width > m.height \
                    and p.track(c.track_id).kind == TRACK_VIDEO:
                issues.append(_issue("info", "Short", c.start, f"«{m.name}» tiene bandas negras",
                                     "Es un clip horizontal en un Short: ponle ▦ Relleno (Efectos → Imagen, o en el "
                                     "Inspector → ⤧ Transformar) y se llena con la propia imagen desenfocada.", c.id))
                break

    # 1) Archivos que faltan
    for c in p.clips.values():
        checked += 1
        if c.media_id and c.media_id in missing:
            m = p.media.get(c.media_id)
            issues.append(_issue("error", "Archivos", c.start, f"Falta el archivo «{m.name if m else '?'}»",
                                 "Se movió o se borró del disco. Ese tramo saldrá en negro o en silencio.", c.id))

    # 1b) Textos que quedan fuera de la pantalla (posición en 0–1 del encuadre)
    for c in p.clips.values():
        if c.text and c.enabled:
            checked += 1
            x, y = float(c.text.get("x", 0.5)), float(c.text.get("y", 0.12))
            if not (0 <= x <= 1 and 0 <= y <= 1):
                issues.append(_issue("warning", "Textos", c.start, "Un texto queda fuera de la pantalla",
                                     f"«{str(c.text.get('content', ''))[:40]}» está fuera del encuadre: "
                                     "no se verá entero. Muévelo desde el Inspector.", c.id))

    # 1c) Cortes de audio dudosos (las «líneas rojas» de la línea de tiempo, ver core/cut_check.py)
    for j in cut_check.check(p, lambda mid: peaks.get(mid)):
        checked += 1
        sev = "warning" if j.get("severity") == "alta" else "info"
        issues.append(_issue(sev, "Cortes", j["t"], "Corte de audio dudoso",
                             "; ".join(j["reasons"]) + ". Ábrelo en la pista de audio para ajustarlo "
                             "o márcalo como «Está bien así».", j.get("right_id")))

    # 2) Pantallas negras y silencios
    for a, b in _coverage_gaps(p, {TRACK_VIDEO}, total, 0.5):
        issues.append(_issue("warning", "Imagen", a, f"Pantalla negra de {b - a:.1f} s",
                             "No hay ningún clip de video en este tramo."))
    audio_spans = _coverage_gaps(p, {TRACK_AUDIO}, total, 2.0)
    video_with_audio = [(c.start, c.end) for c in p.clips.values() if c.enabled and c.volume > 0
                        and p.track(c.track_id).kind == TRACK_VIDEO and not p.track(c.track_id).muted
                        and (m := p.media_of(c)) is not None and m.has_audio]
    for a, b in audio_spans:
        if not any(x < b and y > a for x, y in video_with_audio):
            issues.append(_issue("warning", "Audio", a, f"Silencio total de {b - a:.1f} s",
                                 "No suena nada en este tramo (ni voz, ni música, ni el audio de los clips)."))
    checked += 2

    # 2b) Tramos completamente negros DENTRO de un clip (solo si el análisis de negros ya se hizo antes: es barato)
    negros: dict[str, list | None] = {}
    for c in p.clips.values():
        m = p.media_of(c)
        if not (c.enabled and m and m.kind == KIND_VIDEO and c.speed == 1 and not c.reverse and not c.text):
            continue
        if c.media_id not in negros:
            negros[c.media_id] = _negros_en_cache(m.path) if m.path and os.path.isfile(m.path) else None
        spans = negros[c.media_id] or []
        checked += 1
        dentro = 0.0
        primero = None
        for a, b in spans:
            lo, hi = max(a, c.source_in), min(b, c.source_in + c.src_len)
            if hi - lo >= BLACK_MIN:
                dentro += hi - lo
                primero = primero if primero is not None else lo
        if primero is not None:
            issues.append(_issue("warning", "Imagen", c.start + (primero - c.source_in),
                                 f"Negro de {dentro:.1f} s dentro de un clip",
                                 f"En «{m.name}» la imagen se queda completamente en negro en este tramo. Si es un "
                                 "fundido a negro a propósito, no pasa nada.", c.id))

    # 3) Volumen: saturación, voz baja, música demasiado alta
    for s in p.suggestions:
        if s.kind == "clipping" and s.status == SUG_PENDING:
            t = mapping.map_time(p, s.media_id, s.start)
            if t is not None:
                issues.append(_issue("warning", "Audio", t, "Audio saturado (distorsión)", s.detail))
    voice_level, music_level = [], []
    for tr in p.tracks:
        if tr.kind != TRACK_AUDIO or tr.muted:
            continue
        for c in p.clips_on(tr.id):
            m = p.media_of(c)
            pk = peaks.get(c.media_id) if m else None
            if pk is None or not len(pk) or not c.enabled:
                continue
            level = _nivel_db(pk, c.source_in, c.source_in + c.src_len, c.volume)
            if level is None:
                continue
            (music_level if tr.duck_db is not None else voice_level).append((level, c, tr))
    # Salto brusco de volumen entre dos clips de voz seguidos (p. ej. un trozo mucho más bajo que el anterior)
    for tr in p.tracks:
        if tr.kind != TRACK_AUDIO or tr.muted or tr.duck_db is not None:
            continue
        cs = sorted((c for c in p.clips_on(tr.id) if c.enabled and c.media_id and not c.vol_kf and c.speed == 1
                     and not c.reverse), key=lambda c: c.start)
        for left, right in zip(cs, cs[1:]):
            if right.start - left.end > JUMP_GAP:
                continue
            pk_l, pk_r = peaks.get(left.media_id), peaks.get(right.media_id)
            if pk_l is None or pk_r is None or not len(pk_l) or not len(pk_r):
                continue
            checked += 1
            lv_l = _nivel_db(pk_l, left.source_in + left.src_len - JUMP_WIN, left.source_in + left.src_len,
                             left.volume)
            lv_r = _nivel_db(pk_r, right.source_in, right.source_in + JUMP_WIN, right.volume)
            if lv_l is None or lv_r is None or min(lv_l, lv_r) < JUMP_MIN_DB:
                continue
            if abs(lv_l - lv_r) >= JUMP_DB:
                issues.append(_issue("warning", "Audio", right.start, "Salto de volumen brusco en la voz",
                                     f"Al pasar de un clip al siguiente el volumen cambia {abs(lv_l - lv_r):.0f} dB "
                                     f"({lv_l:.0f} → {lv_r:.0f} dB). Ajusta el volumen de uno de los dos.", right.id))
    for level, c, tr in voice_level:
        checked += 1
        if level < -24 and (m := p.media_of(c)) and m.category == "Narración":
            issues.append(_issue("warning", "Audio", c.start, "La voz suena muy baja",
                                 f"Nivel aproximado {level:.0f} dB. Sube el volumen del clip o activa el compresor.",
                                 c.id))
    if voice_level and music_level:
        v = max(lvl for lvl, _c, _t in voice_level)
        for level, c, tr in music_level:
            effective = level + (tr.duck_db or 0)
            if effective > v - 6:
                issues.append(_issue("warning", "Audio", c.start, "La música puede tapar la voz",
                                     "Baja el volumen de la música o aumenta cuánto baja al hablar.", c.id))

    # 4) Planos largos sin cambios, clips repetidos, imágenes fijas
    uses: dict[str, list] = {}
    for tr in p.tracks:
        if tr.kind != TRACK_VIDEO or tr.hidden:
            continue
        for c in p.clips_on(tr.id):
            checked += 1
            m = p.media_of(c)
            if m is None:
                continue
            uses.setdefault(m.id, []).append(c)
            animated = len(c.zoom_kf) >= 2
            if c.duration > max_static and not animated:
                kind = "Imagen fija" if m.kind == KIND_IMAGE else "Plano"
                issues.append(_issue("info", "Ritmo", c.start, f"{kind} de {c.duration:.0f} s sin cambios",
                                     "Lleva mucho rato igual. Puedes dividirlo, añadir un zoom suave o "
                                     "buscar otro clip.", c.id))
    # Solo se avisa si el MISMO trozo de un archivo sale solapado. Usar un clip en tramos distintos no es repetirlo.
    for mid, cs in uses.items():
        if p.media[mid].kind == KIND_IMAGE:
            continue
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if a.source_in < b.source_in + b.duration and b.source_in < a.source_in + a.duration:
                    issues.append(_issue("info", "Repetición", b.start,
                                         f"Se repite el mismo momento de «{p.media[mid].name}»",
                                         "Las dos apariciones muestran el mismo trozo del archivo.", b.id))

    # 5) Continuidad: lo que dices frente a lo que se ve
    for mk in p.markers:
        if mk.kind != "topic" or mk.end is None or mk.label not in TOPIC_EXPECT:
            continue
        exp = TOPIC_EXPECT[mk.label]
        clips = [c for tr in p.tracks if tr.kind == TRACK_VIDEO and not tr.hidden for c in p.clips_on(tr.id)
                 if c.start < mk.end and c.end > mk.time]
        checked += 1
        analyzed = [(c, p.media_of(c)) for c in clips if p.media_of(c) and p.media_of(c).ai_analyzed]
        if not analyzed:
            continue
        ok = [c for c, m in analyzed if (exp["tags"] & set(m.ai_tags)) or (m.ai_type in exp["types"])]
        covered = sum(min(c.end, mk.end) - max(c.start, mk.time) for c in ok)
        span = sum(min(c.end, mk.end) - max(c.start, mk.time) for c, _m in analyzed)
        if span > 0 and covered / span < 0.35:
            seen = ", ".join(sorted({m.ai_type or (m.ai_tags[0] if m.ai_tags else "?") for _c, m in analyzed}))
            issues.append(_issue("warning", "Continuidad", mk.time,
                                 f"⚠️ Posible inconsistencia visual en «{mk.label.lower()}»",
                                 f"Hablas de {mk.label.lower()} pero se ve sobre todo: {seen}. "
                                 "Puede ser a propósito; si no, busca B-roll para esta parte."))

    # 6) Subtítulos y pistas ocultas
    st = p.subtitles
    if st.enabled and st.media_id not in p.transcripts:
        checked += 1
        issues.append(_issue("warning", "Subtítulos", None, "Subtítulos activados sin transcripción",
                             "La narración de los subtítulos no está transcrita, así que no saldrá ninguno. "
                             "Transcríbela (Voz → Transcribir) o desactiva los subtítulos."))
    if st.enabled and st.media_id in p.transcripts:
        doubtful = [w for w in p.transcripts[st.media_id]["words"] if len(w) > 3 and w[3] < 0.35]
        checked += 1
        if doubtful:
            t = mapping.map_time(p, st.media_id, doubtful[0][0])
            issues.append(_issue("info", "Subtítulos", t, f"{len(doubtful)} palabras dudosas en los subtítulos",
                                 "Whisper no estaba seguro de ellas: revísalas en la pestaña «Texto» "
                                 "(subrayado punteado). Ej.: «" + "», «".join(w[2] for w in doubtful[:4]) + "»."))
    for tr in p.tracks:
        if tr.hidden and tr.kind in (TRACK_VIDEO, TRACK_TEXT) and p.clips_on(tr.id):
            issues.append(_issue("info", "Pistas", None, f"La pista «{tr.name}» está oculta",
                                 "Su contenido no saldrá en el video exportado."))
        if tr.muted and tr.kind == TRACK_AUDIO and p.clips_on(tr.id):
            issues.append(_issue("info", "Pistas", None, f"La pista «{tr.name}» está silenciada",
                                 "No se oirá en el video exportado."))
    solos = [t.name for t in p.tracks if t.kind == TRACK_AUDIO and t.solo]
    if solos:
        issues.append(_issue("warning", "Pistas", None, "Hay pistas de audio en «Solo» (S)",
                             "Al exportar solo se oirá: " + ", ".join(f"«{n}»" for n in solos) +
                             ". Quita la S si quieres que suene todo."))

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda d: (order[d["severity"]], d["time"] if d["time"] is not None else -1))
    return issues, checked


def summary(issues: list[dict], checked: int) -> str:
    n_err = sum(1 for i in issues if i["severity"] in ("error", "warning"))
    n_info = sum(1 for i in issues if i["severity"] == "info")
    return f"⚠️ {n_err} posibles problemas · ℹ️ {n_info} sugerencias · ✓ {checked} elementos revisados"
