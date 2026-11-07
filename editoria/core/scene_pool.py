"""
🎬 Escenas sin usar (panel IA ✨ → Inicio): las escenas de tus videos que todavía no salen en la línea de tiempo, para
elegirlas tú (en el orden que quieras) y meterlas:
  · en los HUECOS (donde hay audio debajo y nada en la pista de video principal): una escena = un plano, en tu orden;
    si la canción tiene su ritmo reconocido, cada plano termina en un golpe (como mucho 2 compases); si no, la escena
    dura lo que dura (o hasta que se acaba el hueco);
  · o «Desde cero»: la pista de video se vacía en el tramo de la canción y se rellena SOLO con esas escenas, un plano
    por compás, turnándolas en tu orden (cada vez que vuelve a una, sigue por donde se quedó: no repite el trozo).

  scenes_of(path, duration, progress, cancelled) -> [(inicio, fin)]   (cortes de cámara; lo largo, en trozos de 8 s)
  thumb(path, t) -> ruta de la miniatura (se guarda)
  unused(project, media_id, scenes) -> las que no salen en ningún clip de video
  gaps_over_audio(project, track_id) -> [(a, b)]   huecos de esa pista de video con audio debajo
  fill_items(scenes, gaps, beats) -> planos para los huecos
  scratch_items(scenes, a, b, beats) -> planos «desde cero»
  (scene = (media_id, inicio, fin); plano = {"media_id", "start", "source_in", "duration"}, en la línea de tiempo)
"""
from __future__ import annotations

import os

from . import media as media_tools
from .model import KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO
from .paths import cache_dir

CHUNK = 8.0          # una escena larga (sin cortes) se ofrece en trozos de 8 s
MIN_SCENE = 0.6
MAX_BEATS = 8        # en los huecos, un plano dura como mucho 2 compases
SCRATCH_BEATS = 4    # «desde cero»: un plano por compás
NO_BEAT_SHOT = 2.0   # sin ritmo reconocido, «desde cero» corta cada 2 s


def scenes_from_cuts(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    edges = [0.0] + sorted(c for c in cuts if 0.0 < c < duration) + [duration]
    out = []
    for a, b in zip(edges, edges[1:]):
        n = max(1, int((b - a) // CHUNK + (1 if (b - a) % CHUNK > CHUNK / 2 else 0)))
        step = (b - a) / n
        for k in range(n):
            s0, s1 = a + k * step, a + (k + 1) * step
            if s1 - s0 >= MIN_SCENE:
                out.append((round(s0, 3), round(s1, 3)))
    return out


def scenes_of(path: str, duration: float, progress=None, cancelled=None) -> list[tuple[float, float]]:
    from . import scene_cuts
    cuts = scene_cuts.detect(path, 0.0, duration, "normal", progress, cancelled)
    return scenes_from_cuts(cuts, duration)


def thumb(path: str, t: float) -> str | None:
    out = os.path.join(str(cache_dir("escenas_miniaturas")), f"{media_tools.cache_key(path)}_{t:.2f}.jpg")
    if os.path.exists(out):
        return out
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}",
                               "-i", path, "-frames:v", "1", "-vf", "scale=192:-2", "-q:v", "5", out], timeout=60)
    return out if r.returncode == 0 and os.path.exists(out) else None


def used_ranges(project, media_id: str) -> list[tuple[float, float]]:
    """Los trozos de ese archivo que ya salen en la línea de tiempo (clips de video)."""
    out = []
    for c in project.clips.values():
        tr = project.track(c.track_id)
        if c.media_id == media_id and tr is not None and tr.kind == TRACK_VIDEO:
            out.append((float(c.source_in), float(c.source_in) + float(c.src_len)))
    return out


def used_by_media(project) -> dict[str, list[tuple[float, float]]]:
    """Como used_ranges, para todos los archivos a la vez: una sola pasada por los clips (⚡ sin buscar pista a pista)."""
    video_ids = {t.id for t in project.tracks if t.kind == TRACK_VIDEO}
    out: dict[str, list[tuple[float, float]]] = {}
    for c in project.clips.values():
        if c.track_id in video_ids:
            out.setdefault(c.media_id, []).append((float(c.source_in), float(c.source_in) + float(c.src_len)))
    return out


