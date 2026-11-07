"""
Módulo de IA (sin Qt): SHORTS DESDE ESTE VIDEO.

  pick_shorts(project, n=5, min_s=45, max_s=75, peaks=None) -> [{"start", "end", "title", "score", "why"}]
      Propone los mejores tramos para Shorts (segundos de la LÍNEA DE TIEMPO), sin solaparse, ordenados por puntuación.
  build_short(project, pick, number) -> Project
      Copia del proyecto con SOLO ese tramo (pistas recortadas y movidas a 0), en formato «short».
  write_short(project, pick, number, folder) -> ruta del .eia
      Guarda ese Short. El proyecto largo no cambia.

Cómo puntúa (0 a 1, suma ponderada):
  · voz con energía (40 %): volumen de la voz frente a lo habitual de la narración (picos de onda);
  · tema completo (25 %): cuánto del tramo cae dentro de un tema de la narración (marcadores de tema);
  · menciones (20 %): nombres de juegos o compañías que salen dentro (ai/mentions.py);
  · pausas limpias (10 %): empieza y acaba en una pausa larga o al final de una frase;
  · duración (5 %): más cerca de 60 s, mejor.
Empieza y acaba en pausas de la transcripción (con margen de hasta 0,3 s, sin tocar la palabra vecina).
Sin transcripción: se usan los trozos de voz que marcan el volumen y los silencios.
"""
from __future__ import annotations

import bisect
import copy
import json
import os
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from ..core import media as media_tools
from ..core.mapping import DeepIndex
from ..core.model import FORMATS, KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, Project, new_id
from . import mentions as _mentions

PAUSA = 0.25        # pausa mínima (s) donde puede empezar o acabar un Short
MARGEN = 0.3        # margen (s) antes de la primera palabra y después de la última (sin cortar palabras)
SEPARACION = 1.0    # separación mínima (s) entre dos propuestas
PESOS = {"energia": 0.40, "tema": 0.25, "menciones": 0.20, "pausas": 0.10, "duracion": 0.05}


@dataclass
class _Tok:
    s0: float      # segundos del archivo de narración
    s1: float
    text: str
    t0: float      # segundos de la línea de tiempo
    t1: float
    rel: float     # volumen de la voz frente a lo habitual (1 = normal)


def _narration_media(p: Project) -> str | None:
    """La narración: el archivo con más palabras transcritas; sin transcripción, el de más sonido en la timeline."""
    best, best_n = None, 0
    for mid, tr in (p.transcripts or {}).items():
        n = len(((tr or {}).get("words")) or [])
        if mid in p.media and n > best_n:
            best, best_n = mid, n
    if best:
        return best
    total: dict[str, float] = {}
    for c in p.clips.values():
        m = p.media.get(c.media_id)
        if m and m.kind in (KIND_VIDEO, KIND_AUDIO) and not c.is_text and c.speed > 0:
            total[c.media_id] = total.get(c.media_id, 0.0) + c.duration
    return max(total, key=total.get) if total else None


def _peaks(p: Project, mid: str, peaks) -> np.ndarray | None:
    pk = peaks.get(mid) if isinstance(peaks, dict) else peaks
    if pk is None:
        m = p.media.get(mid)
        try:
            if m and os.path.exists(m.path):
                pk = media_tools.waveform_peaks(m.path)
        except Exception:  # noqa: BLE001 - sin picos se sigue con la transcripción
            pk = None
    return None if pk is None else np.asarray(pk, np.float32)


def _voiced_runs(pk: np.ndarray) -> list[tuple[float, float, str]]:
    """Sin transcripción: trozos de voz (por volumen), con pausas de al menos PAUSA entre ellos."""
    block = max(1, media_tools.PEAK_RATE // 10)          # bloques de 0,1 s
    n = len(pk) // block
    if n == 0:
        return []
    fl = pk[: n * block].reshape(n, block).max(axis=1)
    thr = max(0.01, 0.12 * float(np.percentile(fl, 90)))
    on = np.concatenate([[False], fl >= thr, [False]])
    edges = np.flatnonzero(np.diff(on.astype(np.int8)))
    runs = [[a / 10.0, b / 10.0] for a, b in zip(edges[::2], edges[1::2])]
    merged: list[list[float]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] < PAUSA:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b, "") for a, b in merged if b - a >= 0.3]


