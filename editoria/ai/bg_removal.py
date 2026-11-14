"""
Módulo de IA: QUITAR EL FONDO (recortar al sujeto) — local y gratis.

Usa el modelo IS-Net «general use» (el de la herramienta libre rembg; licencia Apache-2.0).
Devuelve una MÁSCARA en grises del tamaño de la imagen (blanco = se ve, negro = transparente),
que luego se puede retocar a mano con el pincel (borrar / recuperar).

  remove(path)              → automático: el sujeto principal
  remove(path, box=(…))     → semiautomático: lo que hay dentro del recuadro que marcaste
"""
from __future__ import annotations

import os
import threading
import uuid

import cv2
import numpy as np

from ..core.paths import cache_dir
from .transcription import models_dir

SIZE = 1024
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
_lock = threading.Lock()
_session = None


def model_path() -> str:
    return str(models_dir() / "recorte" / "isnet-general-use.onnx")


def is_available() -> bool:
    return os.path.exists(model_path())


def download(progress=None) -> str:
    """Descarga el modelo (~180 MB) la primera vez."""
    import urllib.request
    out = model_path()
    if os.path.exists(out):
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if progress:
        progress(0.0, "Descargando el modelo para quitar fondos (~180 MB, solo la primera vez)…")
    tmp = out + ".part"
    urllib.request.urlretrieve(MODEL_URL, tmp)
    os.replace(tmp, out)
    return out


def _sess():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            _session = ort.InferenceSession(download(), providers=["CPUExecutionProvider"])
        return _session


def _predict(rgb: np.ndarray) -> np.ndarray:
    """Máscara 0–1 del sujeto para una imagen RGB uint8 (del mismo tamaño)."""
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    x = (x - 0.5) / 1.0
    x = x.transpose(2, 0, 1)[None]
    s = _sess()
    out = s.run(None, {s.get_inputs()[0].name: x})[0][0, 0]
    out = (out - out.min()) / max(1e-6, out.max() - out.min())
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)