def unused(project, media_id: str, scenes: list[tuple[float, float]],
           used: list[tuple[float, float]] | None = None) -> list[tuple[float, float]]:
    """Las escenas que no salen: ningún clip cubre más de un 30 % de ellas. «used» si ya se tiene (used_by_media)."""
    if used is None:
        used = used_ranges(project, media_id)
    out = []
    for a, b in scenes:
        cover = sum(max(0.0, min(b, y) - max(a, x)) for x, y in used)
        if cover < 0.3 * (b - a):
            out.append((a, b))
    return out


def _union(spans: list[tuple[float, float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def main_video_track(project):
    v = [t for t in project.tracks if t.kind == TRACK_VIDEO]
    return v[-1] if v else None        # (la de abajo: la principal, donde van los planos de los edits)


def gaps_over_audio(project, track_id: str, min_len: float = 0.3) -> list[tuple[float, float]]:
    audio = _union([(c.start, c.end) for c in project.clips.values() if c.enabled and
                    (tr := project.track(c.track_id)) is not None and tr.kind == TRACK_AUDIO])
    video = _union([(c.start, c.end) for c in project.clips_on(track_id)])
    gaps = []
    for a, b in audio:
        t = a
        for x, y in video:
            if y <= t or x >= b:
                continue
            if x - t >= min_len:
                gaps.append((round(t, 4), round(min(x, b), 4)))
            t = max(t, y)
        if b - t >= min_len:
            gaps.append((round(t, 4), round(b, 4)))
    return gaps


def fill_items(scenes: list[tuple[str, float, float]], gaps: list[tuple[float, float]],
               beats: list[float]) -> list[dict]:
    """Cada escena (en tu orden) = un plano en el primer hueco libre. Con ritmo, el plano termina en un golpe."""
    period = _period(beats)
    queue = list(scenes)
    out = []
    for g0, g1 in gaps:
        t = g0
        while queue and g1 - t >= 0.25:
            mid, a, b = queue[0]
            want = min(g1, t + (b - a), t + (MAX_BEATS * period if beats else 1e9))
            end = want
            if beats and want < g1 - 1e-3:            # al ritmo: el último golpe que cabe (como poco medio golpe)
                ok = [x for x in beats if t + max(0.25, period * 0.5) <= x <= want + 1e-3]
                if ok:
                    end = ok[-1]
            if end - t < 0.25:
                break
            out.append({"media_id": mid, "start": round(t, 4), "source_in": round(a, 4),
                        "duration": round(end - t, 4)})
            queue.pop(0)
            t = end
    return out


def scratch_items(scenes: list[tuple[str, float, float]], a: float, b: float, beats: list[float]) -> list[dict]:
    """«Desde cero»: de a a b, un plano por compás (o cada 2 s sin ritmo), turnando tus escenas en tu orden."""
    if not scenes or b - a < 0.3:
        return []
    bs = [x for x in beats if a + 1e-3 < x < b - 1e-3]
    if bs:
        edges = [a] + bs[SCRATCH_BEATS - 1::SCRATCH_BEATS]
    else:
        n = max(1, int(round((b - a) / NO_BEAT_SHOT)))
        edges = [a + (b - a) * k / n for k in range(n)]
    if edges[-1] < b - 0.25:
        edges.append(b)
    else:
        edges[-1] = b
    cursor = {k: s[1] for k, s in enumerate(scenes)}
    out, k = [], 0
    for s0, s1 in zip(edges, edges[1:]):
        L = s1 - s0
        for _try in range(len(scenes)):           # la siguiente de tu lista en la que quepa el plano
            mid, x, y = scenes[k % len(scenes)]
            if y - x >= min(L, 0.5):
                break
            k += 1
        mid, x, y = scenes[k % len(scenes)]
        src = cursor[k % len(scenes)]
        if src + L > y:                             # se acabó esa escena: vuelve a su principio
            src = x
        dur = min(L, y - src)
        out.append({"media_id": mid, "start": round(s0, 4), "source_in": round(src, 4), "duration": round(dur, 4)})
        cursor[k % len(scenes)] = src + dur
        k += 1
    return out


def _period(beats: list[float]) -> float:
    if len(beats) < 3:
        return 0.5
    d = sorted(y - x for x, y in zip(beats, beats[1:]))
    return float(d[len(d) // 2])


def video_media(project, missing=()) -> list:
    return [m for m in project.media.values() if m.kind == KIND_VIDEO and m.id not in missing and m.duration]