def _tokens(p: Project, mid: str, pk: np.ndarray | None) -> list[_Tok]:
    words = ((p.transcripts or {}).get(mid) or {}).get("words") or []
    if words:
        raw = [(float(w[0]), float(w[1]), str(w[2])) for w in words]
    else:
        raw = _voiced_runs(pk) if pk is not None else []
    idx = DeepIndex(p, mid)
    out: list[_Tok] = []
    for s0, s1, text in raw:
        if s1 <= s0:
            continue
        t0 = idx.time(s0)
        if t0 is None:
            t0 = idx.time(s0 + 0.03)
        t1 = idx.time(s1)
        if t1 is None:
            t1 = idx.time(s1 - 0.03)
        if t0 is None or t1 is None or t1 < t0:
            continue                       # cortada de la timeline (o al revés): no sirve
        energy = 1.0
        if pk is not None:
            a = int(s0 * media_tools.PEAK_RATE)
            b = max(a + 1, int(s1 * media_tools.PEAK_RATE))
            seg = pk[a:b]
            energy = float(seg.mean()) if seg.size else 0.0
        out.append(_Tok(s0, s1, text, float(t0), float(t1), energy))
    if out and pk is not None:                # volumen relativo a lo habitual de esta narración
        med = float(np.median([t.rel for t in out])) or 1e-6
        for t in out:
            t.rel = t.rel / med
    else:
        for t in out:
            t.rel = 1.0
    return out


def _is_end(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!", "…"))


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _title(toks: list[_Tok], j: int, k: int) -> str:
    """Frase corta de lo que se dice: la frase más enérgica del tramo (9 palabras como mucho)."""
    if not toks[j].text:
        return ""
    frases, cur = [], []
    for i in range(j, k + 1):
        cur.append(i)
        if _is_end(toks[i].text) or i == k:
            frases.append(cur)
            cur = []
    mejor, mejor_e = None, -1.0
    for fr in frases:
        palabras = " ".join(toks[i].text for i in fr).split()
        if len(palabras) < 3 and len(frases) > 1:
            continue
        e = float(np.mean([toks[i].rel for i in fr]))
        if e > mejor_e:
            mejor, mejor_e = palabras, e
    if not mejor:
        mejor = " ".join(toks[i].text for i in frases[0]).split()
    txt = " ".join(mejor[:9]).strip(" ,;:-–—")
    return txt[:1].upper() + txt[1:]


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60:02d}:{s % 60:02d}"


