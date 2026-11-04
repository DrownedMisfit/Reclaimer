"""
🎯 ENCUADRE VERTICAL QUE SIGUE LA ACCIÓN (Shorts y edits con clips horizontales).

En vez de ver el clip entero con el fondo desenfocado, se llena la pantalla vertical recortando los lados, y el
recorte se MUEVE para seguir lo que pasa (como el «reencuadre automático» de otros editores):
  · lo que se mueve DE VERDAD (se descuenta el movimiento de la cámara: si giras la cámara en el juego no cuenta todo
    como «acción»; el HUD quieto tampoco),
  · las caras (cinemáticas),
  · y una ligera preferencia por el centro (en los juegos la mira y el personaje suelen ir ahí).
El recorrido se suaviza como una cámara (sin temblores ni tirones) y, en cada cambio de plano, salta al momento.

  follow_path(path, a, b, src_w, src_h, box_aspect) -> [{"t": segundo del archivo, "x": 0–1, "i": "linear"}]
  from_samples(samples, ...)  -> lo mismo desde el seguimiento de un objeto que marcas tú (🎯 Seguir objeto)
El resultado se guarda en la disposición del clip: layout["follow"] (ver core/transform.py, follow_at).
"""
from __future__ import annotations

import numpy as np

from .base import CancelFn, ProgressFn, check_cancel, report

FPS = 6.0           # muestras por segundo (suficiente: luego se suaviza)
WORK_W = 320
TAU = 0.8           # «inercia» de la cámara (segundos)
MAX_SPEED = 0.45    # como mucho, el recorte se mueve 0,45 anchos de imagen por segundo (salvo en un corte)


def visible_frac(src_w: int, src_h: int, box_aspect: float) -> float:
    """Qué parte del ANCHO del clip se ve al llenar una caja de esa forma (ancho/alto) recortando los lados."""
    if src_w <= 0 or src_h <= 0:
        return 1.0
    return float(min(1.0, box_aspect / (src_w / src_h)))


def _cuts(frames: list[np.ndarray]) -> set[int]:
    """Índices donde empieza un plano nuevo (cambio brusco de histograma)."""
    import cv2
    out = set()
    prev = None
    for i, f in enumerate(frames):
        h = cv2.calcHist([f], [0], None, [32], [0, 256]).ravel()
        h /= max(1.0, h.sum())
        if prev is not None and 0.5 * float(np.abs(h - prev).sum()) > 0.45:
            out.add(i)
        prev = h
    return out


