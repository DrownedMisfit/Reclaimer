"""
Módulo de IA: TRACKING (seguir un personaje u objeto) y DETECCIÓN DE CARAS.

1. Tú marcas un recuadro alrededor de lo que quieres seguir (o eliges una cara detectada).
2. Se leen los fotogramas del clip y un seguidor (OpenCV CSRT) va moviendo el recuadro.
3. El recorrido se suaviza (sin temblores) y se convierte en fotogramas clave de zoom
   que puedes editar después como cualquier otro.
"""
from __future__ import annotations

import os
import subprocess

import numpy as np

from ..core import media as media_tools
from ..core import transform
from .base import CancelFn, Cancelled, ProgressFn, check_cancel, report

WORK_WIDTH = 640  # se analiza a esta anchura (más rápido; el resultado es en proporciones)


def is_available() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False, "Falta OpenCV. Ejecuta INSTALAR.bat."
    return True, ""


def work_size(src_w: int, src_h: int, width: int = WORK_WIDTH) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0:
        return width, int(width * 9 / 16) // 2 * 2
    return width, max(2, int(round(width * src_h / src_w / 2)) * 2)


def read_frames(path: str, start: float, duration: float, size: tuple[int, int], fps: float = 15.0):
    """Fotogramas BGR (para OpenCV) desde start durante duration: genera (segundo, imagen)."""
    w, h = size
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", path,
            "-t", f"{max(0.05, duration):.3f}", "-vf", f"fps={fps},scale={w}:{h}", "-pix_fmt", "bgr24",
            "-f", "rawvideo", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=media_tools.NO_WINDOW)
    n = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
            i += 1
    finally:
        proc.kill()
        proc.wait()


def grab_frame(path: str, t: float, width: int = 960, src_w: int = 0, src_h: int = 0) -> np.ndarray | None:
    """Un fotograma BGR en el segundo t (para elegir qué seguir)."""
    size = work_size(src_w, src_h, width)
    for _t, frame in read_frames(path, t, 0.2, size, fps=10):
        return frame
    return None


# ------------------------------------------------------------------ caras
_face_model: str | None = None


def _quiet_cv():
    try:   # OpenCV avisa en cada detección de algo que no nos afecta: solo errores
        import cv2
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass


def _face_detector(w: int, h: int):
    _quiet_cv()
    import cv2
    global _face_model
    if _face_model is None:
        from huggingface_hub import hf_hub_download
        from .transcription import models_dir
        local = models_dir() / "caras" / "face_detection_yunet_2023mar.onnx"
        if local.exists():   # ya descargado: sin conectarse a internet
            _face_model = str(local)
        else:   # local_dir: archivo normal (sin enlaces simbólicos, que en Windows pueden fallar)
            _face_model = hf_hub_download("opencv/face_detection_yunet", "face_detection_yunet_2023mar.onnx",
                                          local_dir=str(models_dir() / "caras"))
    return cv2.FaceDetectorYN.create(_face_model, "", (w, h), 0.6, 0.3, 50)


def detect_faces(frame: np.ndarray) -> list[tuple[float, float, float, float, float]]:
    """Caras en la imagen: [(x, y, ancho, alto, confianza)] en proporciones 0–1, de mayor a menor."""
    h, w = frame.shape[:2]
    det = _face_detector(w, h)
    _ok, faces = det.detect(frame)
    out = []
    if faces is not None:
        for f in faces:
            x, y, fw, fh, conf = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
            out.append((max(0.0, x / w), max(0.0, y / h), fw / w, fh / h, conf))
    out.sort(key=lambda b: -(b[2] * b[3]))
    return out


