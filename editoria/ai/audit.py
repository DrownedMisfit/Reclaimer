"""
Módulo de IA: REVISIÓN DEL PROYECTO (antes de exportar) y CONTINUIDAD.

No cambia nada: solo avisa. Cada aviso tiene gravedad:
  "error"   → casi seguro un fallo (archivo que falta)
  "warning" → posible problema (pantalla negra, audio saturado, inconsistencia visual…)
  "info"    → sugerencia (plano largo, clip repetido…)
"""
from __future__ import annotations

import numpy as np

from ..core import mapping
from ..core.model import KIND_IMAGE, SUG_PENDING, TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO, Project

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
            a, b = int(c.source_in * 100), int((c.source_in + c.src_len) * 100)
            seg = pk[a:b]
            if not len(seg):
                continue
            level = 20 * np.log10(float(np.percentile(seg, 90)) * c.volume + 1e-9)
            (music_level if tr.duck_db is not None else voice_level).append((level, c, tr))
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
    for mid, cs in uses.items():
        if len(cs) >= 3:
            m = p.media[mid]
            alts = ""
            if clip_vecs and mid in clip_vecs:
                base = clip_vecs[mid][1].mean(axis=0)
                sims = [(float(v.mean(axis=0) @ base), o) for o, (_t, v) in clip_vecs.items()
                        if o != mid and o not in uses and o in p.media]
                sims.sort(reverse=True)
                if sims:
                    alts = " Alternativas parecidas: " + ", ".join(p.media[o].name for _s, o in sims[:3]) + "."
            issues.append(_issue("info", "Repetición", cs[0].start, f"«{m.name}» aparece {len(cs)} veces",
                                 "Usar el mismo clip muchas veces se nota." + alts, cs[0].id))
        else:
            # El mismo trozo de un clip usado dos veces
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    if p.media[mid].kind != KIND_IMAGE and a.source_in < b.source_in + b.duration and \
                            b.source_in < a.source_in + a.duration:
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
