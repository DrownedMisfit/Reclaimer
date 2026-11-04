"""
Módulo de IA: APRENDER TU ESTILO DE MINIATURAS (local y gratis).

Estudia tus miniaturas (las carpetas que elijas) y, aparte, las REFERENCIAS que te gustan, y saca
un «perfil»: cuántas palabras usas, qué tan grande y en qué lado va el texto, su color y si lleva
contorno, si usas mayúsculas, qué tan grande sale la cara, tus colores, brillo y contraste.

Las propuestas usan esos NÚMEROS como punto de partida (nunca copian una miniatura).
Lo que corriges a mano en una propuesta pesa más que el perfil.

  analyze_image(path)                 → rasgos de una miniatura
  build_profile(paths, progress, …)   → perfil {"youtube": {...}, "short": {...}, "n": …}
  to_prefs(profile, refs, fmt)        → preferencias para las propuestas
  describe(profile, fmt)              → resumen en palabras
"""
from __future__ import annotations

import os
import threading
from collections import Counter
from statistics import median

import cv2
import numpy as np

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# Punto de partida cuando todavía no conozco tu estilo. Sale de estudiar (solo mirando, oct-2026) ~55
# miniaturas con más de 100 mil vistas de canales de crítica/análisis de videojuegos en español e inglés
# (descartando las que parecían hechas con IA). Lo común:
#   · 1–4 palabras (casi siempre 2–3), MAYÚSCULAS, letra gruesa y condensada, muy grande.
#   · Blanco como color principal y UNA palabra clave en rojo (a veces amarillo), en el texto o en un recuadro.
#   · Contorno o sombra oscura; fondo oscurecido o desenfocado para que el texto destaque.
#   · Cara o personaje grande, con emoción, a un lado; el texto en el lado contrario; a menudo el logo del juego.
# Tu estilo (tus carpetas), tus referencias y lo que corriges a mano mandan sobre esto.
STUDY_DEFAULTS = {
    "youtube": {"words": 3, "upper": True, "text_color": "#FFFFFF", "outline_share": 0.7, "outline_color": "#000000",
                "accent_share": 0.4, "accent_color": "#E8231A", "text_h": 0.125},
    "short": {"words": 3, "upper": True, "text_color": "#FFFFFF", "outline_share": 0.7, "outline_color": "#000000",
              "accent_share": 0.4, "accent_color": "#E8231A", "text_h": 0.13},
}
MAX_IMAGES = 400
_lock = threading.Lock()
_ocr = None


def _engine():
    global _ocr
    with _lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
        return _ocr


def list_images(folders: list[str], limit: int = MAX_IMAGES) -> list[str]:
    """Imágenes dentro de las carpetas (y subcarpetas), las más recientes primero. Solo lectura."""
    out = []
    for f in folders:
        if os.path.isfile(f) and f.lower().endswith(IMAGE_EXT):
            out.append(f)
            continue
        for root, _dirs, files in os.walk(f):
            out += [os.path.join(root, x) for x in files if x.lower().endswith(IMAGE_EXT)]
    out = list(dict.fromkeys(out))
    out.sort(key=lambda p: -os.path.getmtime(p) if os.path.exists(p) else 0)
    return out[:limit]


