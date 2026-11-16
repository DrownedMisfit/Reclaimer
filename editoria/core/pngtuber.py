"""
🎭 PNGTuber: tu avatar en PNG abre y cierra la boca cuando hablas y parpadea solo.

  · estados(): por cada fotograma, ¿boca abierta?, ¿ojos cerrados?, ¿cuánto sube (rebote)? — sale del volumen de
    la voz (los picos de media.waveform_peaks, PEAK_RATE por segundo) con un umbral relativo, histéresis y un
    mínimo de ~80 ms por estado (para que la boca no tiemble). Parpadeo al azar cada 2,5–6 s con semilla fija
    (siempre sale igual).
  · renderizar(): compone cada fotograma (PIL/numpy) sobre VERDE puro y lo manda a FFmpeg por tubería → mp4 H.264.
    En la línea de tiempo va con la 🟩 Pantalla verde (core/chroma.py): se ve igual en el visor y al exportar.
  · Mis PNGTubers: modelos guardados en datos/pngtubers/<nombre>.json (rutas de las imágenes + ajustes).

Sin Qt: lo usa la ventana ui/pngtuber_dialog.py y las pruebas.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
from typing import Callable, NamedTuple

import numpy as np

# El verde del fondo = el de la 🟩 Pantalla verde por defecto (así el croma lo quita sin tocar nada)
VERDE = "#00b140"
AZUL = "#0000ff"             # (si el avatar tiene verdes: el fondo va azul para no borrarle esas partes)
# Ajustes del croma para el avatar. Medidos contra el PNG original tras pasar por H.264 4:2:0: con 0.11/0.07 (los de
# siempre) quedaba un píxel de cerco alrededor (el color del borde se mezcla con el verde al reducir el color a la
# mitad); con 0.15/0.05 y el borde un poco endurecido (DUREZA) no queda cerco ni se come los grises.
CHROMA = {"color": VERDE, "similarity": 0.15, "blend": 0.05, "spill": True}

# (clave, nombre en pantalla, obligatoria, explicación para el tooltip)
IMAGENES = [
    ("cerrada", "😐 Boca cerrada", True, "Tu avatar callado (ojos abiertos, boca cerrada). Obligatoria."),
    ("abierta", "😮 Boca abierta", True, "Tu avatar hablando (ojos abiertos, boca abierta). Obligatoria."),
    ("ojos", "😌 Ojos cerrados", False, "Ojos cerrados y boca cerrada: para parpadear. Sin ella no parpadea."),
    ("ojos_abierta", "😪 Ojos cerrados hablando", False,
     "Ojos cerrados y boca abierta: para parpadear mientras hablas. Opcional."),
    ("media", "😯 Media boca", False, "Boca a medio abrir: se usa cuando hablas bajito. Opcional."),
]
OBLIGATORIAS = tuple(k for k, _n, o, _d in IMAGENES if o)

# Frecuencia de parpadeo: segundos entre parpadeos (al azar entre los dos)
PARPADEO = {"nunca": None, "poco": (4.0, 8.0), "normal": (2.5, 6.0), "mucho": (1.5, 3.5)}
DURACION_PARPADEO = 0.12
MIN_ESTADO = 0.08            # un estado de la boca dura como poco esto (s): sin temblores
DUREZA = 2.0                 # (borde del PNG: 1 = tal cual; 2 = algo más firme, sin cerco al quitar el verde)
SEMILLA = 7

AJUSTES = {"sensibilidad": 0.5, "parpadeo": "normal", "rebote": True, "tamano": 0.35,
           "posicion": "abajo_derecha"}

# Dónde va en pantalla
POSICIONES = [("abajo_derecha", "↘ Abajo a la derecha"), ("abajo_izquierda", "↙ Abajo a la izquierda"),
              ("arriba_derecha", "↗ Arriba a la derecha"), ("arriba_izquierda", "↖ Arriba a la izquierda"),
              ("abajo_centro", "⬇ Abajo en el centro"), ("centro", "⏺ En el centro")]


class Estado(NamedTuple):
    boca_abierta: bool
    ojos_cerrados: bool
    rebote_px: float = 0.0
    media_boca: bool = False      # (con boca_abierta: está solo a medio abrir)


# ---------------------------------------------------------------------------------------------- estados
def volumen_por_fotograma(peaks: np.ndarray, peak_rate: int, inicio: float, fin: float, fps: float = 30.0,
                          velocidad: float = 1.0) -> np.ndarray:
    """El pico de volumen de cada fotograma del tramo [inicio, fin] (segundos DEL ARCHIVO)."""
    velocidad = max(1e-3, float(velocidad or 1.0))
    n = max(1, int(round((fin - inicio) / velocidad * fps)))
    pk = np.asarray(peaks if peaks is not None else [], dtype=np.float32).reshape(-1)
    bordes = np.floor((inicio + np.arange(n + 1) / fps * velocidad) * peak_rate).astype(np.int64)
    bordes = np.maximum(bordes, 0)
    falta = int(bordes[-1]) + 1 - len(pk)
    if falta > 0:                                   # (más allá del archivo: silencio)
        pk = np.concatenate([pk, np.zeros(falta, np.float32)])
    a = bordes[:-1]
    b = np.maximum(bordes[1:], a + 1)
    cs = np.maximum.reduceat(pk, a) if len(pk) else np.zeros(n, np.float32)
    # reduceat va de a[i] a a[i+1]; con fotogramas iguales en tamaño basta, pero el último va hasta b[-1]
    if n:
        cs[-1] = float(pk[a[-1]:b[-1]].max()) if b[-1] > a[-1] else float(pk[a[-1]])
    return np.abs(cs[:n]).astype(np.float32)


def umbrales(vol: np.ndarray, sensibilidad: float = 0.5) -> tuple[float, float, float, float]:
    """(abrir, cerrar, boca entera, referencia). La referencia es lo fuerte que hablas (percentil 95 de lo que
    suena); sensibilidad 0 = solo abre con la voz fuerte, 1 = abre con casi cualquier sonido."""
    s = min(1.0, max(0.0, float(sensibilidad)))
    sonido = vol[vol > 0.003]
    ref = float(np.percentile(sonido, 95)) if len(sonido) else 0.0
    if ref < 0.01:                                   # todo es silencio (o ruido de fondo): nunca abre
        return math.inf, math.inf, math.inf, ref
    abrir = ref * (0.55 - 0.45 * s)
    cerrar = abrir * 0.65
    entera = abrir + (ref - abrir) * 0.45
    return abrir, cerrar, entera, ref


def estados(peaks: np.ndarray, peak_rate: int, inicio: float, fin: float, sensibilidad: float = 0.5,
            fps: float = 30.0, parpadeo: tuple[float, float] | None = PARPADEO["normal"],
            duracion_parpadeo: float = DURACION_PARPADEO, media_boca: bool = False, rebote_px: float = 0.0,
            semilla: int = SEMILLA, min_estado: float = MIN_ESTADO, velocidad: float = 1.0) -> list[Estado]:
    """Un Estado por fotograma del tramo [inicio, fin] (segundos del archivo; velocidad = la del clip).
    · Boca: abre cuando el volumen pasa el umbral y cierra cuando baja del de cierre (histéresis); cada estado dura
      al menos «min_estado». media_boca=True: con voz baja, a medio abrir.
    · Ojos: parpadeo al azar (cada parpadeo[0]–parpadeo[1] s, de «duracion_parpadeo» s); None = no parpadea.
    · Rebote: sube hasta rebote_px al hablar, con suavidad (0 = quieto)."""
    vol = volumen_por_fotograma(peaks, peak_rate, inicio, fin, fps, velocidad)
    n = len(vol)
    abrir, cerrar, entera, ref = umbrales(vol, sensibilidad)
    hold = max(1, math.ceil(min_estado * fps - 1e-9))
    boca = np.zeros(n, np.int8)                       # 0 cerrada · 1 media · 2 abierta
    estado, llevo = 0, hold
    for i in range(n):
        v = float(vol[i])
        if estado == 0:
            quiero = 0 if v < abrir else (2 if (not media_boca or v >= entera) else 1)
        else:
            quiero = 0 if v < cerrar else (2 if (not media_boca or v >= entera) else 1)
        if quiero != estado and llevo >= hold:
            estado, llevo = quiero, 0
        llevo += 1
        boca[i] = estado

    ojos = np.zeros(n, bool)
    if parpadeo:
        lo, hi = float(parpadeo[0]), float(max(parpadeo[0], parpadeo[1]))
        rng = random.Random(semilla)
        largo = max(2, int(round(duracion_parpadeo * fps)))
        t = rng.uniform(lo, hi)
        while t * fps < n:
            a = int(round(t * fps))
            ojos[a:a + largo] = True
            t += duracion_parpadeo + rng.uniform(lo, hi)

    rebote = np.zeros(n, np.float32)
    if rebote_px > 0 and ref > 0:
        y = 0.0
        for i in range(n):
            meta = float(rebote_px) * min(1.0, 0.6 + 0.4 * float(vol[i]) / ref) if boca[i] else 0.0
            y += (meta - y) * (0.45 if meta > y else 0.25)
            rebote[i] = round(y, 2)

    return [Estado(bool(boca[i]), bool(ojos[i]), float(rebote[i]), bool(boca[i] == 1)) for i in range(n)]


def imagen_para(e: Estado, tiene: set[str] | dict) -> str:
    """Qué imagen del modelo toca en ese estado (según las que haya)."""
    if e.boca_abierta:
        if e.ojos_cerrados and "ojos_abierta" in tiene:
            return "ojos_abierta"
        if e.media_boca and "media" in tiene:
            return "media"
        return "abierta"
    if e.ojos_cerrados and "ojos" in tiene:
        return "ojos"
    return "cerrada"


# ---------------------------------------------------------------------------------------------- imágenes
def _rgb(hexcol: str) -> tuple[int, int, int]:
    h = hexcol.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _dist(rgb: np.ndarray, color: str) -> np.ndarray:
    """Distancia de color (Cb/Cr, como chromakey de FFmpeg) de cada píxel al color del fondo."""
    from .chroma import _cbcr
    kr, kg, kb = _rgb(color)
    kcb, kcr = _cbcr(kr, kg, kb)
    cb, cr = _cbcr(rgb[..., 0], rgb[..., 1], rgb[..., 2])
    return np.sqrt(((cb - kcb) ** 2 + (cr - kcr) ** 2) / (255.0 * 255.0 * 2))


def chroma_para(color: str = VERDE) -> dict:
    """fx["chroma"] para el video del avatar con ese fondo (la tolerancia, en proporción a lo saturado del color)."""
    k = float(_dist(np.array([[128.0, 128.0, 128.0]]), color)[0]) / float(
        _dist(np.array([[128.0, 128.0, 128.0]]), VERDE)[0])
    return dict(CHROMA, color=color, similarity=round(CHROMA["similarity"] * k, 4),
                blend=round(CHROMA["blend"] * k, 4))


def fondo_para(modelo: dict) -> str:
    """VERDE, o AZUL si el avatar tiene partes verdes que el croma se comería."""
    from PIL import Image

    def malos(color: str) -> float:
        ch = chroma_para(color)
        lim = ch["similarity"] + ch["blend"] + 0.01      # (los grises están a 0.232 del verde: se quedan)
        peor = 0.0
        for p in rutas(modelo).values():
            try:
                with Image.open(p) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((256, 256))
                    a = np.asarray(im, dtype=np.float32)
            except OSError:
                continue
            op = a[..., 3] > 200
            if op.any():
                peor = max(peor, float((_dist(a[..., :3][op], color) < lim).mean()))
        return peor

    v = malos(VERDE)
    if v <= 0.003:
        return VERDE
    return AZUL if malos(AZUL) < v else VERDE


def rutas(modelo: dict) -> dict[str, str]:
    """Las imágenes del modelo que existen de verdad: {clave: ruta}."""
    out = {}
    for k, v in ((modelo or {}).get("imagenes") or {}).items():
        if isinstance(v, str) and v and os.path.isfile(v):
            out[k] = v
    return out


def falta(modelo: dict) -> list[str]:
    """Nombres de las imágenes obligatorias que faltan (vacío = se puede crear)."""
    r = rutas(modelo)
    return [n for k, n, o, _d in IMAGENES if o and k not in r]


def _cargar(rs: dict[str, str]) -> dict:
    """Las imágenes en RGBA, todas del tamaño de «boca cerrada» (las demás se encajan centradas)."""
    from PIL import Image
    out = {}
    base = Image.open(rs["cerrada"]).convert("RGBA")
    out["cerrada"] = base
    for k, p in rs.items():
        if k == "cerrada":
            continue
        im = Image.open(p).convert("RGBA")
        if im.size != base.size:
            esc = min(base.width / im.width, base.height / im.height)
            nw, nh = max(1, round(im.width * esc)), max(1, round(im.height * esc))
            im = im.convert("RGBa").resize((nw, nh), Image.LANCZOS).convert("RGBA")
            lienzo = Image.new("RGBA", base.size, (0, 0, 0, 0))
            lienzo.paste(im, ((base.width - nw) // 2, (base.height - nh) // 2))
            im = lienzo
        out[k] = im
    return out


def medida(modelo: dict, alto: int, rebote_px: float = 0.0) -> tuple[int, int, int, int]:
    """(ancho, alto) del video para que la imagen mida «alto» px (+ el margen de arriba del rebote) y (ancho, alto)
    de la imagen dentro. Siempre pares (H.264 4:2:0)."""
    from PIL import Image
    with Image.open(rutas(modelo)["cerrada"]) as im:
        w0, h0 = im.size
    margen = int(math.ceil(max(0.0, rebote_px)))
    ih = max(8, int(alto) - margen)
    iw = max(8, int(round(w0 * ih / h0)))
    W = iw + (iw % 2)
    H = ih + margen
    H += H % 2
    return W, H, iw, ih


def preparar(modelo: dict, alto: int, rebote_px: float = 0.0, verde: str = VERDE, dureza: float = DUREZA) -> dict:
    """Las imágenes ya a su tamaño final (premultiplicadas): {"W", "H", "iw", "ih", "capas": {clave: (rgb, a)}}.
    dureza > 1: el borde semitransparente se endurece (menos mezcla con el verde = sin halo al quitarlo)."""
    from PIL import Image
    rs = rutas(modelo)
    if any(k not in rs for k in OBLIGATORIAS):
        raise ValueError("Faltan imágenes: " + ", ".join(falta(modelo)))
    W, H, iw, ih = medida(modelo, alto, rebote_px)
    capas = {}
    for k, im in _cargar(rs).items():
        pm = im.convert("RGBa").resize((iw, ih), Image.LANCZOS)        # (sin bordes oscuros al encoger)
        arr = np.asarray(pm, dtype=np.float32)
        rgb, a = arr[..., :3], arr[..., 3:4] / 255.0
        if dureza > 1.0:
            a2 = np.clip((a - 0.5) * dureza + 0.5, 0.0, 1.0)
            rgb = rgb / np.maximum(a, 1e-4) * a2          # (el color propio del borde, con el alfa nuevo)
            a = a2
        capas[k] = (rgb, a)
    return {"W": W, "H": H, "iw": iw, "ih": ih, "capas": capas, "verde": np.array(_rgb(verde), np.float32)}


def componer(prep: dict, clave: str, subir: int = 0) -> np.ndarray:
    """Un fotograma RGB uint8 (H, W, 3): la imagen «clave» sobre el verde, pegada abajo y subida «subir» px.
    El borde ya viene algo endurecido de preparar() (DUREZA): el croma con CHROMA lo deja limpio, sin cerco."""
    W, H, iw, ih = prep["W"], prep["H"], prep["iw"], prep["ih"]
    rgb, a = prep["capas"].get(clave) or prep["capas"]["cerrada"]
    out = np.empty((H, W, 3), np.float32)
    out[:] = prep["verde"]
    x = (W - iw) // 2
    y = max(0, H - ih - int(subir))
    zona = out[y:y + ih, x:x + iw]
    zona[:] = rgb + zona * (1.0 - a)                  # (rgb ya premultiplicado)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def renderizar(modelo: dict, estados_: list[Estado], salida_mp4: str, tamano: int, fps: float = 30.0,
               progress: Callable | None = None, cancelled: Callable | None = None, verde: str = VERDE,
               dureza: float = DUREZA) -> dict:
    """Crea el video del avatar (mp4 H.264 yuv420p, sin sonido) sobre verde. tamano = alto en px.
    Devuelve {"ruta", "ancho", "alto", "fotogramas", "duracion"}. Cancelar (cancelled() → True) borra lo hecho."""
    from . import media as M
    tiene = rutas(modelo)
    if "ojos" not in tiene:                       # sin «ojos cerrados» no parpadea
        tiene.pop("ojos_abierta", None)
    sube = max((e.rebote_px for e in estados_), default=0.0)
    prep = preparar(modelo, int(tamano), sube, verde, dureza)
    W, H = prep["W"], prep["H"]
    n = len(estados_)
    if n == 0:
        raise ValueError("No hay nada que crear (el tramo está vacío).")
    os.makedirs(os.path.dirname(os.path.abspath(salida_mp4)) or ".", exist_ok=True)
    tmp = salida_mp4 + ".parte.mp4"
    args = [M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
            "-r", f"{fps:g}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=M.NO_WINDOW)
    cache: dict[tuple[str, int], bytes] = {}
    roto = False
    try:
        for i, e in enumerate(estados_):
            clave = imagen_para(e if "ojos" in tiene else e._replace(ojos_cerrados=False), tiene)
            k = (clave, int(round(e.rebote_px)))
            fr = cache.get(k)
            if fr is None:
                fr = componer(prep, clave, k[1]).tobytes()
                cache[k] = fr
            try:
                proc.stdin.write(fr)
            except (BrokenPipeError, OSError):
                roto = True
                break
            if i % 30 == 0:
                if cancelled is not None and cancelled():
                    raise _Cancelado()
                if progress is not None:
                    progress(min(0.99, i / n), f"🎭 Creando el avatar… {i * 100 // n} %")
        try:
            proc.stdin.close()
        except OSError:
            roto = True
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
        if roto or proc.returncode != 0:
            raise RuntimeError("FFmpeg no pudo crear el video del avatar: " + err.strip()[-300:])
        os.replace(tmp, salida_mp4)
    except BaseException as exc:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        if isinstance(exc, _Cancelado):
            from ..ai.base import Cancelled
            raise Cancelled() from None
        raise
    if progress is not None:
        progress(1.0, "🎭 Avatar listo")
    return {"ruta": salida_mp4, "ancho": W, "alto": H, "fotogramas": n, "duracion": n / fps}


class _Cancelado(Exception):
    pass


# ---------------------------------------------------------------------------------------------- en pantalla
def layout(ancho: int, alto: int, pw: int, ph: int, posicion: str = "abajo_derecha", margen: float = 0.02) -> dict:
    """La disposición (core/transform.py, fracciones de la pantalla) para que el video del avatar (ancho × alto px)
    salga a su tamaño real en la esquina elegida."""
    w, h = min(1.0, ancho / max(1, pw)), min(1.0, alto / max(1, ph))
    mx, my = margen * min(pw, ph) / pw, margen * min(pw, ph) / ph
    if posicion.endswith("derecha"):
        x = 1.0 - w - mx
    elif posicion.endswith("izquierda"):
        x = mx
    else:
        x = (1.0 - w) / 2
    if posicion.startswith("arriba"):
        y = my
    elif posicion == "centro":
        y = (1.0 - h) / 2
    else:
        y = 1.0 - h                                    # abajo: pegado al borde (el avatar «sale» de abajo)
    r = lambda v: round(max(0.0, v), 5)  # noqa: E731
    return {"x": r(x), "y": r(y), "w": r(w), "h": r(h), "fit": "contain", "bg": "none"}


def alto_en_px(tamano: float, ph: int) -> int:
    """El alto del avatar (fracción de la pantalla) en píxeles del proyecto (par)."""
    a = int(round(max(0.05, min(1.0, float(tamano))) * ph))
    return a + (a % 2)


def rebote_para(alto: int) -> float:
    """Cuánto sube al hablar con «rebote» (unos píxeles, según su tamaño)."""
    return float(max(2, round(alto * 0.035)))


def carpeta_videos(project_path: str | None = None) -> str:
    """Donde se guardan los videos del avatar: junto al proyecto (carpeta «PNGTuber») o en tus cosas."""
    from .paths import app_data_dir, user_dir
    if project_path:
        base = os.path.dirname(os.path.abspath(project_path))
    else:
        base = str(app_data_dir() if os.environ.get("EDITORIA_DATOS") else user_dir())   # (las pruebas: su carpeta)
    d = os.path.join(base, "PNGTuber")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------------- Mis PNGTubers
RESERVADOS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def carpeta_modelos() -> str:
    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "pngtubers")
    os.makedirs(d, exist_ok=True)
    return d


def _archivo(nombre: str) -> str:
    """El .json de ese modelo, SIEMPRE dentro de la carpeta (sin barras, ni «..», ni nombres reservados)."""
    limpio = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', " ", str(nombre))
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")[:80] or "Mi PNGTuber"
    if limpio.lower() in RESERVADOS:
        limpio = "_" + limpio
    return os.path.join(carpeta_modelos(), limpio + ".json")


def existe(nombre: str) -> bool:
    return os.path.exists(_archivo(nombre))


def guardar(modelo: dict) -> str:
    """Guarda el modelo (nombre, rutas de las imágenes, ajustes). Devuelve la ruta del .json."""
    nombre = str(modelo.get("nombre") or "").strip() or "Mi PNGTuber"
    datos = {"nombre": nombre,
             "imagenes": {k: os.path.abspath(v) for k, v in (modelo.get("imagenes") or {}).items()
                          if isinstance(v, str) and v},
             "ajustes": dict(AJUSTES, **(modelo.get("ajustes") or {}))}
    ruta = _archivo(nombre)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)
    return ruta


def cargar(ruta_o_nombre: str) -> dict | None:
    ruta = ruta_o_nombre if ruta_o_nombre.lower().endswith(".json") and os.path.isfile(ruta_o_nombre) \
        else _archivo(ruta_o_nombre)
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    im = d.get("imagenes") if isinstance(d.get("imagenes"), dict) else {}
    aj = d.get("ajustes") if isinstance(d.get("ajustes"), dict) else {}
    return {"nombre": str(d.get("nombre") or os.path.splitext(os.path.basename(ruta))[0]),
            "imagenes": {str(k): str(v) for k, v in im.items() if isinstance(v, str)},
            "ajustes": dict(AJUSTES, **aj), "archivo": ruta}


def listar() -> list[dict]:
    """Los modelos guardados, por nombre."""
    out = []
    d = carpeta_modelos()
    for f in sorted(os.listdir(d), key=str.lower):
        if f.lower().endswith(".json"):
            m = cargar(os.path.join(d, f))
            if m is not None:
                out.append(m)
    return out


def borrar(nombre_o_modelo) -> bool:
    ruta = nombre_o_modelo.get("archivo") if isinstance(nombre_o_modelo, dict) else None
    ruta = ruta or _archivo(nombre_o_modelo["nombre"] if isinstance(nombre_o_modelo, dict) else nombre_o_modelo)
    try:
        os.remove(ruta)
        return True
    except OSError:
        return False