def pick_shorts(project: Project, n: int = 5, min_s: float = 45.0, max_s: float = 75.0,
                peaks=None) -> list[dict]:
    """Los mejores tramos de la narración para Shorts. peaks: {media_id: picos} (si no, se calculan)."""
    mid = _narration_media(project)
    if mid is None:
        return []
    pk = _peaks(project, mid, peaks)
    toks = _tokens(project, mid, pk)
    if len(toks) < 3:
        return []
    n_t = len(toks)

    # pausas (en el archivo: la timeline puede haber quitado silencios, y eso no cambia dónde se corta)
    gap_b = [9.0] + [max(0.0, toks[i].s0 - toks[i - 1].s1) for i in range(1, n_t)]
    gap_a = [max(0.0, toks[i + 1].s0 - toks[i].s1) for i in range(n_t - 1)] + [9.0]
    tgap_b = [9.0] + [toks[i].t0 - toks[i - 1].t1 for i in range(1, n_t)]
    tgap_a = [toks[i + 1].t0 - toks[i].t1 for i in range(n_t - 1)] + [9.0]
    inicios = [j for j in range(n_t) if j == 0 or gap_b[j] >= PAUSA or _is_end(toks[j - 1].text)]
    finales = sorted({k for k in range(n_t) if k == n_t - 1 or gap_a[k] >= PAUSA or _is_end(toks[k].text)})
    pad_b = [max(0.0, min(MARGEN, gap_b[j] / 2, tgap_b[j] / 2)) for j in range(n_t)]
    pad_a = [max(0.0, min(MARGEN, gap_a[k] / 2, tgap_a[k] / 2)) for k in range(n_t)]
    ini_t = [max(0.0, toks[j].t0 - pad_b[j]) for j in range(n_t)]
    fin_t = [toks[k].t1 + pad_a[k] for k in range(n_t)]

    # acumulados para el volumen medio de cada tramo
    dur = np.array([max(1e-3, t.s1 - t.s0) for t in toks])
    rel = np.array([t.rel for t in toks])
    cs_d = np.concatenate([[0.0], np.cumsum(dur)])
    cs_e = np.concatenate([[0.0], np.cumsum(dur * rel)])

    # menciones (nombres de juegos y compañías) y temas de la narración (marcadores de tema)
    hits = sorted((h["tl"], m["term"]) for m in _mentions.find_mentions(project)
                  for h in m.get("hits", []) if h.get("tl") is not None)
    mt = [h[0] for h in hits]
    temas = [(m.time, float(m.end), m.label) for m in project.markers
             if m.kind == "topic" and m.end is not None and m.end > m.time]

    cands: list[tuple[float, int, int, float, float]] = []
    for j in inicios:
        a = ini_t[j]
        for k in finales:
            if k < j:
                continue
            b = fin_t[k]
            if toks[k].t1 - a > max_s + 1.0:
                break
            d = b - a
            if d < min_s or d > max_s:
                continue
            w = cs_d[k + 1] - cs_d[j]
            volumen = (cs_e[k + 1] - cs_e[j]) / w if w > 0 else 1.0
            e_s = _clip01((volumen - 0.9) / 0.6)
            lo, hi = bisect.bisect_left(mt, a), bisect.bisect_right(mt, b)
            m_s = min(1.0, 0.25 * (hi - lo))
            t_s = 0.0
            for t0, t1, _lab in temas:
                ov = min(b, t1) - max(a, t0)
                if ov > 0:
                    t_s = max(t_s, ov / min(d, t1 - t0))
            limpias = (gap_b[j] >= 0.6 and gap_a[k] >= 0.6) or j == 0 or k == n_t - 1
            p_s = 1.0 if limpias else 0.6
            l_s = _clip01(1.0 - abs(d - 60.0) / 30.0)
            score = (PESOS["energia"] * e_s + PESOS["tema"] * t_s + PESOS["menciones"] * m_s
                     + PESOS["pausas"] * p_s + PESOS["duracion"] * l_s)
            cands.append((score, j, k, a, b))
    cands.sort(key=lambda c: -c[0])

    def _libre(c, lista):
        return all(c[4] + SEPARACION <= e[3] or c[3] >= e[4] + SEPARACION for e in lista)

    elegidos: list[tuple[float, int, int, float, float]] = []
    repetidas: list[tuple[float, int, int, float, float]] = []
    comienzos: set[str] = set()          # primero, no dos propuestas que empiecen igual («Hola a todos…» dos veces)
    for c in cands:
        if len(elegidos) >= n:
            break
        if not _libre(c, elegidos):
            continue
        clave = _title(toks, c[1], c[2])[:24].lower()
        if clave and clave in comienzos:
            repetidas.append(c)
            continue
        comienzos.add(clave)
        elegidos.append(c)
    for c in repetidas:                  # si faltan, se completa con las repetidas (mejor eso que nada)
        if len(elegidos) >= n:
            break
        if _libre(c, elegidos):
            elegidos.append(c)

    out = []
    for score, j, k, a, b in elegidos:
        lo, hi = bisect.bisect_left(mt, a), bisect.bisect_right(mt, b)
        terminos = [t for t, _ in Counter(h[1] for h in hits[lo:hi]).most_common(2)]
        w = cs_d[k + 1] - cs_d[j]
        volumen = (cs_e[k + 1] - cs_e[j]) / w if w > 0 else 1.0
        razones = []
        if temas:
            best = None
            for t0, t1, lab in temas:
                ov = min(b, t1) - max(a, t0)
                if ov > 0 and (best is None or ov > best[0]):
                    best = (ov, lab)
            if best and best[0] / (b - a) >= 0.5 and best[1]:
                razones.append(f"tema «{best[1]}»")
        if terminos:
            razones.append("menciona " + ", ".join(terminos))
        if _clip01((volumen - 0.9) / 0.6) >= 0.5:
            razones.append("voz con energía")
        limpias = (gap_b[j] >= 0.6 and gap_a[k] >= 0.6) or j == 0 or k == n_t - 1
        razones.append("empieza y acaba en pausa" if limpias else "empieza y acaba en un final de frase")
        if pk is None:
            razones.append("según volumen y silencios (sin transcripción)")
        titulo = _title(toks, j, k) or f"Momento {_mmss(a)}"
        out.append({"start": round(a, 2), "end": round(b, 2), "title": titulo,
                    "score": round(score, 3), "why": " · ".join(razones)})
    out.sort(key=lambda x: -x["score"])
    return out


