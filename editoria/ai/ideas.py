"""
✨ Ideas para lo que seleccionas en la línea de tiempo: cómo meter una imagen o un video encima (entrada,
sombra, contorno, dónde ponerlo). Reglas sencillas y rápidas, sin modelos pesados.

  ideas_for(project, clip_ids) → [{"label", "tip", "changes": {clip_id: {"layout", "fx"}}}]
  is_text_image(path) → ¿es una imagen de puro texto? (captura, tuit, noticia)
"""
from __future__ import annotations

import numpy as np

from ..core.model import KIND_IMAGE, KIND_VIDEO

DECOR_KEYS = ("enter", "shadow", "outline")
_text_cache: dict[str, bool] = {}


def is_text_image(path: str) -> bool:
    """Captura con texto: fondo liso que ocupa casi toda la imagen, muchos trazos pequeños y poco color."""
    if path in _text_cache:
        return _text_cache[path]
    res = False
    try:
        import cv2
        data = np.fromfile(path, np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if len(data) else None
        if img is not None:
            h, w = img.shape[:2]
            k = 480 / max(h, w)
            img = cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))))
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            border = np.concatenate([gray[:4].ravel(), gray[-4:].ravel(), gray[:, :4].ravel(), gray[:, -4:].ravel()])
            bgv = float(np.median(border))
            bg_frac = float((np.abs(gray.astype(int) - bgv) < 18).mean())
            sat = float(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255)
            bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 12)
            n, _lab, stats, _c = cv2.connectedComponentsWithStats(bw, connectivity=8)
            small = int(((stats[1:, cv2.CC_STAT_HEIGHT] < gray.shape[0] * 0.08) &
                         (stats[1:, cv2.CC_STAT_AREA] > 4)).sum()) if n > 1 else 0
            res = bg_frac > 0.5 and small > 40 and sat < 0.35
    except Exception:  # noqa: BLE001 - una idea nunca debe romper nada
        res = False
    _text_cache[path] = res
    return res


def _boxes(vertical: bool) -> dict[str, dict]:
    if vertical:
        return {"center": {"x": 0.06, "y": 0.28, "w": 0.88, "h": 0.44, "fit": "contain", "bg": "none"},
                "card": {"x": 0.05, "y": 0.25, "w": 0.90, "h": 0.50, "fit": "contain", "bg": "none"},
                "corner": {"x": 0.52, "y": 0.10, "w": 0.42, "h": 0.24, "fit": "contain", "bg": "none"}}
    return {"center": {"x": 0.15, "y": 0.12, "w": 0.70, "h": 0.76, "fit": "contain", "bg": "none"},
            "card": {"x": 0.12, "y": 0.10, "w": 0.76, "h": 0.80, "fit": "contain", "bg": "none"},
            "corner": {"x": 0.60, "y": 0.06, "w": 0.36, "h": 0.36, "fit": "contain", "bg": "none"}}


def _fx(c, **decor) -> dict:
    fx = {k: v for k, v in (c.fx or {}).items() if k not in DECOR_KEYS}
    fx.update({k: v for k, v in decor.items() if v is not None})
    return fx


def _over(c, box: dict) -> dict:
    """Si el clip ocupa toda la pantalla, se pone en la caja propuesta; si ya está encima, se queda donde está."""
    lay = c.layout
    full = lay is None or (lay.get("w", 1) >= 0.999 and lay.get("h", 1) >= 0.999)
    return dict(box) if full else dict(lay, bg="none")


def ideas_for(p, clip_ids) -> list[dict]:
    clips = [p.clips[i] for i in clip_ids if i in p.clips and p.clips[i].text is None]
    clips = [c for c in clips if p.media_of(c) is not None and p.media_of(c).kind in (KIND_IMAGE, KIND_VIDEO)]
    if not clips:
        return []
    vertical = p.height > p.width
    B = _boxes(vertical)
    SH = {"opacity": 0.6}
    OL = {"color": "#FFFFFF"}
    out: list[dict] = []

    def idea(label, tip, fn):
        out.append({"label": label, "tip": tip, "changes": {c.id: fn(i, c) for i, c in enumerate(clips)}})

    one = clips[0]
    m = p.media_of(one)
    if len(clips) == 1 and m.kind == KIND_IMAGE and is_text_image(m.path):
        idea("📰 Tarjeta de texto: centrada, entra desde abajo, con contorno y sombra",
             "Parece una captura con texto (tuit, noticia…): se pone como tarjeta encima del video.",
             lambda i, c: {"layout": _over(c, B["card"]), "fx": _fx(c, enter={"from": "bottom", "dur": 0.45},
                                                                    shadow=SH, outline=OL)})
    if len(clips) == 1 and m.kind == KIND_IMAGE:
        idea("🖼 Encima y centrada · entra desde la derecha · con sombra", "",
             lambda i, c: {"layout": _over(c, B["center"]), "fx": _fx(c, enter={"from": "right", "dur": 0.45},
                                                                      shadow=SH)})
        idea("⬆ Entra desde abajo · contorno blanco y sombra", "",
             lambda i, c: {"layout": _over(c, B["center"]), "fx": _fx(c, enter={"from": "bottom", "dur": 0.45},
                                                                      shadow=SH, outline=OL)})
        idea("↘ En una esquina · entra desde la derecha · con sombra", "",
             lambda i, c: {"layout": dict(B["corner"]), "fx": _fx(c, enter={"from": "right", "dur": 0.4},
                                                                 shadow=SH)})
        idea("✨ Aparece suave · con sombra", "",
             lambda i, c: {"layout": _over(c, B["center"]), "fx": _fx(c, enter={"from": "fade", "dur": 0.5},
                                                                      shadow=SH)})
    if len(clips) == 1 and m.kind == KIND_VIDEO:
        idea("▶ Recuadro en una esquina · entra desde la derecha · con sombra",
             "Como imagen en imagen, encima de lo que haya debajo.",
             lambda i, c: {"layout": dict(B["corner"]), "fx": _fx(c, enter={"from": "right", "dur": 0.4},
                                                                 shadow=SH)})
        idea("▶ Recuadro centrado · aparece suave · contorno y sombra", "",
             lambda i, c: {"layout": dict(B["center"]), "fx": _fx(c, enter={"from": "fade", "dur": 0.5},
                                                                  shadow=SH, outline=OL)})
    if len(clips) > 1:
        sides = ("right", "left", "bottom", "top")
        idea(f"🎞 Escalonar las {len(clips)}: cada una entra por un lado distinto · con sombra",
             "Derecha, izquierda, abajo, arriba… (en el orden de la línea de tiempo).",
             lambda i, c: {"layout": _over(c, B["center"]), "fx": _fx(c, enter={"from": sides[i % 4], "dur": 0.45},
                                                                      shadow=SH)})
        idea(f"⬆ Todas entran desde abajo · contorno y sombra", "",
             lambda i, c: {"layout": _over(c, B["center"]), "fx": _fx(c, enter={"from": "bottom", "dur": 0.45},
                                                                      shadow=SH, outline=OL)})
    if any(any(k in (c.fx or {}) for k in DECOR_KEYS) for c in clips):
        idea("✕ Quitar la entrada, la sombra y el contorno", "",
             lambda i, c: {"fx": _fx(c) or None})
    if any(c.layout for c in clips):
        idea("🖥 Pantalla completa (sin detalles)", "",
             lambda i, c: {"layout": None, "fx": _fx(c) or None})
    return out