def _read(path: str) -> np.ndarray | None:
    # imdecode: funciona con rutas con acentos (cv2.imread no siempre en Windows)
    try:
        data = np.fromfile(path, np.uint8)
    except OSError:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def _hex(bgr) -> str:
    b, g, r = (int(max(0, min(255, v))) for v in bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def _lum(bgr) -> float:
    b, g, r = (float(v) / 255 for v in bgr)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _text_style(img: np.ndarray, box: tuple[int, int, int, int]) -> tuple[str | None, str | None, int]:
    """(color del relleno de las letras, color del contorno o None, nº de palabras) de una línea de texto."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = box
    lh = y1 - y0
    pad = max(3, int(lh * 0.25))                                  # el contorno sobresale del recuadro del OCR
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    roi = img[Y0:Y1, X0:X1]
    if roi.size < 300:
        return None, None, 0
    h, w = roi.shape[:2]
    px = roi.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(1)
    _c, labels, centers = cv2.kmeans(px, 3, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(h, w)
    ring = np.zeros((h, w), bool)
    b = max(1, pad // 2)
    ring[:b, :] = ring[-b:, :] = ring[:, :b] = ring[:, -b:] = True
    inner = np.zeros((h, w), bool)
    inner[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = True
    r = max(2, int(lh * 0.05))
    kernel = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    info = {}
    for k in range(3):
        m = labels == k
        area = (m & inner).sum() / max(1, inner.sum())
        if area < 0.08:
            continue
        rim = cv2.dilate(m.astype(np.uint8), kernel).astype(bool) & ~m
        cnt = Counter(labels[rim].ravel().tolist()) if rim.any() else Counter()
        around, n = cnt.most_common(1)[0] if cnt else (None, 0)
        info[k] = {"border": (m & ring).sum() / max(1, ring.sum()) / area, "ring": (m & ring).mean() / ring.mean(),
                   "around": around, "share": n / max(1, rim.sum())}
    if not info:
        return None, None, 0
    # Las letras son lo que queda RODEADO por otro color (el contorno); si nada lo está, lo que menos toca el borde
    enclosed = [k for k, v in info.items() if v["around"] in info and v["around"] != k and v["share"] > 0.6]
    if enclosed:
        fill = max(enclosed, key=lambda k: info[k]["share"])
        around = info[fill]["around"]
        outline = _hex(centers[around]) if info[around]["ring"] < 0.5 else None   # si rodea todo, es el fondo
    else:
        fill = min(info, key=lambda k: info[k]["border"])
        outline = None
    fm = (labels == fill) & inner
    if outline and abs(_lum(centers[fill]) - _lum(centers[info[fill]["around"]])) < 0.25:
        outline = None          # dos tonos parecidos: no es un contorno
    fill_hex = _hex(np.median(roi[fm], axis=0))
    # Palabras: huecos anchos entre columnas con tinta (el OCR a veces junta las palabras)
    cols = fm[y0 - Y0:y1 - Y0].mean(axis=0) > 0.02
    gaps, run = [], 0
    started = False
    for c in cols:
        if c:
            if started and run:
                gaps.append(run)
            started, run = True, 0
        elif started:
            run += 1
    words = 1 + sum(g > max(0.14 * lh, 2.2 * (median(gaps) if gaps else 0)) for g in gaps) if started else 0
    return fill_hex, outline, words


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.7


def _dist(h1: str, h2: str) -> float:
    a = np.array([int(h1[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    b = np.array([int(h2[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    return float(np.linalg.norm(a - b))


def _title_block(lines: list[dict], W: int) -> list[dict]:
    """Las líneas que forman EL TÍTULO. Se agrupan las líneas pegadas y de tamaño parecido, y gana el grupo
    con más palabras grandes; logos («gRand theft auto», «REMASTERED»), marcas y letreros quedan fuera."""
    if not lines:
        return []
    n = len(lines)
    parent = list(range(n))

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            a, b = lines[i], lines[j]
            hmax = max(a["h"], b["h"])
            if not 0.55 <= a["h"] / b["h"] <= 1.8 or _is_upper(a["text"]) != _is_upper(b["text"]):
                continue
            gap = max(a["box"][1] - b["box"][3], b["box"][1] - a["box"][3])
            dx = abs((a["box"][0] + a["box"][2]) - (b["box"][0] + b["box"][2])) / 2
            if gap < 0.9 * hmax * W and dx < 0.25 * W:
                parent[root(i)] = root(j)
    groups: dict = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(lines[i])

    def score(g):
        words = min(6, sum(l["words"] for l in g))
        up = 1.0 if _is_upper(g[0]["text"]) else 0.6
        return words * max(l["h"] for l in g) ** 0.5 * up
    block = max(groups.values(), key=score)
    block.sort(key=lambda l: l["box"][1])
    return block


def analyze_image(path: str) -> dict | None:
    """Rasgos de UNA miniatura (proporciones 0–1 respecto al lienzo)."""
    img = _read(path)
    if img is None:
        return None
    H, W = img.shape[:2]
    k = 1280 / max(W, H)
    if k < 1:
        img = cv2.resize(img, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA)
        H, W = img.shape[:2]
    f: dict = {"fmt": "youtube" if W >= H else "short", "path": path}

    # Texto (RapidOCR): solo lo que es «título» (se ignoran marcas de agua y letras diminutas)
    res, _ = _engine()(img)
    lines = []
    for quad, txt, score in res or []:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        x0, y0, x1, y1 = int(max(0, min(xs))), int(max(0, min(ys))), int(min(W, max(xs))), int(min(H, max(ys)))
        if float(score) < 0.6 or len(txt.strip()) < 2 or (y1 - y0) < W * 0.025:
            continue
        line = {"text": txt.strip(), "box": (x0, y0, x1, y1), "h": (y1 - y0) / W}
        line["fill"], line["outline"], gw = _text_style(img, line["box"])
        line["words"] = max(len(line["text"].split()), gw)
        lines.append(line)
    block = _title_block(lines, W)
    f["words"] = sum(l["words"] for l in block)
    f["lines"] = len(block)
    f["extra_text"] = len(lines) - len(block)                     # logos, marcas, letreros aparte
    if block:
        big = max(block, key=lambda l: l["h"])
        x0 = min(l["box"][0] for l in block)
        y0 = min(l["box"][1] for l in block)
        x1 = max(l["box"][2] for l in block)
        y1 = max(l["box"][3] for l in block)
        f["text_h"] = round(big["h"], 4)                          # alto de la línea más grande / ancho
        f["text_x"] = round((x0 + x1) / 2 / W, 3)
        f["text_y"] = round((y0 + y1) / 2 / H, 3)
        f["text_area"] = round((x1 - x0) * (y1 - y0) / (W * H), 3)
        f["upper"] = all(_is_upper(l["text"]) for l in block)
        # Color principal (el de más palabras) y, si una línea va en otro color, el ACENTO (p. ej. la palabra en rojo)
        main = max(block, key=lambda l: (l["words"], l["h"]))
        f["text_color"], f["outline"] = main["fill"], main["outline"] or big["outline"]
        f["accent"] = next((l["fill"] for l in block if l["fill"] and main["fill"]
                            and _dist(l["fill"], main["fill"]) > 110), None)
        f["fills"] = [(l["fill"], l["words"]) for l in block if l["fill"]]

    # Caras
    from .tracking import detect_faces
    faces = [b for b in detect_faces(img) if b[4] > 0.7]
    f["faces"] = len(faces)
    if faces:
        fb = faces[0]
        f["face_h"] = round(fb[3], 3)                             # alto de la cara / alto del lienzo
        f["face_x"] = round(fb[0] + fb[2] / 2, 3)

    # Color, brillo y contraste
    small = cv2.resize(img, (96, int(96 * H / W) or 1), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    f["saturation"] = round(float(hsv[..., 1].mean()) / 255, 3)
    f["brightness"] = round(float(lab[..., 0].mean()) / 255, 3)
    f["contrast"] = round(float(lab[..., 0].std()) / 255, 3)
    px = small.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _c, labels, centers = cv2.kmeans(px, 5, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    cnt = np.bincount(labels.ravel(), minlength=5) / len(labels)
    f["palette"] = [(_hex(centers[i]), round(float(cnt[i]), 3)) for i in np.argsort(-cnt)]
    return f


# ------------------------------------------------------------------- perfil
def _mode(values, min_share=0.0):
    values = [v for v in values if v is not None]
    if not values:
        return None, 0.0
    v, n = Counter(values).most_common(1)[0]
    share = n / len(values)
    return (v, share) if share >= min_share else (None, share)


def _close_color(hexes: list[str], min_share: float = 0.35) -> str | None:
    """El color de texto que más se repite (agrupando tonos parecidos)."""
    cols = [h for h in hexes if h]
    if not cols:
        return None
    rgb = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in cols], np.float32)
    q = (rgb // 48).astype(int)
    key, n = Counter(map(tuple, q)).most_common(1)[0]
    if n / len(cols) < min_share:
        return None
    sel = rgb[(q == np.array(key)).all(axis=1)].mean(axis=0)
    return "#%02X%02X%02X" % tuple(int(v) for v in sel)


def _summarize(feats: list[dict]) -> dict:
    if not feats:
        return {}
    with_text = [f for f in feats if f.get("words")]
    p: dict = {"n": len(feats), "with_text": round(len(with_text) / len(feats), 2)}
    if with_text:
        p["words"] = median(f["words"] for f in with_text)
        p["text_h"] = round(median(f["text_h"] for f in with_text), 4)
        p["text_y"] = round(median(f["text_y"] for f in with_text), 3)
        sides = ["left" if f["text_x"] < 0.42 else "right" if f["text_x"] > 0.58 else "center" for f in with_text]
        p["text_side"], p["text_side_share"] = _mode(sides)
        p["upper"] = sum(bool(f.get("upper")) for f in with_text) / len(with_text) > 0.6
        # Color del texto y de la palabra clave: votación entre TODAS (una miniatura mal leída no cambia nada)
        votes = [c for f in with_text for c, w in f.get("fills", []) for _ in range(max(1, w))]
        p["text_color"] = _close_color(votes, 0.25) or _close_color([f.get("text_color") for f in with_text])
        outl = [f.get("outline") for f in with_text]
        p["outline_share"] = round(sum(o is not None for o in outl) / len(outl), 2)
        p["outline_color"] = _close_color([o for o in outl if o])
        acc = []
        for f in with_text:
            if p["text_color"]:
                other = [c for c, _w in f.get("fills", []) if _dist(c, p["text_color"]) > 110]
                if other and len(other) < len(f.get("fills", [])):     # su texto mezcla el color principal y otro
                    acc.append(other[0])
        p["accent_share"] = round(len(acc) / len(with_text), 2)
        p["accent_color"] = _close_color(acc, 0.25)
    faced = [f for f in feats if f.get("faces")]
    p["face_share"] = round(len(faced) / len(feats), 2)
    if faced:
        p["face_h"] = round(median(f["face_h"] for f in faced), 3)
        fs = ["left" if f["face_x"] < 0.42 else "right" if f["face_x"] > 0.58 else "center" for f in faced]
        p["face_side"], _ = _mode(fs)
    for key in ("saturation", "brightness", "contrast"):
        p[key] = round(median(f[key] for f in feats), 3)
    # Colores de la casa: los de todas las paletas, reagrupados
    cols = [(h, w) for f in feats for h, w in f.get("palette", [])]
    if cols:
        rgb = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h, _ in cols], np.float32)
        wts = np.array([w for _, w in cols], np.float32)
        q = (rgb // 40).astype(int)
        acc: dict = {}
        for c, w, key in zip(rgb, wts, map(tuple, q)):
            s = acc.setdefault(key, [np.zeros(3), 0.0])
            s[0] += c * w
            s[1] += w
        top = sorted(acc.values(), key=lambda s: -s[1])[:5]
        p["palette"] = ["#%02X%02X%02X" % tuple(int(v) for v in s[0] / s[1]) for s in top]
    return p


def build_profile(paths: list[str], progress=None, cancelled=None) -> dict:
    """Analiza las imágenes y devuelve el perfil por formato (YouTube / Shorts)."""
    feats = []
    for i, p in enumerate(paths):
        if cancelled and cancelled():
            break
        if progress:
            progress(i / max(1, len(paths)), f"Estudiando {i + 1} de {len(paths)}: {os.path.basename(p)}")
        try:
            f = analyze_image(p)
        except Exception:
            f = None
        if f:
            feats.append(f)
    out = {"n": len(feats)}
    for fmt in ("youtube", "short"):
        s = _summarize([f for f in feats if f["fmt"] == fmt])
        if s:
            out[fmt] = s
    return out


def _pick(profile: dict | None, fmt: str) -> dict:
    """El perfil del formato; si no hay de ese formato, el del otro (solo para rasgos que no dependen del tamaño)."""
    if not profile:
        return {}
    if profile.get(fmt):
        return profile[fmt]
    other = profile.get("short" if fmt == "youtube" else "youtube") or {}
    return {k: other[k] for k in ("words", "upper", "text_color", "outline_share", "outline_color", "palette",
                                  "accent_share", "accent_color",
                                  "saturation", "contrast") if k in other}


def to_prefs(own: dict | None, refs: dict | None, fmt: str, doc_w: int, defaults: bool = False) -> dict:
    """Preferencias de partida para las propuestas: tu estilo primero; las referencias rellenan lo que falte;
    con defaults=True, lo que siga faltando sale del estudio de miniaturas de YouTube (STUDY_DEFAULTS)."""
    a, b = _pick(own, fmt), _pick(refs, fmt)
    c = STUDY_DEFAULTS.get(fmt, {}) if defaults else {}

    def get(key):
        for src in (a, b, c):
            if src.get(key) is not None:
                return src[key]
        return None
    p: dict = {}
    th = get("text_h")
    if th:   # la fuente del título (130 px) ocupa ~130/ancho del lienzo
        p["size_k"] = round(min(1.8, max(0.6, th / (130 / doc_w))), 3)
    side = get("text_side")
    if side in ("left", "right"):
        p["text_side"] = side
    col = get("text_color")
    if col:
        p["color"] = col
    share = get("outline_share")
    if share is not None:
        p["outline"] = share >= 0.4
        if get("outline_color"):
            p["outline_color"] = get("outline_color")
    if (get("accent_share") or 0) >= 0.3 and get("accent_color"):
        p["accent"] = get("accent_color")       # la palabra clave en otro color
    if get("upper") is not None:
        p["uppercase"] = bool(get("upper"))
    if get("words"):
        p["max_words"] = int(max(1, min(6, round(get("words") + 0.5))))
    if get("face_h"):
        p["face_h"] = get("face_h")
    return p


def describe(profile: dict | None, fmt: str) -> str:
    p = (profile or {}).get(fmt)
    if not p:
        return ""
    side = {"left": "a la izquierda", "right": "a la derecha", "center": "al centro"}
    parts = [f"{p['n']} miniaturas"]
    if p.get("words"):
        parts.append(f"sueles usar ~{p['words']:g} palabras {side.get(p.get('text_side'), '')}".rstrip())
        parts.append("en MAYÚSCULAS" if p.get("upper") else "en minúsculas/mixto")
        if p.get("text_color"):
            parts.append(f"letras {p['text_color']}" + (" con contorno" if p.get("outline_share", 0) >= 0.4 else
                                                           " sin contorno"))
        if p.get("accent_share", 0) >= 0.3 and p.get("accent_color"):
            parts.append(f"palabra clave en {p['accent_color']} ({p['accent_share']:.0%})")
    else:
        parts.append("casi sin texto")
    if p.get("face_share", 0) >= 0.3:
        parts.append(f"cara en el {p['face_share']:.0%} (alto ~{p.get('face_h', 0):.0%} del lienzo)")
    else:
        parts.append("pocas caras")
    parts.append(f"saturación {p['saturation']:.0%}, contraste {p['contrast']:.0%}")
    return " · ".join(parts)