# ------------------------------------------------------------------ crear un Short
def _trim_keys(nc, la: float, lb: float, src_a: float, src_b: float, image: bool) -> None:
    """Quita de los fotogramas clave lo que queda fuera del tramo (las imágenes cuentan desde su inicio)."""
    for name in ("zoom_kf", "layout_kf", "vol_kf", "op_kf"):
        lst = getattr(nc, name, None)
        if not lst:
            continue
        keep = []
        for kf in lst:
            t = float(kf.get("t", 0.0))
            if image:
                if 0.0 <= t - la <= lb - la + 1e-6:
                    keep.append({**kf, "t": round(t - la, 4)})
            elif src_a - 1e-3 <= t <= src_b + 1e-3:
                keep.append(kf)
        setattr(nc, name, keep)


def build_short(p: Project, pick: dict, number: int = 1) -> Project:
    """Proyecto nuevo con SOLO el tramo [start, end] (en formato Short). El original no se toca."""
    a, b = float(pick["start"]), float(pick["end"])
    q = Project.from_dict(copy.deepcopy(p.to_dict()))
    nuevos = {}
    for c in list(q.clips.values()):
        lo, hi = max(a, c.start), min(b, c.end)
        if hi - lo <= 0.02:
            continue
        la, lb = lo - c.start, hi - c.start
        nc = copy.deepcopy(c)
        nc.id = new_id()
        nc.start = lo - a
        nc.source_in = c.piece_src(la, lb)
        nc.duration = hi - lo
        src_a = min(c.src_at(la), c.src_at(lb))
        src_b = max(c.src_at(la), c.src_at(lb))
        m = q.media.get(c.media_id)
        _trim_keys(nc, la, lb, src_a, src_b, bool(m and m.kind == KIND_IMAGE))
        nuevos[nc.id] = nc
    q.clips = nuevos
    marcas = []
    for mk in q.markers:
        if mk.end is not None:
            t, fin = max(mk.time, a), min(mk.end, b)
            if fin - t > 0.05:
                mk.time, mk.end = t - a, fin - a
                marcas.append(mk)
        elif a <= mk.time < b:
            mk.time = mk.time - a
            marcas.append(mk)
    q.markers = marcas
    q.suggestions, q.annotations, q.edits, q.cut_ok = [], [], [], []
    q.thumbnails, q.mark_in, q.mark_out = {}, None, None
    q.format = "short"
    _label, q.width, q.height = FORMATS["short"]
    q.fps = 60.0
    # mismo ajuste que «Formato Short» del proyecto: encuadre automático y subtítulos de Shorts
    from ..core.subtitles import PRESETS, SHORTS
    from ..core.controller import ProjectController   # solo la regla de encuadre (no crea nada)
    for c in q.clips.values():
        if c.text is None and not c.locked and c.layout is None:
            c.layout = ProjectController._auto_layout(None, q, q.media_of(c), c.track_id)
    st = q.subtitles
    if st.preset == "YouTube clásico":
        for k, v in PRESETS[SHORTS].items():
            setattr(st, k, v)
        st.preset = SHORTS
    q.name = f"{p.name} — Short {number} · {pick['title']}"
    return q


def short_file_name(p: Project, pick: dict, number: int) -> str:
    base = f"{p.name} — Short {number} · {pick['title']}"
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", base).strip(" .")[:150]
    return base + ".eia"


def write_short(p: Project, pick: dict, number: int, folder: str) -> str:
    """Guarda el Short como .eia nuevo en «folder» (sin pisar nada) y devuelve su ruta."""
    q = build_short(p, pick, number)
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(short_file_name(p, pick, number))
    path, k = os.path.join(folder, stem + ext), 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({k}){ext}")
        k += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q.to_dict(), f, ensure_ascii=False,
                  default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    os.replace(tmp, path)
    return path
