"""
🎬 Ajustes de imagen de un personaje (capa) de Escenas: quitar el fondo, redondear las esquinas y el borde.

Se «hornean» en un PNG nuevo a partir de la imagen ORIGINAL (actor["base_media"]): así el visor de Escenas, el visor del
editor y la exportación enseñan exactamente lo mismo sin tocar el motor. La sombra no se hornea: va como fx["shadow"]
del clip (core/decor.py, igual en el visor y al exportar) y sigue la forma de la imagen (también la recortada).

  actor["ajustes"] = {"sin_fondo": ruta de la máscara (gris) o "", "redondeo": 0–0.5 (del lado corto),
                      "borde": 0–0.08 (del lado corto), "borde_color": "#RRGGBB", "sombra": 0–1 (opacidad)}

  hornear(ruta_base, ajustes) -> ruta del PNG (en caché; la misma entrada da el mismo archivo) o ruta_base si no hay
  nada que hornear. sombra_fx(ajustes) -> el fx["shadow"] o None.
"""
from __future__ import annotations

import hashlib
import json
import os

NEUTROS = {"sin_fondo": "", "redondeo": 0.0, "borde": 0.0, "borde_color": "#FFFFFF", "sombra": 0.0}
RAPIDOS = {
    "borde": (("Sin borde", 0.0), ("Fino", 0.012), ("Grueso", 0.03)),
    "sombra": (("Sin sombra", 0.0), ("Suave", 0.45), ("Fuerte", 0.8)),
    "redondeo": (("Rectas", 0.0), ("Suaves", 0.06), ("Muy redondas", 0.18), ("Círculo", 0.5)),
}


def de(actor: dict) -> dict:
    """Los ajustes del personaje con sus valores por defecto."""
    return dict(NEUTROS, **(actor.get("ajustes") or {}))


def hay_horneado(aj: dict) -> bool:
    return bool(aj.get("sin_fondo")) or float(aj.get("redondeo", 0) or 0) > 1e-4 or \
        float(aj.get("borde", 0) or 0) > 1e-4


def sombra_fx(aj: dict) -> dict | None:
    s = float(aj.get("sombra", 0) or 0)
    if s <= 1e-3:
        return None
    return {"opacity": round(min(1.0, s), 3), "blur": 0.02, "dx": 0.008, "dy": 0.012}


def _carpeta() -> str:
    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "escenas_ajustes")
    os.makedirs(d, exist_ok=True)
    return d


LADO_MAX = 2048        # (se hornea a este tamaño como mucho: una capa nunca necesita más y así no se congela nada)


def clave(aj: dict) -> str:
    """Lo que decide el horneado (para saber si el PNG de una capa está al día)."""
    return json.dumps({k: aj.get(k) for k in ("sin_fondo", "redondeo", "borde", "borde_color")}, sort_keys=True)


def _leer(ruta: str, flags):
    import cv2
    import numpy as np
    try:
        return cv2.imdecode(np.fromfile(ruta, np.uint8), flags)
    except (OSError, ValueError, cv2.error):
        return None