def remove(path: str, box: tuple[float, float, float, float] | None = None, margin: float = 0.06) -> str:
    """Crea la máscara del sujeto y devuelve su ruta (PNG en grises, mismo tamaño que la imagen).
    box = (x0, y0, x1, y1) en 0–1: solo se busca el sujeto dentro de ese recuadro."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("No se pudo leer la imagen.")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.float32)
    if box:
        x0, y0, x1, y1 = box
        mx, my = (x1 - x0) * margin, (y1 - y0) * margin
        a = int(max(0, (x0 - mx) * w)), int(max(0, (y0 - my) * h))
        b = int(min(w, (x1 + mx) * w)), int(min(h, (y1 + my) * h))
        if b[0] - a[0] < 8 or b[1] - a[1] < 8:
            raise RuntimeError("El recuadro es demasiado pequeño.")
        mask[a[1]:b[1], a[0]:b[0]] = _predict(rgb[a[1]:b[1], a[0]:b[0]])
        # Fuera del recuadro marcado no hay nada
        inner = np.zeros_like(mask)
        inner[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 1
        inner = cv2.GaussianBlur(inner, (0, 0), max(2, int(min(w, h) * 0.01)))
        mask *= np.clip(inner * 1.5, 0, 1)
    else:
        mask = _predict(rgb)
    # Bordes limpios: quitar «neblina» suave y conservar el detalle (pelo, bordes)
    mask = np.clip((mask - 0.08) / 0.84, 0, 1)
    out = os.path.join(str(cache_dir("recortes")), f"mask_{uuid.uuid4().hex[:12]}.png")
    cv2.imwrite(out, (mask * 255).astype(np.uint8))
    return out


def _leer(path: str, flags: int):
    """cv2.imread, pero también con tildes en la ruta."""
    try:
        return cv2.imdecode(np.fromfile(path, np.uint8), flags)
    except (OSError, ValueError, cv2.error):
        return None


def _solo_sujeto(image_path: str, m: np.ndarray, brush: np.ndarray, r: int) -> np.ndarray | None:
    """🖌 Recuperar «solo el sujeto»: de lo pintado se queda con lo que se parece a lo que ya se ve (el personaje) y no a
    lo borrado de alrededor (el fondo), siguiendo los bordes de la imagen (GrabCut). None = no se puede decidir (entonces
    se recupera todo lo pintado, tal cual)."""
    cand = (brush > 0) & (m < 128)
    if int(cand.sum()) < 30:
        return None
    ys, xs = np.nonzero(brush)
    H, W = m.shape[:2]
    margen = max(2 * r, 40)
    x0, x1 = max(0, int(xs.min()) - margen), min(W, int(xs.max()) + margen + 1)
    y0, y1 = max(0, int(ys.min()) - margen), min(H, int(ys.max()) + margen + 1)
    img = _leer(image_path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    if img.shape[:2] != (H, W):
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    def etiquetas(m_p: np.ndarray, b_p: np.ndarray, escala: float) -> np.ndarray:
        lab = np.full(m_p.shape, cv2.GC_BGD, np.uint8)           # lo borrado lejos del pincel: fondo
        lado = max(3, int(0.6 * r * escala) * 2 + 1)
        cerca = cv2.dilate((b_p > 127).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado)))
        lab[cerca > 0] = cv2.GC_PR_BGD                           # junto al pincel: a saber
        lab[b_p > 127] = cv2.GC_PR_FGD                           # lo pintado: probablemente sujeto
        lab[m_p >= 128] = cv2.GC_FGD                             # lo que ya se ve: el sujeto, seguro
        return lab

    # 1) qué colores son del sujeto y cuáles del fondo: con TODA la imagen (lo que se ve puede quedar lejos del trazo)
    f0 = min(1.0, 480.0 / max(W, H))
    tam0 = (max(8, int(W * f0)), max(8, int(H * f0)))
    lab0 = etiquetas(cv2.resize(m, tam0, interpolation=cv2.INTER_AREA), cv2.resize(brush, tam0, interpolation=cv2.INTER_AREA), f0)
    if int((lab0 == cv2.GC_FGD).sum()) < 30:
        return None
    img0 = cv2.resize(img, tam0, interpolation=cv2.INTER_AREA)
    # lo borrado que tiene los colores del sujeto (otro trozo del personaje que se borró) no enseña cómo es el fondo
    bins = (img0 // 16).astype(np.int32)
    idx = bins[..., 0] * 256 + bins[..., 1] * 16 + bins[..., 2]
    cuenta = np.bincount(idx[lab0 == cv2.GC_FGD].ravel(), minlength=4096)
    del_sujeto = cuenta[idx] >= max(2.0, 0.002 * float(cuenta.sum()))
    lab0[(lab0 == cv2.GC_BGD) & del_sujeto] = cv2.GC_PR_FGD
    if int((lab0 == cv2.GC_BGD).sum()) < 30:
        return None                                              # (todo se parece: no hay forma de distinguir)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(img0, lab0, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    # 2) el borde exacto: solo la zona del trazo, con más detalle y esos mismos colores
    f = min(1.0, 900.0 / max(x1 - x0, y1 - y0))
    tam = (max(8, int((x1 - x0) * f)), max(8, int((y1 - y0) * f)))
    small = cv2.resize(img[y0:y1, x0:x1], tam, interpolation=cv2.INTER_AREA)
    m_s = cv2.resize(m[y0:y1, x0:x1], tam, interpolation=cv2.INTER_AREA)
    b_s = cv2.resize(brush[y0:y1, x0:x1], tam, interpolation=cv2.INTER_AREA)
    labels = etiquetas(m_s, b_s, f)
    try:
        cv2.grabCut(small, labels, None, bgd, fgd, 2, getattr(cv2, "GC_EVAL_FREEZE_MODEL", cv2.GC_EVAL))
    except cv2.error:
        return None
    keep = ((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)).astype(np.uint8)
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    keep[b_s <= 127] = 0
    # nada de islas sueltas: lo que no toca lo que ya se ve solo se queda si es un trozo grande
    n, comp, stats, _c = cv2.connectedComponentsWithStats(((keep > 0) | (m_s >= 128)).astype(np.uint8), connectivity=8)
    total = int(keep.sum())
    tocan = set(np.unique(comp[m_s >= 128]).tolist())
    for i in range(1, n):
        if i not in tocan and stats[i, cv2.CC_STAT_AREA] < 0.15 * max(1, total):
            keep[comp == i] = 0
    # nada de agujeros: lo rechazado solo es fondo de verdad si sigue, sin cortes, por lo borrado que no pintaste; si queda
    # rodeado de lo recuperado es otra parte del sujeto (p. ej. una armadura de un color que aún no se veía)
    rechazado = ((b_s > 127) & (keep == 0) & (m_s < 128)).astype(np.uint8)
    fuera = ((b_s <= 127) & (m_s < 128)).astype(np.uint8)
    if rechazado.any():
        lado = max(3, int(0.3 * r * f) | 1)
        nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado))
        abierto = cv2.morphologyEx(rechazado, cv2.MORPH_OPEN, nucleo)       # (un paso estrecho no lo conecta con el fondo)
        n, comp = cv2.connectedComponents(((abierto > 0) | (fuera > 0)).astype(np.uint8), connectivity=8)
        conectan = np.unique(comp[fuera > 0]) if fuera.any() else np.array([], np.int32)
        fondo = np.isin(comp, conectan[conectan > 0]) & (abierto > 0)
        fondo = cv2.dilate(fondo.astype(np.uint8), nucleo).astype(bool) & (rechazado > 0)
        keep[(rechazado > 0) & ~fondo] = 1
    cand_s = (b_s > 127) & (m_s < 128)
    if int((keep.astype(bool) & cand_s).sum()) < 0.08 * max(1, int(cand_s.sum())):
        return None
    grande = cv2.resize(keep * 255, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    grande = cv2.GaussianBlur(grande, (0, 0), max(0.6, 0.5 / f))
    out = np.zeros_like(brush)
    out[y0:y1, x0:x1] = cv2.min(grande, brush[y0:y1, x0:x1])
    return out


def _suavizar(brush: np.ndarray, r: int, hard: float) -> np.ndarray:
    """Pincel blando: el borde se difumina (dureza 1 = borde nítido; 0 = muy suave). Solo en la zona del trazo."""
    if hard >= 0.999:
        return brush
    sigma = max(0.8, (1.0 - hard) * r * 0.5)
    ys, xs = np.nonzero(brush)
    if not len(xs):
        return brush
    m = int(3 * sigma) + 2
    h, w = brush.shape
    x0, y0, x1, y1 = max(0, xs.min() - m), max(0, ys.min() - m), min(w, xs.max() + m + 1), min(h, ys.max() + m + 1)
    out = brush.copy()
    roi = brush[y0:y1, x0:x1].astype(np.float32)
    if sigma > 8:                                   # (con mucho difuminado, en pequeño: igual de suave y mucho más rápido)
        f = sigma / 8.0
        small = cv2.resize(roi, (max(1, int(roi.shape[1] / f)), max(1, int(roi.shape[0] / f))), interpolation=cv2.INTER_AREA)
        roi = cv2.resize(cv2.GaussianBlur(small, (0, 0), 8.0), (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        roi = cv2.GaussianBlur(roi, (0, 0), sigma)
    out[y0:y1, x0:x1] = np.clip(roi, 0, 255).astype(np.uint8)
    return out


def paint(mask_path: str | None, image_path: str, strokes: list[tuple[float, float]], radius: float,
          restore: bool, size: tuple[int, int] | None = None, smart: bool = False, hard: float = 1.0,
          alpha: float = 1.0) -> str:
    """Pincel: borra (o recupera) a lo largo de los puntos (píxeles de la imagen original).
    smart (al recuperar): solo lo pintado que sea sujeto. hard: dureza del borde (1 = nítido); alpha: opacidad del trazo
    (0,5 = borra o recupera la mitad; como en Photoshop, pasar dos veces por el mismo sitio en un trazo no suma).
    Devuelve una máscara NUEVA (así deshacer funciona)."""
    m = _leer(mask_path, cv2.IMREAD_GRAYSCALE) if mask_path and os.path.exists(mask_path) else None
    if m is None:
        img = _leer(image_path, cv2.IMREAD_COLOR)
        h, w = img.shape[:2] if img is not None else (size[1], size[0])
        m = np.full((h, w), 255, np.uint8)
    r = max(1, int(radius))
    pts = [(int(x), int(y)) for x, y in strokes]
    brush = np.zeros_like(m)
    for i, p in enumerate(pts):
        cv2.circle(brush, p, r, 255, -1, lineType=cv2.LINE_AA)
        if i:
            cv2.line(brush, pts[i - 1], p, 255, 2 * r, lineType=cv2.LINE_AA)
    if restore and smart:
        fino = _solo_sujeto(image_path, m, brush, r)
        if fino is not None:
            brush = fino
    hard, alpha = max(0.0, min(1.0, float(hard))), max(0.0, min(1.0, float(alpha)))
    if hard >= 0.999 and alpha >= 0.999:
        m = cv2.max(m, brush) if restore else cv2.min(m, cv2.bitwise_not(brush))
    else:
        b = _suavizar(brush, r, hard).astype(np.float32) * (alpha / 255.0)
        mf = m.astype(np.float32)
        mf = mf + (255.0 - mf) * b if restore else mf * (1.0 - b)
        m = np.clip(mf + 0.5, 0, 255).astype(np.uint8)
    out = os.path.join(str(cache_dir("recortes")), f"mask_{uuid.uuid4().hex[:12]}.png")
    cv2.imwrite(out, m, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    return out


def subject_box(mask_path: str) -> tuple[float, float, float, float] | None:
    """Caja (0–1) de lo que quedó visible: para reencuadrar al sujeto recortado."""
    m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if m is None:
        return None
    ys, xs = np.nonzero(m > 128)
    if not len(xs):
        return None
    h, w = m.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h