def _targets(frames: list[np.ndarray], color: list[np.ndarray], cuts: set[int]) -> np.ndarray:
    """Para cada muestra: (x del interés 0–1, peso). Movimiento propio + caras + preferencia por el centro."""
    import cv2
    h, w = frames[0].shape
    xs = (np.arange(w) + 0.5) / w
    center = np.exp(-0.5 * ((xs - 0.5) / 0.32) ** 2)
    out = np.zeros((len(frames), 2))
    face = None
    try:
        from .tracking import detect_faces
        face = detect_faces
    except Exception:  # noqa: BLE001 - sin detector de caras: solo movimiento
        face = None
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    for i, f in enumerate(frames):
        col = np.zeros(w)
        if i > 0 and i not in cuts:
            a = frames[i - 1].astype(np.float32)
            b = f.astype(np.float32)
            (dx, dy), _resp = cv2.phaseCorrelate(a, b, win)        # movimiento de la cámara
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            a_al = cv2.warpAffine(a, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
            res = cv2.GaussianBlur(np.abs(b - a_al), (5, 5), 0)
            raw = np.abs(b - a)
            mov = (res > 18) & (raw > 10)                           # se mueve de verdad (el HUD quieto, no)
            m = int(max(2, abs(dx) + 2))
            mov[:, :m] = False
            mov[:, w - m:] = False
            col = mov.sum(axis=0).astype(np.float64)
            if col.sum() > 0.25 * h * w:                             # todo se mueve (explosión, fundido): no sirve
                col[:] = 0
        if face is not None:
            try:
                for fx, fy, fw, fh, conf in face(color[i]):
                    cx = (fx + fw / 2) / color[i].shape[1]
                    amp = conf * (fw * fh) / (color[i].shape[0] * color[i].shape[1]) * h * w * 3
                    col += amp * np.exp(-0.5 * ((xs - cx) / max(0.03, fw / color[i].shape[1] / 2)) ** 2)
            except Exception:  # noqa: BLE001
                face = None
        weight = float(col.sum())
        prof = col * center + 1e-9
        out[i] = (float((prof * xs).sum() / prof.sum()) if weight > 0 else 0.5, weight)
    return out


def _camera(ts: np.ndarray, target: np.ndarray, weight: np.ndarray, cuts: set[int], vis: float) -> np.ndarray:
    """Recorrido suave como una cámara: inercia, velocidad máxima, zona muerta y salto en los cortes."""
    lo, hi = vis / 2, 1 - vis / 2
    n = len(ts)
    seg_starts = sorted({0} | set(cuts))
    out = np.empty(n)
    for si, s in enumerate(seg_starts):
        e = seg_starts[si + 1] if si + 1 < len(seg_starts) else n
        tgt = target[s:e].copy()
        wgt = weight[s:e]
        good = wgt > np.percentile(wgt, 25) if e - s > 3 else wgt >= 0
        if good.any():                    # las muestras sin nada que seguir toman la última buena
            last = float(np.average(tgt[good], weights=wgt[good] + 1e-9)) if not good[0] else tgt[0]
            for k in range(len(tgt)):
                if good[k]:
                    last = tgt[k]
                else:
                    tgt[k] = last
        tgt = np.clip(tgt, lo, hi)

        def ema(vals, tt):
            y = np.empty_like(vals)
            y[0] = vals[0]
            for k in range(1, len(vals)):
                dt = max(1e-3, abs(tt[k] - tt[k - 1]))
                a = 1 - np.exp(-dt / TAU)
                y[k] = y[k - 1] + a * (vals[k] - y[k - 1])
            return y
        tt = ts[s:e]
        fwd = ema(tgt, tt)
        both = ema(fwd[::-1], tt[::-1])[::-1]               # ida y vuelta: sin retraso
        cam = np.empty_like(both)
        cam[0] = both[0]
        dead = vis * 0.12                                    # pequeños movimientos: la cámara no se mueve
        for k in range(1, len(both)):
            dt = max(1e-3, tt[k] - tt[k - 1])
            d = both[k] - cam[k - 1]
            if abs(d) < dead:
                d = 0.0
            else:
                d -= np.sign(d) * dead
            lim = MAX_SPEED * dt
            cam[k] = cam[k - 1] + float(np.clip(d, -lim, lim))
        out[s:e] = np.clip(cam, lo, hi)
    return out


def _keyframes(ts: np.ndarray, xs: np.ndarray, cuts: set[int]) -> list[dict]:
    kf = []
    for k, (t, x) in enumerate(zip(ts, xs)):
        if k in cuts and kf:              # corte: la clave anterior justo antes, para saltar (no deslizar)
            kf.append({"t": round(float(t) - 0.01, 3), "x": kf[-1]["x"], "i": "linear"})
        kf.append({"t": round(float(t), 3), "x": round(float(x), 4), "i": "linear"})
    return simplify(kf)


def simplify(kf: list[dict], tol: float = 0.006) -> list[dict]:
    if len(kf) <= 2:
        return kf
    out = [kf[0]]
    for i in range(1, len(kf) - 1):
        a, b, c = out[-1], kf[i], kf[i + 1]
        u = (b["t"] - a["t"]) / max(c["t"] - a["t"], 1e-6)
        if abs(a["x"] + (c["x"] - a["x"]) * u - b["x"]) > tol or c["t"] - b["t"] < 0.05:
            out.append(b)
    out.append(kf[-1])
    return out


def follow_path(path: str, a: float, b: float, src_w: int, src_h: int, box_aspect: float,
                progress: ProgressFn = None, cancelled: CancelFn = None) -> list[dict]:
    """Recorrido automático del encuadre entre los segundos a y b del archivo."""
    import cv2
    from .tracking import read_frames, work_size
    vis = visible_frac(src_w, src_h, box_aspect)
    if vis >= 0.98:
        return []
    size = work_size(src_w, src_h, WORK_W)
    gray, color, ts = [], [], []
    total = max(0.1, b - a)
    for t, frame in read_frames(path, a, b - a, size, FPS):
        check_cancel(cancelled)
        gray.append(cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (3, 3), 0))
        color.append(frame)
        ts.append(t)
        if len(ts) % 12 == 0:
            report(progress, 0.8 * (t - a) / total, f"🎯 Mirando dónde está la acción… {t - a:.0f} de {total:.0f} s")
    if len(ts) < 2:
        return []
    ts_a = np.array(ts)
    cuts = _cuts(gray)
    tw = _targets(gray, color, cuts)
    report(progress, 0.95, "🎯 Suavizando el encuadre…")
    xs = _camera(ts_a, tw[:, 0], tw[:, 1], cuts, vis)
    return _keyframes(ts_a, xs, cuts)


def from_samples(samples: list[tuple], src_w: int, src_h: int, box_aspect: float) -> list[dict]:
    """Desde el seguimiento de un objeto (🎯 Seguir objeto): el encuadre lo acompaña (sin zoom)."""
    if not samples:
        return []
    vis = visible_frac(src_w, src_h, box_aspect)
    arr = np.array(samples, dtype=np.float64)
    xs = _camera(arr[:, 0], arr[:, 1], np.ones(len(arr)), set(), vis)
    return _keyframes(arr[:, 0], xs, set())