# ---------------------------------------------------------------- seguir
def track(path: str, start: float, end: float, box: tuple[float, float, float, float],
          src_w: int, src_h: int, fps: float = 15.0, progress: ProgressFn = None,
          cancelled: CancelFn = None) -> list[tuple[float, float, float, float, float]]:
    """
    Sigue el recuadro box=(x, y, ancho, alto) (proporciones 0–1) desde start hasta end
    (segundos del archivo). Devuelve [(segundo, centro_x, centro_y, ancho, alto)] en 0–1.
    Se detiene si pierde el objeto más de medio segundo.
    """
    import cv2
    size = work_size(src_w, src_h)
    W, H = size
    tracker = None
    fallback = False   # si CSRT pierde el objeto, se sigue con MIL desde la última posición buena
    last_rect = None
    samples = []
    lost = 0
    total = max(end - start, 0.1)
    for t, frame in read_frames(path, start, end - start, size, fps):
        check_cancel(cancelled)
        if tracker is None:
            x, y, bw, bh = box
            rect = (int(x * W), int(y * H), max(4, int(bw * W)), max(4, int(bh * H)))
            tracker = cv2.TrackerCSRT_create()
            tracker.init(frame, rect)
            last_rect = rect
            samples.append((t, (rect[0] + rect[2] / 2) / W, (rect[1] + rect[3] / 2) / H, rect[2] / W, rect[3] / H))
            continue
        ok, r = tracker.update(frame)
        if not ok and not fallback and last_rect is not None:
            fallback = True
            tracker = cv2.TrackerMIL_create()
            tracker.init(frame, tuple(int(v) for v in last_rect))
            ok, r = tracker.update(frame)
        if ok:
            lost = 0
            last_rect = r
            samples.append((t, (r[0] + r[2] / 2) / W, (r[1] + r[3] / 2) / H, r[2] / W, r[3] / H))
        else:
            lost += 1
            if lost > fps * 0.5:
                break
        if len(samples) % 10 == 0:
            report(progress, (t - start) / total, f"🎯 Siguiendo… {t - start:.1f} de {total:.1f} s")
    return samples



# ------------------------------------------------- 🎯 seguimiento automático robusto (recorridos del clip)
LOW_CONF = 0.42      # parecido con el objeto por debajo de esto = dudoso (no se usa; se marca en rojo)
RECOVER_CONF = 0.62  # al buscarlo de nuevo, hace falta esto para darlo por encontrado
MAX_LOST_S = 2.5     # tanto tiempo sin encontrarlo = se para (y dice dónde)
PATCH = 40           # lado del «retrato» del objeto con el que se compara (píxeles)


def _new_tracker():
    import cv2
    for name in ("TrackerCSRT_create", "TrackerKCF_create", "TrackerMIL_create"):
        fn = getattr(cv2, name, None)
        if fn is not None:
            try:
                return fn()
            except Exception:  # noqa: BLE001
                continue
    for name in ("TrackerCSRT", "TrackerKCF", "TrackerMIL"):
        cls = getattr(cv2, name, None)
        if cls is not None and hasattr(cls, "create"):
            return cls.create()
    raise RuntimeError("Esta versión de OpenCV no trae ningún seguidor (CSRT/KCF/MIL).")


def _patch(gray: np.ndarray, rect, size: tuple[int, int]) -> np.ndarray | None:
    import cv2
    H, W = gray.shape[:2]
    x, y, w, h = (int(round(v)) for v in rect)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return cv2.resize(gray[y0:y1, x0:x1], size, interpolation=cv2.INTER_AREA)