def hornear(ruta_base: str, aj: dict) -> str:
    """El PNG con el fondo quitado (máscara), las esquinas redondeadas y el borde (por fuera de la forma, también si
    está recortada). Lo que no hace falta, no se hornea (devuelve ruta_base). Rápido: como mucho LADO_MAX px y el
    borde con distance transform (no depende de su grosor). Se escribe de una vez (nada a medias en la carpeta)."""
    if not hay_horneado(aj):
        return ruta_base
    import cv2
    import numpy as np
    k = json.dumps({"r": os.path.abspath(ruta_base), "m": os.path.getmtime(ruta_base) if os.path.isfile(ruta_base)
                    else 0, "a": clave(aj), "l": LADO_MAX}, sort_keys=True)
    destino = os.path.join(_carpeta(), hashlib.sha1(k.encode("utf-8")).hexdigest()[:20] + ".png")
    if os.path.isfile(destino):
        return destino
    im = _leer(ruta_base, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise RuntimeError("No se pudo leer la imagen.")
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    h, w = im.shape[:2]
    if max(h, w) > LADO_MAX:
        f = LADO_MAX / float(max(h, w))
        im = cv2.resize(im, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)
        h, w = im.shape[:2]
    alfa = im[:, :, 3].astype(np.float32) / 255.0
    masc = aj.get("sin_fondo") or ""
    if masc and os.path.isfile(masc):                   # ✂ quitar el fondo: la máscara (blanco = se ve)
        m = _leer(masc, cv2.IMREAD_GRAYSCALE)
        if m is not None:
            alfa *= cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    red = float(aj.get("redondeo", 0) or 0)
    if red > 1e-4:                                      # ◜ esquinas redondeadas (0,5 = círculo / óvalo)
        r = int(round(min(h, w) * min(0.5, red)))
        forma = np.zeros((h, w), np.uint8)
        cv2.rectangle(forma, (r, 0), (w - 1 - r, h - 1), 255, -1)
        cv2.rectangle(forma, (0, r), (w - 1, h - 1 - r), 255, -1)
        for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
            cv2.circle(forma, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
        alfa *= forma.astype(np.float32) / 255.0
    im[:, :, 3] = np.clip(alfa * 255.0, 0, 255).astype(np.uint8)
    bor = float(aj.get("borde", 0) or 0)
    if bor > 1e-4:                                      # ▢ borde por fuera de la forma (distancia a lo que se ve)
        g = max(1, int(round(min(h, w) * bor)))
        lienzo = np.zeros((h + 2 * g, w + 2 * g, 4), np.uint8)
        lienzo[g:g + h, g:g + w] = im
        fuera = (lienzo[:, :, 3] < 128).astype(np.uint8)
        dist = cv2.distanceTransform(fuera, cv2.DIST_L2, 5)
        a_borde = np.clip(g + 1.0 - dist, 0.0, 1.0)
        col = str(aj.get("borde_color") or "#FFFFFF").lstrip("#")
        try:
            rgb = tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            rgb = (255, 255, 255)
        a_img = lienzo[:, :, 3].astype(np.float32) / 255.0
        salida = np.zeros_like(lienzo)
        for c, v in enumerate((rgb[2], rgb[1], rgb[0])):   # (BGR)
            salida[:, :, c] = np.clip(lienzo[:, :, c] * a_img + v * (1 - a_img), 0, 255).astype(np.uint8)
        salida[:, :, 3] = np.clip(np.maximum(a_borde, a_img) * 255.0, 0, 255).astype(np.uint8)
        im = salida
    ok, datos = cv2.imencode(".png", im)
    if not ok:
        raise RuntimeError("No se pudo guardar la imagen.")
    tmp = destino + ".tmp"
    datos.tofile(tmp)
    os.replace(tmp, destino)
    return destino


def guardar_mascara(ruta_mascara: str) -> str:
    """La máscara de «quitar el fondo» (que bg_removal deja en la caché que se limpia), copiada a la carpeta de las
    escenas: si la caché se vacía, la capa sigue sin fondo."""
    import shutil
    if not ruta_mascara or not os.path.isfile(ruta_mascara):
        return ruta_mascara
    with open(ruta_mascara, "rb") as f:
        h = hashlib.sha1(f.read()).hexdigest()[:20]
    destino = os.path.join(_carpeta(), f"mascara_{h}.png")
    if not os.path.isfile(destino):
        shutil.copyfile(ruta_mascara, destino)
    return destino


def texto_png(texto: str, color: str = "#FFFFFF", ancho: int = 1600, alto: int = 280) -> str:
    """Un texto como imagen (Arial en negrita, con contorno oscuro para que se lea sobre cualquier cosa), centrado y
    del tamaño que quepa: lo usan las plantillas (meme, antes / después). En caché por texto, color y tamaño."""
    from PIL import Image, ImageDraw
    from .escenas_prehechas import _fuente
    clave = json.dumps({"t": texto, "c": color, "w": ancho, "h": alto}, sort_keys=True)
    destino = os.path.join(_carpeta(), "texto_" + hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16] + ".png")
    if os.path.isfile(destino):
        return destino
    col = str(color or "#FFFFFF").lstrip("#")
    try:
        rgb = tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        rgb = (255, 255, 255)
    im = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t = str(texto or "").strip() or " "
    tam = int(alto * 0.8)
    while tam > 12:
        f = _fuente(tam)
        x0, y0, x1, y1 = d.textbbox((0, 0), t, font=f, stroke_width=max(2, tam // 14))
        if x1 - x0 <= ancho * 0.96 and y1 - y0 <= alto * 0.96:
            break
        tam = int(tam * 0.9)
    f = _fuente(tam)
    d.text((ancho / 2, alto / 2), t, font=f, anchor="mm", fill=rgb + (255,), stroke_width=max(2, tam // 14),
           stroke_fill=(10, 10, 10, 255))
    im.save(destino, "PNG")
    return destino


_CARPETA_N: tuple = ("", "")      # (carpeta de datos con la que se calculó, la carpeta propia normalizada)


def es_propia(ruta: str) -> bool:
    """¿Es una imagen hecha aquí (horneada o un texto)? (no se enseña en la lista de Local de Escenas). Barata: la
    carpeta se calcula (y se crea) una vez por carpeta de datos; la ruta, sin abspath si ya es absoluta."""
    global _CARPETA_N
    try:
        from .paths import app_data_dir
        datos = str(app_data_dir())
        if _CARPETA_N[0] != datos:
            _CARPETA_N = (datos, os.path.normcase(os.path.abspath(_carpeta())))
        r = ruta if os.path.isabs(ruta) else os.path.abspath(ruta)
        return os.path.normcase(os.path.dirname(r)) == _CARPETA_N[1]
    except (OSError, TypeError):
        return False
