"""
👤 Identificar personajes por SILUETA (y sus líneas), no por el fotograma entero.

Enseñar (2–5 ejemplos): marcas al personaje con un clic; SAM 2.1 recorta su silueta. De cada ejemplo se guarda:
  · sus COLORES PROPIOS: los que tiene la figura y no su fondo (pelo rosa, armadura…), con su tamaño y forma;
  · dos huellas CLIP: la figura recortada y su DIBUJO DE LÍNEAS (contorno + sombras, piezas de la armadura).
Buscar (ligero): cada video se recorre a 1 fotograma por segundo en miniatura (128×72) y se busca la ventana del
tamaño del personaje donde más se juntan sus colores propios. Solo los mejores candidatos se miran de cerca con
CLIP (figura y líneas) en esa ventana. Lo recorrido se guarda (datos/cache/siluetas): la siguiente búsqueda, de
cualquier personaje, es casi instantánea.

  teach(name, rgb, mask) · names() · search(name, videos, progress, cancelled) -> [Moment]
"""
from __future__ import annotations

import json
import os
import threading

import numpy as np

from ..core import media as media_tools
from ..core.paths import app_data_dir, cache_dir
from .base import check_cancel, report

STEP = 1.0                  # segundos entre fotogramas al recorrer un video
WORK_W = 448                # anchura a la que se miran de cerca los candidatos
MAP_W, MAP_H = 128, 72      # miniatura del índice de colores
N_BINS = 188
VERSION = 3
_lock = threading.Lock()


# ------------------------------------------------------------------ guardar lo aprendido
def _store() -> str:
    return str(app_data_dir() / "personajes_silueta.json")