def _similar(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Parecido 0–1 entre dos retratos del mismo tamaño (correlación; si son lisos, por el brillo)."""
    import cv2
    if a is None or b is None:
        return 0.0
    sa, sb = float(a.std()), float(b.std())
    if sa < 3 or sb < 3:
        if sa < 3 and sb < 3:
            return max(0.0, 1.0 - abs(float(a.mean()) - float(b.mean())) / 40.0)
        return 0.0
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])


class _Look:
    """Cómo es el objeto (para saber si el seguidor sigue encima de él y para buscarlo si se pierde)."""

    def __init__(self, gray: np.ndarray, rect):
        w, h = max(4.0, rect[2]), max(4.0, rect[3])
        s = PATCH / max(w, h)
        self.size = (max(8, int(round(w * s))), max(8, int(round(h * s))))
        self.ref = _patch(gray, rect, self.size)
        self.recent = self.ref
        self.prev = self.ref          # cómo era en el último fotograma bueno (cambios poco a poco: luz, giro, zoom)
        self.wh = (w, h)

    def score(self, gray, rect) -> float:
        p = _patch(gray, rect, self.size)
        return max(_similar(self.ref, p), _similar(self.recent, p), 0.97 * _similar(self.prev, p))

    def learn(self, gray, rect, conf: float):
        p = _patch(gray, rect, self.size)
        if p is None:
            return
        self.prev = p
        if self.recent is not None and conf > LOW_CONF + 0.1:
            self.recent = (0.75 * self.recent.astype(np.float32) + 0.25 * p.astype(np.float32)).astype(np.uint8)

    def search(self, gray, center, radius: float) -> tuple[float, tuple | None]:
        """Lo busca alrededor de center (con algo de cambio de tamaño): (parecido, rect)."""
        best = (0.0, None)
        for tmpl in (self.ref, self.recent):
            r = self._search(tmpl, gray, center, radius)
            if r[0] > best[0]:
                best = r
        return best

    def _search(self, ref, gray, center, radius: float) -> tuple[float, tuple | None]:
        import cv2
        if ref is None:
            return 0.0, None
        H, W = gray.shape[:2]
        best = (0.0, None)
        for sc in (0.85, 1.0, 1.18):
            w, h = int(round(self.wh[0] * sc)), int(round(self.wh[1] * sc))
            if w < 6 or h < 6 or w >= W or h >= H:
                continue
            x0, y0 = int(max(0, center[0] - radius - w / 2)), int(max(0, center[1] - radius - h / 2))
            x1, y1 = int(min(W, center[0] + radius + w / 2)), int(min(H, center[1] + radius + h / 2))
            if x1 - x0 <= w or y1 - y0 <= h:
                continue
            tmpl = cv2.resize(ref, (w, h), interpolation=cv2.INTER_LINEAR)
            if float(tmpl.std()) < 3:
                continue
            res = cv2.matchTemplate(gray[y0:y1, x0:x1], tmpl, cv2.TM_CCOEFF_NORMED)
            _mn, mx, _ml, loc = cv2.minMaxLoc(res)
            if mx > best[0]:
                best = (float(mx), (x0 + loc[0], y0 + loc[1], w, h))
        return best


def _frames_between(path: str, s0: float, s1: float, size: tuple[int, int], fps: float, cancelled: CancelFn):
    """Fotogramas de s0 a s1 (hacia atrás si s1 < s0): genera (segundo del archivo, imagen BGR)."""
    step = 1.0 / fps
    if s1 >= s0:
        yield from read_frames(path, s0, s1 - s0 + 0.5 * step, size, fps)
        return
    hi, last = s0, None
    chunk = max(1.0, round(3.0 * fps) / fps)      # trozos de ~3 s leídos hacia delante y recorridos al revés
    while hi > s1 + 1e-6:
        check_cancel(cancelled)
        lo = max(s1, hi - chunk)
        frames = list(read_frames(path, lo, hi - lo + 1.5 * step, size, fps))
        for t, f in reversed(frames):
            if t > s0 + 0.5 * step or (last is not None and t > last - 0.5 * step):
                continue
            last = t
            yield t, f
        if lo <= s1 + 1e-6:
            break
        hi = lo


def track_auto(path: str, s0: float, s1: float, box: tuple[float, float, float, float], src_w: int, src_h: int,
               fps: float = 15.0, progress: ProgressFn = None, cancelled: CancelFn = None,
               width: int = WORK_WIDTH) -> dict:
    """
    🎯 Sigue el objeto desde s0 hasta s1 (segundos del archivo; hacia atrás si s1 < s0), empezando con
    box = (centro_x, centro_y, ancho, alto) en 0–1. Se analiza a resolución reducida (width).
    En cada fotograma compara lo que ve el seguidor con cómo era el objeto: si no se parece, ese tramo es DUDOSO
    (no se usa) y lo busca alrededor de la última posición buena; si lo encuentra, sigue desde ahí.
    Devuelve {"samples": [[t, cx, cy, w, h, confianza]], "lost": [[a, b]], "end": t, "stopped": bool,
    "cancelled": bool} (al cancelar, devuelve lo seguido hasta ese momento).
    """
    import cv2
    _quiet_cv()
    size = work_size(src_w, src_h, width)
    W, H = size
    total = max(abs(s1 - s0), 1e-3)
    cx, cy, bw, bh = box
    rect = (max(0.0, (cx - bw / 2) * W), max(0.0, (cy - bh / 2) * H), max(6.0, bw * W), max(6.0, bh * H))
    tracker = None
    look = None
    samples: list[list[float]] = []
    lost: list[list[float]] = []
    lost_from = lost_last = None
    last_good = (s0, rect)
    stopped = False
    t_end = s0
    n = 0

    def norm(r, conf):
        x, y, w, h = r
        return [round(t, 4), round(min(1.0, max(0.0, (x + w / 2) / W)), 5), round(min(1.0, max(0.0, (y + h / 2) / H)), 5),
                round(w / W, 5), round(h / H, 5), round(float(conf), 3)]

    was_cancelled = False
    try:
        for t, frame in _frames_between(path, s0, s1, size, fps, cancelled):
            check_cancel(cancelled)
            t_end = t
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if tracker is None:
                tracker = _new_tracker()
                tracker.init(frame, tuple(int(round(v)) for v in rect))
                look = _Look(gray, rect)
                samples.append(norm(rect, 1.0))
                continue
            ok, r = tracker.update(frame)
            conf = look.score(gray, r) if ok else 0.0
            if ok and conf >= LOW_CONF:
                if lost_from is not None:
                    lost.append(sorted([lost_from, lost_last]))
                    lost_from = None
                samples.append(norm(r, conf))
                last_good = (t, tuple(float(v) for v in r))
                look.learn(gray, r, conf)
            else:
                gx, gy, gw, gh = last_good[1]
                radius = max(gw, gh) * (1.0 + 2.0 * min(3.0, abs(t - last_good[0])))
                sc, rr = look.search(gray, (gx + gw / 2, gy + gh / 2), radius)
                if sc >= RECOVER_CONF and rr is not None:      # lo encontró otra vez: sigue desde ahí
                    if lost_from is not None:
                        lost.append(sorted([lost_from, lost_last]))
                        lost_from = None
                    tracker = _new_tracker()
                    tracker.init(frame, tuple(int(round(v)) for v in rr))
                    samples.append(norm(rr, sc))
                    last_good = (t, tuple(float(v) for v in rr))
                else:
                    if lost_from is None:
                        lost_from = t
                    lost_last = t
                    if abs(t - lost_from) > MAX_LOST_S:
                        stopped = True
                        break
            n += 1
            if n % 5 == 0:
                report(progress, abs(t - s0) / total,
                       f"🎯 Siguiendo {'hacia atrás' if s1 < s0 else 'hacia delante'}… {abs(t - s0):.1f} de {total:.1f} s")
    except Cancelled:          # (cancelado: se devuelve lo seguido hasta ahí)
        was_cancelled = True
    if lost_from is not None:
        lost.append(sorted([lost_from, lost_last]))
    lost = [[round(a, 4), round(b, 4)] for a, b in lost if b >= a]
    return {"samples": samples, "lost": lost, "end": round(t_end, 4), "stopped": stopped,
            "cancelled": was_cancelled}


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(values) < 3:
        return values
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")[:len(values)]


def follow_keyframes(samples: list[tuple], zoom: float | None = None, fill: float = 0.45,
                     ease_in_from: float | None = None, ease: float = 0.5,
                     every: float = 0.25, fps: float = 15.0) -> list[dict]:
    """
    Convierte el recorrido en fotogramas clave de zoom que siguen al objeto.
    zoom=None: automático (el objeto ocupa ~45 % del alto). ease_in_from: segundo desde el
    que se empieza a acercar suavemente (z=1), para que el zoom no aparezca de golpe.
    """
    if not samples:
        return []
    arr = np.array(samples, dtype=np.float64)
    t, cx, cy, bh = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 4]
    win = max(1, int(fps * 0.6)) | 1  # ~0,6 s, impar
    cx, cy = _smooth(cx, win), _smooth(cy, win)
    if zoom is None:
        # Con el tamaño del recuadro que marcó el usuario (el del seguidor puede ir "creciendo")
        zoom = float(np.clip(fill / max(float(bh[0]), 1e-3), 1.2, 4.0))
    kf = []
    if ease_in_from is not None and t[0] - ease_in_from > 0.05:
        kf.append({"t": round(float(ease_in_from), 3), "z": 1.0, "x": round(float(cx[0]), 4),
                   "y": round(float(cy[0]), 4)})
    step = max(1, int(round(every * fps)))
    idx = list(range(0, len(t), step))
    if idx[-1] != len(t) - 1:
        idx.append(len(t) - 1)
    first_t = float(t[0]) + (ease if kf else 0.0)
    for i in idx:
        ti = float(t[i])
        if kf and ti < first_t and i != idx[-1]:
            continue  # deja tiempo a la entrada suave
        kf.append({"t": round(ti, 3), "z": round(zoom, 4), "x": round(float(cx[i]), 4), "y": round(float(cy[i]), 4),
                   "i": "linear"})
    return transform.simplify(kf, tol=0.004)
