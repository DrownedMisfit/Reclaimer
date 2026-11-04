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
from .base import CancelFn, ProgressFn, check_cancel, report

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