def load() -> dict:
    try:
        with open(_store(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    tmp = _store() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, _store())


def names() -> dict[str, int]:
    """{personaje: nº de ejemplos}"""
    return {k: len(v.get("examples", [])) for k, v in load().items() if v.get("examples")}


def forget(name: str):
    with _lock:
        d = load()
        d.pop(name, None)
        _save(d)


# ------------------------------------------------------------------ imágenes
def _square(img: np.ndarray, size: int = 224, fill: int = 0) -> np.ndarray:
    import cv2
    h, w = img.shape[:2]
    s = size / max(h, w)
    small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    out = np.full((size, size, 3), fill, np.uint8)
    y0, x0 = (size - small.shape[0]) // 2, (size - small.shape[1]) // 2
    out[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
    return out


def lines_of(rgb: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """El dibujo de líneas: bordes interiores (sombras, piezas) + el contorno de la silueta, blanco sobre negro."""
    import cv2
    gray = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    med = float(np.median(gray))
    edges = cv2.Canny(gray, int(max(10, 0.66 * med)), int(min(255, 1.33 * med + 30)))
    if mask is not None:
        m = (mask > 127).astype(np.uint8)
        edges = edges * cv2.dilate(m, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(edges, cnts, -1, 255, 2)
    return np.repeat(edges[..., None], 3, axis=2)


def example_images(rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(figura sin fondo, dibujo de líneas) del ejemplo, 224×224."""
    ys, xs = np.nonzero(mask > 127)
    if len(xs) == 0:
        raise ValueError("La silueta está vacía: marca el personaje otra vez.")
    h, w = mask.shape
    pad = int(0.08 * max(xs.max() - xs.min(), ys.max() - ys.min()))
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad)
    crop, m = rgb[y0:y1, x0:x1].copy(), mask[y0:y1, x0:x1]
    fig = crop.copy()
    fig[m <= 127] = 128                                  # fondo gris: solo cuenta la figura
    return _square(fig, fill=128), _square(lines_of(crop, m))


def color_bins(rgb: np.ndarray) -> np.ndarray:
    """Cada píxel → uno de 188 colores: 30 tonos × 3 saturaciones × 2 luces, y 8 grises (negro … blanco)."""
    import cv2
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
    h, sat, v = hsv[..., 0].astype(np.int32), hsv[..., 1].astype(np.int32), hsv[..., 2].astype(np.int32)
    chroma = (np.minimum(h * 30 // 180, 29) * 3 + np.clip((sat - 40) * 3 // 216, 0, 2)) * 2 + (v >= 128)
    gray = 180 + np.minimum(v * 8 // 256, 7)
    return np.where((sat >= 40) & (v >= 40), chroma, gray).astype(np.uint8)


def _hist(bins: np.ndarray, sel: np.ndarray) -> np.ndarray:
    hst = np.bincount(bins[sel].ravel(), minlength=N_BINS).astype(np.float32)
    return hst / max(1.0, hst.sum())


def teach(name: str, rgb: np.ndarray, mask: np.ndarray, source: str = "", t: float = 0.0) -> int:
    """Añade un ejemplo del personaje. Devuelve cuántos ejemplos tiene ya."""
    import cv2

    from . import embeddings
    fig, lin = example_images(rgb, mask)
    h, w = mask.shape
    ys, xs = np.nonzero(mask > 127)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    small = cv2.resize(rgb, (MAP_W, MAP_H), interpolation=cv2.INTER_AREA)
    m_small = cv2.resize((mask > 127).astype(np.uint8), (MAP_W, MAP_H), interpolation=cv2.INTER_NEAREST) > 0
    if m_small.sum() < 4:
        raise ValueError("El personaje se ve muy pequeño en ese fotograma: elige uno donde se vea más grande.")
    bins = color_bins(small)
    bx = (slice(int(y0 * MAP_H / h), max(int(y0 * MAP_H / h) + 1, int(np.ceil(y1 * MAP_H / h)))),
          slice(int(x0 * MAP_W / w), max(int(x0 * MAP_W / w) + 1, int(np.ceil(x1 * MAP_W / w)))))
    enc = embeddings.get("clip_image")
    vecs = enc.encode(np.stack([fig, lin, _square(rgb[y0:y1, x0:x1])]))
    with _lock:
        d = load()
        ex = d.setdefault(name.strip(), {"examples": []})["examples"]
        ex.append({"vec": vecs[0].round(5).tolist(), "lines": vecs[1].round(5).tolist(),
                   "box": vecs[2].round(5).tolist(),
                   "fg": _hist(bins, m_small).round(5).tolist(), "bg": _hist(bins, ~m_small).round(5).tolist(),
                   "boxh": _hist(bins[bx], np.ones(bins[bx].shape, bool)).round(5).tolist(),
                   "size": [round(float(x1 - x0) / w, 4), round(float(y1 - y0) / h, 4)], "src": source,
                   "t": round(float(t), 2)})
        _save(d)
        return len(ex)


# ------------------------------------------------------------------ recorrer los videos (miniaturas de colores)
def _index_path(path: str) -> str:
    return os.path.join(str(cache_dir("siluetas")), f"{media_tools.cache_key(path)}_v{VERSION}.npz")


def index_media(path: str, duration: float, progress=None, cancelled=None) -> tuple[np.ndarray, np.ndarray]:
    """(tiempos [N], colores [N, 72, 128]) de un video. Se guarda: la siguiente vez es instantáneo."""
    import subprocess
    cp = _index_path(path)
    if os.path.exists(cp):
        d = np.load(cp)
        return d["times"], d["bins"]
    proc = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-skip_loop_filter", "all",
                             "-i", path, "-an", "-sn",   # ⚡ sin filtro de desbloqueo: ~25 % más rápido; en imágenes pequeñas para analizar no cambia nada
                             "-vf", f"fps=1/{STEP},scale={MAP_W}:{MAP_H}:flags=area", "-pix_fmt", "rgb24",
                             "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    size = MAP_W * MAP_H * 3
    times, maps = [], []
    total = max(1, int(duration / STEP))
    try:
        while True:
            if cancelled is not None and cancelled():
                proc.kill()
                check_cancel(cancelled)
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            maps.append(color_bins(np.frombuffer(buf, np.uint8).reshape(MAP_H, MAP_W, 3)))
            times.append(round(len(times) * STEP, 2))          # el filtro fps toma el fotograma de k·STEP
            if len(times) % 30 == 0:
                report(progress, min(0.99, len(times) / total),
                       f"👤 Recorriendo el video · {int(100 * min(1, len(times) / total))} %")
    finally:
        proc.stdout.close()
        proc.wait()
    t = np.array(times, np.float32)
    b = np.stack(maps) if maps else np.zeros((0, MAP_H, MAP_W), np.uint8)
    np.savez_compressed(cp, times=t, bins=b)
    return t, b


def _weights(ex: list) -> np.ndarray:
    """Peso de cada color: ~1 si es del personaje y no de su fondo; 0 si es del fondo o no lo tiene."""
    fg = np.mean([e["fg"] for e in ex], axis=0)
    bg = np.mean([e["bg"] for e in ex], axis=0)
    w = fg / (fg + bg + 1e-3)
    w[fg < 0.01] = 0.0                                    # colores sueltos (ruido, bordes)
    return w.astype(np.float32)


def _windows(ex: list) -> list[tuple[int, int]]:
    """Tamaños de ventana (alto, ancho en la miniatura): el del personaje en los ejemplos, más grande y más pequeño."""
    sw = float(np.median([e["size"][0] for e in ex]))
    sh = float(np.median([e["size"][1] for e in ex]))
    out = set()
    for k in (0.5, 0.75, 1.0, 1.4):
        out.add((min(MAP_H, max(3, int(round(sh * k * MAP_H)))), min(MAP_W, max(3, int(round(sw * k * MAP_W))))))
    return sorted(out)


def _fg(ex: list) -> np.ndarray:
    return np.mean([e["fg"] for e in ex], axis=0).astype(np.float32)


def _fill(ex: list, weights: np.ndarray) -> float:
    """Cuánto llena el personaje su propio recuadro (con sus colores propios), en los ejemplos."""
    v = [float(np.dot(weights, e["boxh"])) for e in ex if "boxh" in e]
    return max(0.15, float(np.median(v))) if v else 0.5


def color_scores(bins: np.ndarray, weights: np.ndarray, wins, fg: np.ndarray | None = None, fill: float = 0.5
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Para cada fotograma: puntuación de la mejor ventana y su recuadro (x0, y0, x1, y1 normalizados).
    Puntuación = si sus colores propios están en la MISMA PROPORCIÓN que en él (pelo rosa + vestido negro + piel…;
    algo solo rosa no basta) × si llenan la ventana tanto como él llena su recuadro."""
    import cv2
    n = len(bins)
    best = np.zeros(n, np.float32)
    rect = np.zeros((n, 4), np.float32)
    own = [int(b) for b in np.nonzero(weights > 0)[0]]
    if not own:
        return best, rect
    ref = np.array([fg[b] for b in own] if fg is not None else [1.0] * len(own), np.float32)
    ref /= max(1e-6, ref.sum())
    wts = np.array([weights[b] for b in own], np.float32)
    for i in range(n):
        planes = [(bins[i] == b).astype(np.float32) for b in own]
        for hh, ww in wins:
            y0, y1, x0, x1 = hh // 2, MAP_H - (hh - 1) // 2, ww // 2, MAP_W - (ww - 1) // 2   # ventana entera dentro
            p = np.stack([cv2.blur(pl, (ww, hh), borderType=cv2.BORDER_CONSTANT)[y0:y1, x0:x1] for pl in planes])
            mean = np.tensordot(wts, p, 1)                         # cuánto de sus colores propios hay junto
            tot = p.sum(axis=0) + 1e-6
            inter = np.minimum(p / tot, ref[:, None, None]).sum(axis=0)   # ¿en la misma proporción que en él?
            # la proporción manda; la cantidad, solo hasta lo que él llena su recuadro (no premia un globo macizo)
            f = inter * np.minimum(1.0, mean / fill) if fg is not None else mean
            k = int(f.argmax())
            v = float(f.flat[k])
            if v > best[i]:
                cy, cx = divmod(k, f.shape[1])
                cy, cx = cy + y0, cx + x0
                best[i] = v
                rect[i] = ((cx - ww / 2) / MAP_W, (cy - hh / 2) / MAP_H, (cx + ww / 2) / MAP_W, (cy + hh / 2) / MAP_H)
    return best, rect


def _crop(img: np.ndarray, r) -> np.ndarray:
    h, w = img.shape[:2]
    pw, ph = 0.12 * (r[2] - r[0]), 0.12 * (r[3] - r[1])
    x0, x1 = int(max(0.0, r[0] - pw) * w), int(min(1.0, r[2] + pw) * w)
    y0, y1 = int(max(0.0, r[1] - ph) * h), int(min(1.0, r[3] + ph) * h)
    return img[y0:max(y1, y0 + 2), x0:max(x1, x0 + 2)]


# ------------------------------------------------------------------ buscar
def search(name: str, videos: list[tuple[str, str, float]], progress=None, cancelled=None,
           max_results: int = 40, n_check: int = 80) -> list:
    """videos = [(media_id, ruta, duración)] → apariciones del personaje (Moment), las más seguras primero."""
    from . import embeddings
    from .moments import Moment
    ex = [e for e in load().get(name, {}).get("examples", []) if "fg" in e]
    if not ex:
        raise RuntimeError(f"Todavía no le enseñaste «{name}» (👤 Enseñar un personaje por su silueta…).")
    weights, wins = _weights(ex), _windows(ex)
    fig = np.array([e["vec"] for e in ex], np.float32)
    boxv = np.array([e["box"] for e in ex], np.float32)
    lin = np.array([e["lines"] for e in ex], np.float32)
    frames = []                                              # (color, media, t, ruta, recuadro)
    for i, (mid, path, dur) in enumerate(videos):
        t, b = index_media(path, dur, lambda f, txt, i=i: report(
            progress, 0.7 * (i + f) / max(1, len(videos)), f"{txt} ({i + 1}/{len(videos)})"), cancelled)
        check_cancel(cancelled)
        if not len(t):
            continue
        sc, rc = color_scores(b, weights, wins, _fg(ex), _fill(ex, weights))
        frames += [(float(sc[j]), mid, float(t[j]), path, rc[j]) for j in range(len(t))]
    if not frames:
        return []
    cs = np.array([f[0] for f in frames], np.float32)
    med = float(np.median(cs))
    mad = float(np.median(np.abs(cs - med))) * 1.4826 + 1e-3
    zc = (cs - med) / mad
    order = [int(j) for j in np.argsort(-cs)[:n_check] if zc[j] > 1.0 or cs[j] > 0.35]
    if not order:
        report(progress, 1.0, f"👤 «{name}» no aparece")
        return []
    # Mirar de cerca a los candidatos (y a unos cuantos fotogramas cualquiera, para saber qué es «parecido»)
    rng = np.random.default_rng(0)
    others = [int(j) for j in rng.choice(len(frames), min(12, len(frames)), replace=False) if int(j) not in order]
    enc = embeddings.get("clip_image")
    sims = {}
    todo = order + others
    for n_, j in enumerate(todo):
        check_cancel(cancelled)
        if n_ % 4 == 0:
            report(progress, 0.7 + 0.28 * n_ / len(todo), f"👤 Mirando de cerca {n_ + 1}/{len(todo)}…")
        _c, mid, tt, path, r = frames[j]
        img = media_tools.frame_rgb(path, tt, WORK_W)
        if img is None:
            continue
        crop = _crop(img, r)
        v = enc.encode(np.stack([_square(crop), _square(lines_of(crop))]))
        sims[j] = (float(max((boxv @ v[0]).max(), (fig @ v[0]).max())), float((lin @ v[1]).max()))
    ref = [sims[j][0] for j in others if j in sims]
    base = float(np.median(ref)) if ref else float(np.median([s[0] for s in sims.values()]))
    final = {}
    for j in order:
        if j in sims:
            s_fig, s_lin = sims[j]
            # colores propios juntos + CLIP (¿es esa figura?, frente a un fotograma cualquiera) + líneas
            final[j] = 0.6 * min(1.0, cs[j] / max(1e-3, cs[order[0]])) + 2.5 * (s_fig - base) + 0.1 * s_lin
    search.last = {round(frames[j][2], 1): (round(float(cs[j]), 3), round(sims[j][0] - base, 3), round(sims[j][1], 3),
                                          round(float(v), 3)) for j, v in final.items()}     # para ajustar
    if not final:
        return []
    top = max(final.values())
    thr = top - 0.25
    hits = sorted(((frames[j][1], frames[j][2], v) for j, v in final.items() if v >= thr),
                  key=lambda x: (x[0], x[1]))
    out: list = []
    cur = None
    for mid, tt, v in hits:
        if cur is not None and cur.media_id == mid and tt - cur.end <= STEP * 2.5:
            cur.end = tt + STEP / 2
            if v > cur.score:
                cur.best, cur.score = tt, v
        else:
            if cur is not None:
                out.append(cur)
            cur = Moment(mid, max(0.0, tt - STEP / 2), tt + STEP / 2, tt, v)
    if cur is not None:
        out.append(cur)
    for m in out:                                            # al menos 3 s para poder usarlo
        if m.end - m.start < 3.0:
            m.start, m.end = max(0.0, m.best - 1.5), m.best + 1.5
    out.sort(key=lambda m: -m.score)
    report(progress, 1.0, f"👤 {len(out)} apariciones de «{name}»")
    return out[:max_results]


def debug_scores(name: str, path: str, dur: float):
    """(tiempos, puntuación de color, recuadros): para ajustar/probar."""
    ex = [e for e in load().get(name, {}).get("examples", []) if "fg" in e]
    t, b = index_media(path, dur)
    w = _weights(ex)
    sc, rc = color_scores(b, w, _windows(ex), _fg(ex), _fill(ex, w))
    return t, sc, rc
