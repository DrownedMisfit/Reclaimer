"""
🎬 ARMA TU VIDEO (paso 3 de «Edita desde tu voz»; lógica SIN Qt, vale para la versión pública y la privada).

Un clic arma la línea de tiempo SIN HUECOS sobre la narración ya pulida: cada frase lleva el material donde se nombra,
por orden de prioridad, sin repetir ninguna escena (huella por plano) y sin tocar lo que el usuario puso a mano.

  Niveles (de mejor a peor), para cada pieza (la frase, o hasta el siguiente cambio):
    1. «exacto»     el momento EXACTO: lo que describe (CLIP texto → fotograma, en sus clips y en lo descargado) o lo
                    que cita (la frase dicha también en la voz de otro archivo transcrito);
    2. «mis_clips»  sus clips de Medios por palabra clave (nombre, carpeta, categoría y etiquetas: buscador.entender);
    3. «internet»   versión privada: cinemáticas, tráileres y gameplay sin comentarios, oficiales primero, SOLO el trozo
                    (material_videos.para_armar); versión pública: imágenes libres (Openverse / Commons);
    4. «base»       la imagen de su grabación de OBS (si eligió usarla), sincronizada con la voz;
    5. «relleno»    su carpeta de relleno (un ajuste);
    6. «cualquiera» lo que quede sin usar de sus clips (nunca negro).
  Nunca videos de stock. Las imágenes, pocas (una cada IMG_CADA s como mucho), encima de un video que se desenfoca y
  con sombra (estilo «auto» de core/overlay). Todo lo puesto va mudo (B-roll).

  Uso (el panel de «Edita desde tu voz» lo hace por trozos con ui/armar_video.Armador):
    inst = instantanea(ctrl, desde, hasta, ajustes)      hilo de la interfaz: lee el proyecto (copias, nada vivo)
    plan = planear(inst, fuentes, progreso, cancelado, pausado)     cualquier hilo: busca, baja y elige (sin tocar
                                                                    el proyecto)
    res  = colocar(ctrl, plan, sesion)                   hilo de la interfaz: UN paso de Ctrl+Z (los trozos de una
                                                         misma sesión se juntan en ese mismo paso)
    armar(ctrl, desde, hasta, fuentes, progreso, cancelado, ajustes, sesion)    los tres seguidos (pruebas, MCP)
    alternativas_de(clip_id) / cambiar(ctrl, clip_id, k)  clic derecho → «Cambiar» (un clic, un Ctrl+Z)
    avisos_previos(inst, fuentes)                        «sin internet», «sin clips», «poco disco» antes de empezar
    pendiente(ctrl) / guardar_estado(...) / borrar_estado(ctrl)     «Seguir armando» al reabrir

  `Fuentes` reúne lo que viene de fuera (CLIP, internet, disco): las pruebas pasan una simulada (sin red).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import unicodedata

import numpy as np

from .base import Cancelled, check_cancel

NOTA = "🎬 Arma tu video"
TITULO_DESHACER = "🎬 Arma tu video"
NIVELES = ("exacto", "mis_clips", "internet", "base", "relleno", "cualquiera")
NOMBRE_NIVEL = {"exacto": "El momento exacto", "mis_clips": "Tus clips", "internet": "De internet",
                "base": "La imagen de tu grabación", "relleno": "Tu carpeta de relleno",
                "cualquiera": "Otro trozo de tus clips"}

MIN_PIEZA = 1.0          # s: una pieza más corta se junta con la de al lado
MAX_PIEZA = 7.0          # s: una pieza más larga se parte (más ritmo; el material cambia)
MAX_PIEZA_VERTICAL = 4.0  # Shorts: corte más rápido
MIN_HUECO = 0.3          # s: un hueco más corto no se rellena
PAUSA_FRASE = 0.7        # s de silencio que cortan una frase
FIN_FRASE = ".?!…;"
MAX_PALABRAS = 28
UMBRAL_EXACTO = 0.26     # parecido CLIP (coseno) para dar un fotograma por «el momento exacto»
CITA_MIN = 4             # palabras seguidas iguales para que sea una cita
IMG_CADA = 15.0          # s como poco entre una imagen y la siguiente (imágenes pocas)
IMG_MAX = 5.0            # s que dura una imagen como mucho
ALTERNATIVAS = 3
MARGEN_DESCARGA = 2.0    # s de más a cada lado del trozo que se baja
MIN_LIBRE_GB = 3.0       # menos espacio libre: no se baja nada (aviso)
TOPE_DESCARGAS_MB = 1500  # lo que se baja como mucho en una sesión de armado
DESCARGAS_A_LA_VEZ = 3
EPS = 1e-3

SIN_INTERNET = "Sin internet: armo con tus clips y tu carpeta de relleno."
SIN_CLIPS_PRIVADA = "No tienes clips en Medios: busco el material en internet (cinemáticas, tráileres y gameplay)."
SIN_CLIPS_PUBLICA = "No tienes clips en Medios: uso imágenes libres de internet y tu carpeta de relleno."
POCO_DISCO = "Queda poco espacio en el disco ({gb:.1f} GB): no bajo nada de internet."
TOPE_BAJADO = "Llegué al límite de descargas de esta vez ({mb} MB): el resto sale de tus clips y del relleno."


# ================================================================ texto
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-zñ ]+", " ", s)


def _palabras_norm(s: str) -> list[str]:
    return [w for w in _norm(s).split() if w]


# ================================================================ instantánea (hilo de la interfaz)
def _frases_en_linea(project) -> tuple[list[dict], list[dict]]:
    """Las frases de la narración en segundos de la LÍNEA DE TIEMPO (clips de audio con transcripción), en orden, y
    los clips de narración [{"start","end","source_in","speed","media_id"}] (para la imagen de la grabación)."""
    from ..core.model import TRACK_AUDIO
    palabras, narr = [], []
    trans = getattr(project, "transcripts", None) or {}
    for c in project.clips.values():
        tr = project.track(c.track_id)
        if tr is None or tr.kind != TRACK_AUDIO or not c.enabled or c.speed <= 0 or c.reverse:
            continue
        words = (trans.get(c.media_id) or {}).get("words") or []
        if not words:
            continue
        narr.append({"start": float(c.start), "end": float(c.end), "source_in": float(c.source_in),
                     "speed": float(c.speed), "media_id": c.media_id})
        s0, s1 = float(c.source_in), float(c.source_in) + float(c.src_len)
        for w in words:
            a, b = float(w[0]), float(w[1])
            if a < s0 - EPS or a >= s1 - EPS:
                continue
            t0 = c.start + (a - s0) / c.speed
            t1 = c.start + (min(b, s1) - s0) / c.speed
            palabras.append((t0, max(t0 + 0.05, t1), str(w[2]).strip()))
    palabras.sort()
    frases: list[dict] = []
    cur: list = []
    for i, (a, b, w) in enumerate(palabras):
        if cur and (a - cur[-1][1] > PAUSA_FRASE or len(cur) >= MAX_PALABRAS):
            frases.append(cur)
            cur = []
        cur.append((a, b, w))
        if w.rstrip().endswith(tuple(FIN_FRASE)):
            frases.append(cur)
            cur = []
    if cur:
        frases.append(cur)
    out = [{"t0": round(f[0][0], 4), "t1": round(f[-1][1], 4), "texto": " ".join(x[2] for x in f).strip()}
           for f in frases if f]
    return out, sorted(narr, key=lambda d: d["start"])


def _piezas(frases: list[dict], huecos: list[tuple[float, float]], max_pieza: float) -> list[dict]:
    """Cada hueco en piezas: corta donde empieza una frase; la pieza lleva la frase que se dice al empezar (o la
    última dicha, o la siguiente). Las cortas se juntan y las largas se parten."""
    starts = [f["t0"] for f in frases]
    tramos = [(f["t0"], frases[i + 1]["t0"] if i + 1 < len(frases) else math.inf, f) for i, f in enumerate(frases)]

    def frase_de(x0: float, x1: float) -> dict | None:
        """La frase que más ocupa la pieza (cada frase dura hasta que empieza la siguiente); si ninguna, la última
        dicha antes, o la primera."""
        mejor = max(tramos, key=lambda t: min(x1, t[1]) - max(x0, t[0]), default=None)
        if mejor is not None and min(x1, mejor[1]) - max(x0, mejor[0]) > EPS:
            return mejor[2]
        prev = [f for f in frases if f["t0"] <= x0 + EPS]
        if prev:
            return prev[-1]
        return frases[0] if frases else None

    out: list[dict] = []
    for h0, h1 in huecos:
        cortes = [h0] + [s for s in starts if h0 + MIN_PIEZA <= s <= h1 - MIN_PIEZA] + [h1]
        trozos = [[cortes[i], cortes[i + 1]] for i in range(len(cortes) - 1) if cortes[i + 1] - cortes[i] > EPS]
        juntos: list[list] = []                      # (las cortas, con la de antes del mismo hueco)
        for t in trozos:
            if juntos and t[1] - t[0] < MIN_PIEZA:
                juntos[-1][1] = t[1]
            else:
                juntos.append(t)
        if len(juntos) > 1 and juntos[0][1] - juntos[0][0] < MIN_PIEZA:
            juntos[1][0] = juntos[0][0]
            juntos.pop(0)
        for a, b in juntos:
            n = max(1, int(math.ceil((b - a) / max_pieza - 1e-6)))
            paso = (b - a) / n
            for k in range(n):
                x0, x1 = a + k * paso, (b if k == n - 1 else a + (k + 1) * paso)
                f = frase_de(x0, x1)
                out.append({"t0": round(x0, 4), "t1": round(x1, 4), "frase": (f or {}).get("texto", ""),
                            "f0": (f or {}).get("t0")})
    return out


def _recortar(huecos: list, desde: float, hasta: float | None) -> list:
    out = []
    for a, b in huecos:
        a2, b2 = max(a, desde), (b if hasta is None else min(b, hasta))
        if b2 - a2 >= MIN_HUECO:
            out.append((round(a2, 4), round(b2, 4)))
    return out


def pista_destino(project):
    """La pista de video principal (la de abajo) sin bloquear, o la siguiente sin bloquear hacia arriba."""
    from ..core import autocompletar as AC
    return AC.pista_destino(project)


def huecos_actuales(project, desde: float = 0.0, hasta: float | None = None) -> list[tuple[float, float]]:
    """Donde hay voz (o música) y no se ve nada (ningún clip de video encima, ni en la pista donde va el armado)."""
    from ..core import autocompletar as AC
    tr = pista_destino(project)
    return _recortar(AC.huecos(project, destino=tr.id if tr is not None else None), desde, hasta)


def _bajo(ruta: str, carpeta: str | None) -> bool:
    if not carpeta:
        return False
    try:
        r = os.path.normcase(os.path.abspath(ruta))
        c = os.path.normcase(os.path.abspath(carpeta))
        return os.path.commonpath([r, c]) == c
    except ValueError:
        return False


def archivos_relleno(carpeta: str | None) -> list[str]:
    """Los videos de la carpeta de relleno (y sus subcarpetas), por nombre."""
    from ..core.model import KIND_VIDEO, kind_for_path
    if not carpeta or not os.path.isdir(carpeta):
        return []
    out = []
    for raiz, dirs, fs in os.walk(carpeta):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        out += [os.path.join(raiz, f) for f in sorted(fs) if kind_for_path(f) == KIND_VIDEO]
    return out


def clave_proyecto(ctrl) -> str:
    """Qué proyecto es (para «Seguir armando» y para no mezclar pestañas): su archivo o el de su pestaña."""
    return os.path.normcase(os.path.abspath(str(getattr(ctrl, "path", None) or getattr(ctrl, "workspace_file", None)
                                                or "sin_nombre")))


def instantanea(ctrl, desde: float = 0.0, hasta: float | None = None, ajustes: dict | None = None) -> dict:
    """Todo lo que el plan necesita del proyecto, COPIADO (el plan corre en otro hilo y el usuario puede seguir
    editando). Hilo de la interfaz."""
    from ..core.model import KIND_IMAGE, KIND_VIDEO
    ajustes = dict(ajustes or {})
    p = ctrl.project
    missing = set(getattr(ctrl, "missing", set()) or ())
    frases, narr = _frases_en_linea(p)
    narr_ids = {d["media_id"] for d in narr}
    huecos = huecos_actuales(p, float(desde or 0.0), hasta)
    vertical = p.height > p.width
    piezas = _piezas(frases, huecos, MAX_PIEZA_VERTICAL if vertical else MAX_PIEZA)
    base = ajustes.get("base_media_id")
    relleno = ajustes.get("carpeta_relleno")
    medios = []
    trans_otros = {}
    for m in p.media.values():
        if m.id in missing or getattr(m, "gen", None) or m.id in (p.compounds or {}) or m.id in narr_ids \
                or m.id == base or m.kind not in (KIND_VIDEO, KIND_IMAGE) or _bajo(m.path, relleno):
            continue
        if m.kind == KIND_VIDEO and not m.duration:
            continue
        carpeta = os.path.dirname(os.path.abspath(m.path))
        meta = " ".join([os.path.splitext(m.name or os.path.basename(m.path))[0], os.path.basename(carpeta),
                         os.path.basename(os.path.dirname(carpeta)), m.category or "",
                         " ".join(getattr(m, "tags", None) or [])])
        medios.append({"media_id": m.id, "ruta": m.path, "tipo": "imagen" if m.kind == KIND_IMAGE else "video",
                       "dur": float(m.duration or 0.0), "meta": meta, "nombre": m.name})
        words = ((p.transcripts or {}).get(m.id) or {}).get("words") or []
        if words and m.kind == KIND_VIDEO:
            trans_otros[m.id] = [(float(w[0]), float(w[1]), str(w[2])) for w in words]
    bm = p.media.get(base) if base else None
    imagenes_hechas = sorted(c.start for c in p.clips.values() if (c.note or "") == NOTA and
                             (p.media.get(c.media_id) is not None and p.media[c.media_id].kind == KIND_IMAGE))
    try:
        from . import material_por_frases as M
        vecs_img = M.huellas_en_proyecto(p)
    except Exception:  # noqa: BLE001
        vecs_img = []
    return {
        "entidades": _entidades(ctrl, {d["media_id"] for d in medios}),
        "desde": float(desde or 0.0), "hasta": hasta, "frases": frases, "piezas": piezas, "huecos": huecos,
        "narracion": narr, "medios": medios, "transcripciones": trans_otros, "vertical": vertical,
        "alto": int(min(p.width, p.height)), "ancho": int(p.width), "ajustes": ajustes,
        "base": ({"media_id": bm.id, "ruta": bm.path, "dur": float(bm.duration or 0.0)} if bm is not None else None),
        "relleno": archivos_relleno(relleno), "imagenes_hechas": imagenes_hechas, "vecs_imagen": vecs_img,
        "tomados": _TomadosArmado(p, missing),
        "rutas_proyecto": {os.path.normcase(os.path.abspath(m.path)): m.id for m in p.media.values()},
        "proyecto": clave_proyecto(ctrl),
        "rev": getattr(ctrl, "rev", 0),
    }


def _entidades(ctrl, medios: set) -> list[dict]:
    """🔬 «Mirar mis clips a fondo» (ctrl.understanding): quién y qué aparece y dónde, COPIADO para el hilo del plan:
    [{"nombres": [...], "hits": [(media_id, segundo, inicio_plano, fin_plano, puntos)]}] (solo medios que se pueden
    usar). Vacío si no se analizó."""
    u = getattr(ctrl, "understanding", None) or {}
    idx = u.get("index") or {}
    out = []
    for e in u.get("entities") or []:
        nombre = getattr(e, "name", None)
        hits = [(h.media_id, float(h.time), float(h.start), float(h.end), float(h.score))
                for h in idx.get(nombre, []) if h.media_id in medios]
        if nombre and hits:
            out.append({"nombres": list(e.all_names()), "hits": hits[:6]})
    return out


def _dicho(nombres: list, frase: str) -> bool:
    t = " " + " ".join(_palabras_norm(frase)) + " "
    return any(f" {' '.join(_palabras_norm(n))} " in t for n in nombres if _palabras_norm(n))


# ================================================================ sin repetir (huella por plano, también archivos nuevos)
class _TomadosArmado:
    """core/repetidos.Tomados + archivos que aún no están en el proyecto (lo bajado y la carpeta de relleno), por su
    clave «ruta:…». Al registrar un archivo nuevo, lo que ya sale en la línea de tiempo y se ve también en él (huella)
    queda reservado en él."""

    def __init__(self, project, missing=()):
        from ..core import repetidos
        self.t = repetidos.Tomados(project, missing)
        self._lock = threading.Lock()

    def registrar(self, clave: str, ruta: str, dur: float, calcular_huella: bool = False, cancelled=None):
        from ..core import huella_plano as HP
        from ..core import repetidos
        with self._lock:
            if clave in self.t._medios:
                return
        hu = HP.cargar(ruta)
        if hu is None and calcular_huella:
            try:
                hu = HP.calcular(ruta, dur, cancelled)
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001 - sin huella: solo cuenta lo del mismo archivo
                hu = None
        with self._lock:
            otros = []
            for mid, (path, _d) in self.t._medios.items():
                rangos = [r for r in self.t.get(mid, []) if math.isfinite(r[1])]
                ho = HP.cargar(path) if rangos else None
                if ho is not None:
                    otros.append((ho, rangos))
            if hu is not None and otros:
                for r in repetidos._equivalencias((ruta, float(dur), hu), otros):
                    self.t.setdefault(clave, []).append(r)
            self.t._medios[clave] = (ruta, float(dur))
            self.t._ind = None

    def libre(self, clave: str, src0: float, dur: float, dur_archivo: float) -> float | None:
        from .broll_selection import find_free
        with self._lock:
            return find_free(self.t, clave, src0, dur, dur_archivo)

    def tomar(self, clave: str, src: float, dur: float, imagen: bool = False):
        from .broll_selection import claim
        with self._lock:
            claim(self.t, clave, src, dur, image=imagen)

    def usada(self, clave: str) -> bool:
        with self._lock:
            return bool(self.t.get(clave))


# ================================================================ fuentes (lo de fuera: CLIP, internet, disco)
class Fuentes:
    """Lo que viene de fuera. Las pruebas la sustituyen (sin red, sin modelos). Atributos para el panel:
    fallos (búsquedas que no respondieron), avisos (lo que no se pudo bajar), bajado (bytes de esta sesión)."""

    def __init__(self, internet: bool = True, enc_texto=None, enc_imagen=None):
        self.usar_internet = bool(internet)
        self.enc_texto, self.enc_imagen = enc_texto, enc_imagen
        self.fallos: list[str] = []
        self.avisos: list[str] = []
        self.bajado = 0
        self._sin_red = None
        self._video = None
        self._tramos: dict = {}

    # -- CLIP
    def encoders(self):
        if self.enc_texto is None or self.enc_imagen is None:
            from . import embeddings
            self.enc_texto = self.enc_texto or embeddings.get("clip_text")
            self.enc_imagen = self.enc_imagen or embeddings.get("clip_image")
        return self.enc_texto, self.enc_imagen

    def vector_texto(self, textos: list[str]) -> np.ndarray:
        enc, _ = self.encoders()
        v = enc.encode(list(textos)).mean(axis=0)
        return (v / max(1e-9, float(np.linalg.norm(v)))).astype(np.float32)

    def vectores(self, medio: dict):
        """(segundos, huellas CLIP) de un clip ya analizado (◈ Analizar clips con IA), o None."""
        from . import clip_analysis
        try:
            got = clip_analysis.load_cached(medio["ruta"])
        except Exception:  # noqa: BLE001
            return None
        if got is None or not len(got[1]):
            return None
        return np.asarray(got[0], np.float32), np.asarray(got[1], np.float32)

    # -- disco e internet
    def disco_libre(self, carpeta: str | None = None) -> float:
        import shutil
        try:
            from ..core.paths import app_data_dir
            return shutil.disk_usage(carpeta or str(app_data_dir())).free / 1e9
        except OSError:
            return 1e9

    def hay_internet(self) -> bool:
        if not self.usar_internet:
            return False
        if self._sin_red is None:
            import socket
            try:
                socket.create_connection(("www.youtube.com", 443), timeout=3).close()
                self._sin_red = False
            except OSError:
                self._sin_red = True
        return not self._sin_red

    def privada(self) -> bool:
        from . import material_por_frases as M
        return M.hay_videos()

    def internet(self, pieza: dict, cancelado=None, usados_vecs=(), alto: int = 1080) -> list[dict]:
        """Material de internet para una pieza, YA bajado: [{"ruta", "tipo", "source_in", "dur_archivo", "vec",
        "motivo", "item"}]. Privada: trozos de video (material_videos.para_armar); pública: imágenes libres."""
        from . import material_por_frases as M
        enc_t, enc_i = self.encoders()
        if self.privada():
            mod = M._videos()
            if mod is not None and hasattr(mod, "para_armar"):
                if self._video is None:
                    self._video = mod.FuentesVideo()
                try:
                    return mod.para_armar(pieza, self._video, enc_texto=enc_t, enc_imagen=enc_i, usados=usados_vecs,
                                          tramos=self._tramos, cancelled=cancelado, alto=alto,
                                          margen=MARGEN_DESCARGA)
                finally:
                    self.fallos[:] = list(dict.fromkeys(self.fallos + list(self._video.fallos)))
                    self.avisos[:] = list(dict.fromkeys(self.avisos + [str(a.get("error") or a)
                                                                       for a in self._video.avisos]))
        fu = M.Fuentes()
        try:
            ranked = M.buscar_para_frase(pieza["frase"], pieza.get("termino"), fu, n=4, cancelled=cancelado,
                                         enc_texto=enc_t, enc_imagen=enc_i)
        finally:
            self.fallos += fu.fallos
        out = []
        for c in ranked:
            if c.get("parecido", 0) < M.PARECIDO_MINIMO or M.repetida(c.get("vec"), list(usados_vecs)):
                continue
            try:
                ruta = M.bajar_elegido(c, fu, pieza.get("termino"), pieza["frase"])
            except Exception as exc:  # noqa: BLE001 - la siguiente
                self.avisos.append(str(exc))
                continue
            out.append({"ruta": ruta, "tipo": "imagen", "source_in": 0.0, "dur_archivo": 0.0, "vec": c.get("vec"),
                        "motivo": "imagen libre", "item": {k: c.get(k) for k in ("title", "creator", "page", "url")}})
            break
        return out

    def duracion(self, ruta: str) -> float:
        from ..core import media as MT
        try:
            return float(MT.probe(ruta).get("duration") or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0


def archivo_listo(ruta: str, intentos: int = 5, espera: float = 0.4, cancelado=None) -> bool:
    """¿Se puede leer? (el antivirus u OneDrive a veces retienen un archivo recién bajado): reintenta unas veces."""
    for k in range(max(1, intentos)):
        try:
            with open(ruta, "rb") as f:
                if f.read(1) or os.path.getsize(ruta) == 0:
                    return os.path.getsize(ruta) > 0
        except OSError:
            pass
        if cancelado and cancelado():
            return False
        if k < intentos - 1:
            time.sleep(espera)
    return False


def avisos_previos(inst: dict, fuentes: Fuentes) -> list[str]:
    """Lo que conviene decir ANTES de empezar (sin internet, sin clips, poco disco)."""
    out = []
    red = fuentes.hay_internet()
    if not red:
        out.append(SIN_INTERNET)
    if not inst["medios"]:
        out.append(SIN_CLIPS_PRIVADA if (red and fuentes.privada()) else SIN_CLIPS_PUBLICA)
    gb = fuentes.disco_libre()
    if red and gb < MIN_LIBRE_GB:
        out.append(POCO_DISCO.format(gb=gb))
    return out


# ================================================================ candidatos por nivel
def _cand(nivel: str, medio: dict | None = None, **k) -> dict:
    c = {"nivel": nivel, "tipo": "video", "source_in": 0.0, "motivo": NOMBRE_NIVEL[nivel]}
    if medio is not None:
        c.update(media_id=medio.get("media_id"), ruta=medio["ruta"], tipo=medio.get("tipo", "video"),
                 dur_archivo=float(medio.get("dur") or 0.0), nombre=medio.get("nombre"))
    c.update(k)
    c["clave"] = c.get("media_id") or ("ruta:" + os.path.normcase(os.path.abspath(c["ruta"])))
    return c


def _exactos(pieza: dict, inst: dict, vectores, q: np.ndarray | None, umbral: float) -> list[dict]:
    out = []
    dur = pieza["t1"] - pieza["t0"]
    # 1) lo que CITA: la frase (4+ palabras seguidas) en la voz de otro archivo
    fw = _palabras_norm(pieza["frase"])
    if len(fw) >= CITA_MIN:
        grams = {tuple(fw[i:i + CITA_MIN]) for i in range(len(fw) - CITA_MIN + 1)}
        for medio in inst["medios"]:
            words = inst["transcripciones"].get(medio["media_id"])
            if not words:
                continue
            ws = [(_palabras_norm(w[2]) or [""])[0] for w in words]
            for i in range(len(ws) - CITA_MIN + 1):
                if tuple(ws[i:i + CITA_MIN]) in grams:
                    out.append(_cand("exacto", medio, source_in=max(0.0, words[i][0] - 0.2), puntos=2.0,
                                     motivo="Lo que citas"))
                    break
    # 2) a quién o qué NOMBRA: el plano donde aparece («Mirar mis clips a fondo», si se hizo)
    if inst.get("entidades") and pieza["frase"]:
        por_id = {m["media_id"]: m for m in inst["medios"]}
        for e in inst["entidades"]:
            if not _dicho(e["nombres"], pieza["frase"]):
                continue
            for mid, t, a, b, sc in e["hits"]:
                medio = por_id.get(mid)
                if medio is None:
                    continue
                src = 0.0 if medio["tipo"] == "imagen" else max(0.0, max(a, t - dur / 3.0))
                out.append(_cand("exacto", medio, source_in=src, puntos=1.5 + min(1.0, sc / 10.0),
                                 motivo=f"Aparece {e['nombres'][0]}"))
    # 3) lo que DESCRIBE: el fotograma que más se parece (CLIP), en sus clips y lo descargado
    if q is not None:
        for medio in inst["medios"]:
            got = vectores(medio)
            if got is None:
                continue
            times, vecs = got
            if vecs.shape[-1] != q.shape[-1]:
                continue
            sims = vecs @ q
            k = int(np.argmax(sims))
            if float(sims[k]) < umbral:
                continue
            src = 0.0 if medio["tipo"] == "imagen" else max(0.0, float(times[k]) - dur / 3.0)
            out.append(_cand("exacto", medio, source_in=src, puntos=float(sims[k]), vec=np.asarray(vecs[k]),
                             motivo="El momento que describes"))
    out.sort(key=lambda c: -c.get("puntos", 0.0))
    return out


def _claves_frase(frase: str, ent: dict | None) -> tuple[set, set]:
    """(nombres compactos del tema y entidades, palabras con contenido) para buscar en los nombres de sus clips."""
    from ..core import keyword_folders as KF
    from . import material_por_frases as M
    nombres = set()
    if ent:
        for n in [ent.get("tema")] + [e.get("nombre") for e in ent.get("entidades") or []]:
            if n:
                nombres.add(KF.compacta(n))
                for v in (next((e.get("variantes") for e in ent.get("entidades") or [] if e.get("nombre") == n),
                               None) or []):
                    nombres.add(KF.compacta(v))
    palabras = set()
    for w in M._palabras(frase):
        if M._con_contenido(w):
            palabras.update(_palabras_norm(w))
    if ent:
        for o in (ent.get("objetos") or []) + (ent.get("acciones") or []):
            palabras.update(_palabras_norm(o.get("es", "")))
            palabras.update(_palabras_norm(o.get("en", "")))
    return {n for n in nombres if n}, {w for w in palabras if len(w) >= 3}


def _por_clave(pieza: dict, inst: dict, ent: dict | None) -> list[dict]:
    from ..core import keyword_folders as KF
    if not pieza["frase"]:
        return []
    nombres, palabras = _claves_frase(pieza["frase"], ent)
    out = []
    for medio in inst["medios"]:
        meta_c = KF.compacta(medio["meta"])
        meta_w = set(_palabras_norm(medio["meta"]))
        pts = 0.0
        if any(n and n in meta_c for n in nombres):
            pts += 2.0
        pts += 0.6 * len(palabras & meta_w)
        if pts >= 0.6:
            out.append(_cand("mis_clips", medio, source_in=min(3.0, 0.1 * float(medio.get("dur") or 0.0)),
                             puntos=pts, motivo="Tus clips: «" + str(medio.get("nombre") or "") + "»"))
    out.sort(key=lambda c: (-c["puntos"], c.get("nombre") or ""))
    return out


def _src_narracion(inst: dict, t: float) -> float | None:
    for d in inst["narracion"]:
        if d["start"] - EPS <= t < d["end"] - EPS:
            return d["source_in"] + (t - d["start"]) * d["speed"]
    return None


def _de_base(pieza: dict, inst: dict) -> list[dict]:
    b = inst.get("base")
    if not b:
        return []
    src = _src_narracion(inst, pieza["t0"])
    if src is None:
        return []
    return [_cand("base", {"media_id": b["media_id"], "ruta": b["ruta"], "dur": b["dur"], "tipo": "video"},
                  source_in=src, exacto_src=True)]


def _de_relleno(inst: dict, estado: dict) -> list[dict]:
    rutas = inst["relleno"]
    if not rutas:
        return []
    k0 = estado.setdefault("relleno_k", 0)
    out = []
    for i in range(len(rutas)):                           # (de archivo en archivo: más variado)
        ruta = rutas[(k0 + i) % len(rutas)]
        mid = inst["rutas_proyecto"].get(os.path.normcase(os.path.abspath(ruta)))
        out.append(_cand("relleno", {"media_id": mid, "ruta": ruta, "dur": 0.0, "tipo": "video"},
                         source_in=estado.get("cursor", {}).get(ruta, 0.0), indice=(k0 + i) % len(rutas)))
    return out


def _cualquiera(inst: dict, estado: dict) -> list[dict]:
    vids = [m for m in inst["medios"] if m["tipo"] == "video"]
    return [_cand("cualquiera", m, source_in=estado.get("cursor", {}).get(m["ruta"], min(3.0, 0.1 * m["dur"])))
            for m in vids]


# ================================================================ resolver: ¿cabe sin repetir? ¿qué trozo?
def _resolver(c: dict, dur: float, inst: dict, fuentes: Fuentes, cancelado=None) -> dict | None:
    """El candidato con su trozo libre («source_in», «dur»), o None si repetiría o no se puede leer. La duración
    puede salir MÁS CORTA que la pieza si el archivo no da para más (el resto lo cubre otro)."""
    tom = inst["tomados"]
    if c["tipo"] == "imagen":
        if tom.usada(c["clave"]) or (c.get("vec") is not None and _img_repetida(c["vec"], inst)):
            return None
        return dict(c, source_in=0.0, dur=min(dur, IMG_MAX))
    da = float(c.get("dur_archivo") or 0.0)
    if da <= 0:
        if not archivo_listo(c["ruta"], cancelado=cancelado):
            fuentes.avisos.append(f"No se pudo leer «{os.path.basename(c['ruta'])}» (¿antivirus u OneDrive?).")
            return None
        da = fuentes.duracion(c["ruta"])
        if da <= 0:
            return None
        c["dur_archivo"] = da
    if not c.get("media_id"):
        tom.registrar(c["clave"], c["ruta"], da, calcular_huella=c["nivel"] in ("relleno", "internet"),
                      cancelled=cancelado)
    need = min(dur, da)
    if need < 0.5 - EPS and dur >= 0.5:
        return None
    src = tom.libre(c["clave"], float(c.get("source_in") or 0.0), need, da)
    if src is None and c.get("exacto_src"):
        return None
    if src is None:                                      # (no cabe entero: el trozo libre más largo que haya)
        for frac in (0.75, 0.5):
            n2 = max(0.5, need * frac)
            src = tom.libre(c["clave"], float(c.get("source_in") or 0.0), n2, da)
            if src is not None:
                need = n2
                break
    if src is None:
        return None
    if c.get("exacto_src") and abs(src - float(c["source_in"])) > 0.05:
        return None                                      # (la imagen de la grabación, solo sincronizada)
    return dict(c, source_in=round(float(src), 4), dur=round(float(need), 4))


def _img_repetida(vec, inst) -> bool:
    from . import material_por_frases as M
    return M.repetida(np.asarray(vec, np.float32), inst["vecs_imagen"])


def _tomar(r: dict, inst: dict, estado: dict):
    inst["tomados"].tomar(r["clave"], r["source_in"], r["dur"], imagen=r["tipo"] == "imagen")
    if r["tipo"] == "imagen" and r.get("vec") is not None:
        inst["vecs_imagen"].append(np.asarray(r["vec"], np.float32))
    if r["tipo"] == "video":
        estado.setdefault("cursor", {})[r["ruta"]] = r["source_in"] + r["dur"] + 0.5
    if r["nivel"] == "relleno":
        estado["relleno_k"] = int(r.get("indice", 0)) + 1


def _imagen_permitida(t0: float, inst: dict, estado: dict) -> bool:
    hechas = list(inst["imagenes_hechas"]) + estado.setdefault("imagenes", [])
    return all(abs(t0 - x) >= IMG_CADA for x in hechas)


# ================================================================ el plan
def _esperar(cancelado, pausado):
    check_cancel(cancelado)
    while pausado is not None and pausado():
        time.sleep(0.25)
        check_cancel(cancelado)


def planear(inst: dict, fuentes: Fuentes | None = None, progreso=None, cancelado=None, pausado=None) -> dict:
    """Elige el material de cada pieza (sin tocar el proyecto; puede ir en otro hilo). Devuelve
    {"piezas": [{"t0","t1","frase","elegido","fondo","alternativas","nivel"}], "faltan": s, "avisos": [...]}."""
    from . import buscador as B
    from . import material_por_frases as M
    fuentes = fuentes or Fuentes()
    ajustes = inst.get("ajustes") or {}
    umbral = float(ajustes.get("umbral_exacto", UMBRAL_EXACTO))
    piezas = [dict(p) for p in inst["piezas"]]
    n = max(1, len(piezas))
    estado: dict = {}
    avisos: list[str] = []
    red = fuentes.hay_internet() if piezas else False
    disco_ok = (fuentes.disco_libre() >= MIN_LIBRE_GB) if red else False
    if red and not disco_ok:
        avisos.append(POCO_DISCO.format(gb=fuentes.disco_libre()))
    entendidas: dict = {}

    def entender(frase: str):
        if frase not in entendidas:
            try:
                entendidas[frase] = B.entender(frase) if frase else None
            except Exception:  # noqa: BLE001
                entendidas[frase] = None
        return entendidas[frase]

    vec_q: dict = {}

    def q_de(frase: str):
        if not frase:
            return None
        if frase not in vec_q:
            ent = entender(frase)
            try:
                vec_q[frase] = fuentes.vector_texto(M.textos_clip(ent) if ent else [frase])
            except Exception:  # noqa: BLE001 - sin CLIP: sin «momento exacto» por lo que describe
                vec_q[frase] = None
        return vec_q[frase]

    memo_v: dict = {}

    def vectores(medio):                                  # (cada clip se lee una vez por pasada)
        if medio["ruta"] not in memo_v:
            try:
                memo_v[medio["ruta"]] = fuentes.vectores(medio)
            except Exception:  # noqa: BLE001
                memo_v[medio["ruta"]] = None
        return memo_v[medio["ruta"]]

    # 1) lo de casa (exacto y mis clips), en orden; lo que no tenga nada, a internet
    locales: list[list[dict]] = []
    for i, pz in enumerate(piezas):
        _esperar(cancelado, pausado)
        if progreso:
            progreso(0.5 * i / n, f"Buscando en tus clips {i + 1}/{n}")
        ent = entender(pz["frase"])
        pz["termino"] = (ent or {}).get("tema")
        locales.append(_exactos(pz, inst, vectores, q_de(pz["frase"]), umbral) + _por_clave(pz, inst, ent))
    # 2) internet: solo las piezas sin nada de casa con algo que buscar, 2–3 a la vez y en orden de aparición
    de_red: dict[int, list] = {}
    pedir = [i for i, pz in enumerate(piezas) if not locales[i] and pz["frase"] and _con_algo(entender(pz["frase"]))]
    if pedir and red and disco_ok:
        de_red = _pedir_internet(piezas, pedir, inst, fuentes, progreso, cancelado, pausado, avisos)
    # 3) elegir, pieza a pieza (sin repetir), con alternativas ya preparadas
    hechas: list[dict] = []
    faltan = 0.0
    k = 0
    while k < len(piezas):
        _esperar(cancelado, pausado)
        pz = piezas[k]
        if progreso:
            progreso(0.75 + 0.25 * k / max(1, len(piezas)), f"Armando {k + 1}/{len(piezas)}")
        dur = pz["t1"] - pz["t0"]
        orden = (locales[k] if k < len(locales) else []) + de_red.get(k, []) + _de_base(pz, inst) + \
            _de_relleno(inst, estado) + _cualquiera(inst, estado)
        elegido, fondo, alts = None, None, []
        vistos = set()
        for c in orden:
            if c["tipo"] == "imagen" and (elegido is not None or not _imagen_permitida(pz["t0"], inst, estado)):
                continue
            if c["clave"] in vistos:
                continue
            r = _resolver(c, dur, inst, fuentes, cancelado)
            if r is None:
                continue
            vistos.add(r["clave"])
            if elegido is None:
                elegido = r
                _tomar(r, inst, estado)
                if r["tipo"] == "imagen":
                    estado.setdefault("imagenes", []).append(pz["t0"])
            elif elegido["tipo"] == "imagen" and fondo is None:
                fondo = r                                 # (el video de debajo de la imagen, que se desenfoca)
                _tomar(r, inst, estado)
            elif len(alts) < ALTERNATIVAS:
                alts.append(r)
            if len(alts) >= ALTERNATIVAS and (elegido["tipo"] != "imagen" or fondo is not None):
                break
        if elegido is None:
            faltan += dur
            hechas.append(dict(pz, elegido=None, fondo=None, alternativas=[], nivel=None))
            k += 1
            continue
        cubre = elegido["dur"] if elegido["tipo"] == "video" else (fondo["dur"] if fondo else dur)
        if elegido["tipo"] == "imagen" and fondo is None:
            cubre = elegido["dur"]
        if cubre < dur - 0.05:                            # el archivo no daba para toda la pieza: el resto, aparte
            resto = dict(pz, t0=round(pz["t0"] + cubre, 4))
            pz = dict(pz, t1=round(pz["t0"] + cubre, 4))
            if elegido["tipo"] == "imagen":
                elegido = dict(elegido, dur=min(elegido["dur"], cubre))
            piezas.insert(k + 1, resto)
            locales.insert(k + 1, locales[k] if k < len(locales) else [])
            de_red = {(j + 1 if j > k else j): v for j, v in de_red.items()}
        alts = [dict(a, dur=min(a["dur"], pz["t1"] - pz["t0"])) for a in alts
                if a["dur"] >= min(pz["t1"] - pz["t0"], 0.5) - 0.05]
        hechas.append(dict(pz, elegido=elegido, fondo=fondo, alternativas=alts, nivel=elegido["nivel"]))
        k += 1
    _limpiar_alternativas(hechas, inst)
    if getattr(fuentes, "bajado", 0) > TOPE_DESCARGAS_MB * 1e6:
        avisos.append(TOPE_BAJADO.format(mb=TOPE_DESCARGAS_MB))
    if progreso:
        progreso(1.0, f"Listo: {len([h for h in hechas if h['elegido']])} piezas")
    return {"piezas": hechas, "faltan": round(faltan, 3), "avisos": avisos + list(dict.fromkeys(fuentes.avisos)),
            "fallos": list(fuentes.fallos), "desde": inst["desde"], "hasta": inst["hasta"],
            "proyecto": inst["proyecto"], "rev": inst.get("rev")}


def _limpiar_alternativas(hechas: list[dict], inst: dict) -> None:
    """Una alternativa resuelta al principio puede pisar lo que otra pieza eligió después: se mueve a otro trozo libre
    del mismo archivo o se quita (las que quedan se pueden poner sin repetir nada)."""
    tom = inst["tomados"]
    for pz in hechas:
        buenas = []
        for a in pz.get("alternativas") or []:
            if a["tipo"] == "imagen":
                if not tom.usada(a["clave"]):
                    buenas.append(a)
                continue
            src = tom.libre(a["clave"], a["source_in"], a["dur"], float(a.get("dur_archivo") or 0.0))
            if src is not None:
                buenas.append(dict(a, source_in=round(float(src), 4)))
        pz["alternativas"] = buenas


def _con_algo(ent: dict | None) -> bool:
    return bool(ent and (ent.get("tema") or ent.get("objetos") or ent.get("acciones")))


def _pedir_internet(piezas, pedir, inst, fuentes, progreso, cancelado, pausado, avisos) -> dict[int, list]:
    """2–3 piezas a la vez, en orden de aparición (la primera que se pide es la primera que se usa). Lo bajado ya
    viene con su huella (material_videos) para no repetir escenas."""
    from concurrent.futures import ThreadPoolExecutor
    out: dict[int, list] = {}
    usados = list(inst["vecs_imagen"])
    lock = threading.Lock()
    hechas = [0]

    def una(i):
        _esperar(cancelado, pausado)
        if getattr(fuentes, "bajado", 0) > TOPE_DESCARGAS_MB * 1e6:
            return i, []
        pz = dict(piezas[i])
        pz["dur"] = pz["t1"] - pz["t0"]
        with lock:
            vs = list(usados)
        try:
            res = fuentes.internet(pz, cancelado, vs, inst.get("alto", 1080)) or []
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - sin conexión, privado, con edad…: la pieza sigue con lo siguiente
            fuentes.fallos.append(str(exc))
            res = []
        cands = []
        for r in res:
            if not r.get("ruta") or not archivo_listo(r["ruta"], cancelado=cancelado):
                continue
            try:
                fuentes.bajado += os.path.getsize(r["ruta"])
            except (OSError, TypeError):
                pass
            mid = inst["rutas_proyecto"].get(os.path.normcase(os.path.abspath(r["ruta"])))
            cands.append(_cand("internet", None, ruta=r["ruta"], media_id=mid, tipo=r.get("tipo", "video"),
                               source_in=float(r.get("source_in") or 0.0),
                               dur_archivo=float(r.get("dur_archivo") or 0.0), vec=r.get("vec"),
                               motivo=r.get("motivo") or NOMBRE_NIVEL["internet"], item=r.get("item")))
            if r.get("vec") is not None:
                with lock:
                    usados.append(np.asarray(r["vec"], np.float32))
        with lock:
            hechas[0] += 1
            if progreso:
                progreso(0.5 + 0.25 * hechas[0] / max(1, len(pedir)), f"Bajando de internet {hechas[0]}/{len(pedir)}")
        return i, cands

    with ThreadPoolExecutor(max_workers=DESCARGAS_A_LA_VEZ) as pool:
        for i, cands in pool.map(una, pedir):
            out[i] = cands
    return out


# ================================================================ colocar (hilo de la interfaz)
class Sesion:
    """Un armado (de uno o varios trozos): todo va en UN solo paso de Ctrl+Z mientras nadie edite entre medias."""

    def __init__(self, ctrl=None):
        self.token = hashlib.sha1(f"{time.time()}-{id(self)}".encode()).hexdigest()[:12]
        self.cmd = None
        self.proyecto = clave_proyecto(ctrl) if ctrl is not None else None
        self.puestos: list[str] = []
        self.editados = 0
        self.deshecho = False

    def sigue_vivo(self, ctrl) -> bool:
        """False si el usuario deshizo el armado (Ctrl+Z) mientras seguía: entonces se para."""
        if self.cmd is None:
            return True
        st = ctrl.undo_stack
        for i in range(st.count()):
            if st.command(i) is self.cmd:
                return i < st.index()
        return False


# alternativas por clip (en esta sesión de Reclaimer; también se guardan junto al estado del armado)
_ALTERNATIVAS: dict[str, dict] = {}


def alternativas_de(clip_id: str) -> list[dict]:
    return list((_ALTERNATIVAS.get(clip_id) or {}).get("alternativas") or [])


def _trozo_para(ctrl, clip_id: str, alt: dict, mid: str | None) -> float | None:
    """El segundo del archivo donde la alternativa entra sin repetir nada de la línea de tiempo (None si no cabe).
    Un archivo que aún no está en Medios no puede repetir nada de la línea de tiempo (salvo por huella: se mira al
    ponerlo)."""
    from ..core import repetidos
    from ..core.model import KIND_VIDEO
    from .broll_selection import find_free
    p = ctrl.project
    c = p.clips.get(clip_id)
    if c is None:
        return None
    if alt.get("tipo") == "imagen":
        if mid and any(o.media_id == mid for o in p.clips.values() if o.id != clip_id):
            return None
        return 0.0
    m = p.media.get(mid) if mid else None
    if m is None:
        da = float(alt.get("dur_archivo") or 0.0)
        return float(alt.get("source_in") or 0.0) if da <= 0 or float(alt.get("source_in") or 0.0) + c.duration <=             da + 0.05 else None
    if m.kind != KIND_VIDEO or not m.duration:
        return None
    usados = repetidos.usados_con_huella(p, m.id, excluir={clip_id})
    return find_free({m.id: usados}, m.id, float(alt.get("source_in") or 0.0), c.duration, float(m.duration))


def _mid_de_ruta(ctrl, alt: dict) -> str | None:
    p = ctrl.project
    if alt.get("media_id") in p.media:
        return alt["media_id"]
    k = os.path.normcase(os.path.abspath(alt.get("ruta") or ""))
    return next((m.id for m in p.media.values() if os.path.normcase(os.path.abspath(m.path)) == k), None)


def alternativas_validas(ctrl, clip_id: str) -> list[tuple[int, dict]]:
    """[(k, alternativa)] de las que HOY se pueden poner en ese clip sin repetir nada (para el menú «Cambiar»)."""
    out = []
    for k, alt in enumerate(alternativas_de(clip_id)):
        if _trozo_para(ctrl, clip_id, alt, _mid_de_ruta(ctrl, alt)) is not None:
            out.append((k, alt))
    return out


def _sin_vec(c: dict | None) -> dict | None:
    if c is None:
        return None
    return {k: v for k, v in c.items() if k not in ("vec",) and not isinstance(v, np.ndarray)}


def _importar(ctrl, rutas: list[str]) -> dict[str, str]:
    rutas = [r for r in dict.fromkeys(rutas) if r]
    if not rutas:
        return {}
    ids = ctrl.import_now(rutas, quiet=True)
    by = {os.path.normcase(os.path.abspath(m.path)): m.id for m in ctrl.project.media.values()}
    del ids
    return {r: by.get(os.path.normcase(os.path.abspath(r))) for r in rutas}


def _dentro(a: float, b: float, huecos: list) -> bool:
    return any(h0 - 0.02 <= a and b <= h1 + 0.02 for h0, h1 in huecos)


def _pista_encima(p, tid: str, a: float, b: float):
    """(dentro del _edit) una pista de video encima de tid libre en [a, b] (o una nueva justo encima)."""
    from ..core.model import TRACK_VIDEO, Track, new_id
    vt = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    i = p.track_index(tid)
    for t in sorted((t for t in vt if p.track_index(t.id) < i and not t.locked), key=lambda t: -p.track_index(t.id)):
        if not any(c.start < b - EPS and c.end > a + EPS for c in p.clips_on(t.id)):
            return t.id
    nt = Track(new_id(), TRACK_VIDEO, f"V{len(vt) + 1}")
    p.tracks.insert(i, nt)
    return nt.id


def colocar(ctrl, plan: dict, sesion: Sesion | None = None) -> dict:
    """Pone el plan en la línea de tiempo, SOLO en lo que sigue vacío (si mientras tanto editaste un tramo, ese se
    salta y se avisa). UN paso de Ctrl+Z (con la misma sesión, los trozos siguientes se juntan en ese paso).
    Devuelve {"puestos": [clip_id], "saltados": n, "faltan": s, "avisos": [...]}."""
    from ..core.controller import MERGE_SESION
    from ..core.model import KIND_IMAGE, KIND_VIDEO, ORIGIN_AI, Clip, new_id
    sesion = sesion or Sesion(ctrl)
    res = {"puestos": [], "saltados": 0, "faltan": plan.get("faltan", 0.0), "avisos": list(plan.get("avisos") or [])}
    if sesion.proyecto and clave_proyecto(ctrl) != sesion.proyecto:
        res["avisos"].append("El armado es de otro proyecto (otra pestaña): espera a que vuelvas a él.")
        res["otro_proyecto"] = True
        return res
    if not sesion.sigue_vivo(ctrl):
        sesion.deshecho = True
        res["deshecho"] = True
        return res
    piezas = [pz for pz in plan.get("piezas") or [] if pz.get("elegido")]
    if not piezas:
        return res
    p = ctrl.project
    rutas = []
    for pz in piezas:
        for c in (pz["elegido"], pz.get("fondo")):
            if c and not (c.get("media_id") and c["media_id"] in p.media):
                rutas.append(c["ruta"])
    ids = _importar(ctrl, rutas)
    tr = pista_destino(p)
    if tr is None:
        res["avisos"].append("Todas las pistas de video están bloqueadas: no puedo poner nada.")
        return res
    tid_base = tr.id
    huecos = huecos_actuales(p, 0.0, None)
    alts_por_clip: dict[str, dict] = {}

    def mid_de(c):
        if c.get("media_id") and c["media_id"] in p.media:
            return c["media_id"]
        return ids.get(c["ruta"])

    cuenta = {"saltados": 0}

    def fn(proj):
        puestos, saltados = [], 0
        for pz in piezas:
            a, b = float(pz["t0"]), float(pz["t1"])
            if not _dentro(a, b, huecos):                 # (lo tocaste mientras se armaba: no se pisa)
                saltados += 1
                continue
            el, fo = pz["elegido"], pz.get("fondo")
            abajo = fo if el["tipo"] == "imagen" and fo else el
            nuevos = []
            mid = mid_de(abajo)
            m = proj.media.get(mid) if mid else None
            if m is None or (m.kind == KIND_VIDEO and not m.duration):
                saltados += 1
                continue
            d = min(b - a, float(abajo["dur"]) if m.kind == KIND_VIDEO else b - a)
            c = Clip(new_id(), m.id, tid_base, a, 0.0 if m.kind == KIND_IMAGE else float(abajo["source_in"]), d,
                     volume=0.0, origin=ORIGIN_AI, note=NOTA, layout=ctrl._auto_layout(proj, m, tid_base))
            proj.clips[c.id] = c
            nuevos.append(c.id)
            if m.kind == KIND_IMAGE:
                ctrl._image_style(proj, c, "auto")
            principal = c.id
            if el["tipo"] == "imagen" and fo:
                mi = proj.media.get(mid_de(el) or "")
                if mi is not None:
                    di = min(float(el["dur"]), d)
                    tid_img = _pista_encima(proj, tid_base, a, a + di)
                    ci = Clip(new_id(), mi.id, tid_img, a, 0.0, di, volume=0.0, origin=ORIGIN_AI, note=NOTA)
                    proj.clips[ci.id] = ci
                    ctrl._image_style(proj, ci, "auto")     # (encima, con sombra; el video de debajo, desenfocado)
                    nuevos.append(ci.id)
            ctrl._tras_colocar(proj, nuevos)              # (📱 vertical: lo horizontal con su fondo desenfocado)
            puestos += nuevos
            alts_por_clip[principal] = {"alternativas": [_sin_vec(x) for x in pz.get("alternativas") or []],
                                        "frase": pz.get("frase", ""), "nivel": pz.get("nivel"),
                                        "elegido": _sin_vec(abajo)}
        cuenta["saltados"] = saltados
        return {"puestos": puestos, "saltados": saltados}

    hecho = ctrl._edit(TITULO_DESHACER, fn, merge_id=MERGE_SESION, tramo=sesion.token)
    res["saltados"] = cuenta["saltados"]
    if isinstance(hecho, dict):
        res["puestos"], res["saltados"] = hecho["puestos"], hecho["saltados"]
        st = ctrl.undo_stack
        if st.index() > 0:
            sesion.cmd = st.command(st.index() - 1)       # (si se juntó con el anterior, es el mismo paso)
        sesion.puestos += hecho["puestos"]
        _ALTERNATIVAS.update(alts_por_clip)
    if res["saltados"]:
        sesion.editados += res["saltados"]
        res["avisos"].append(f"Salté {res['saltados']} tramo(s) que cambiaste mientras armaba (no piso lo tuyo).")
    return res


def armar(ctrl, desde: float = 0.0, hasta: float | None = None, fuentes: Fuentes | None = None, progreso=None,
          cancelado=None, ajustes: dict | None = None, sesion: Sesion | None = None, pausado=None) -> dict:
    """Instantánea + plan + colocar, seguidos en ESTE hilo (pruebas, MCP). El panel lo hace por trozos sin bloquear
    (ui/armar_video.Armador). Devuelve lo de colocar más «plan»."""
    inst = instantanea(ctrl, desde, hasta, ajustes)
    plan = planear(inst, fuentes, progreso, cancelado, pausado)
    res = colocar(ctrl, plan, sesion)
    res["plan"] = plan
    return res


# ================================================================ «Cambiar» (clic derecho en el clip)
def cambiar(ctrl, clip_id: str, k: int) -> str | None:
    """Pone en ese clip la alternativa k (mismo sitio y duración), si no repite nada. Un Ctrl+Z. Devuelve el id del
    clip (el mismo) o None."""
    from ..core.controller import EditError
    from ..core.model import KIND_IMAGE
    info = _ALTERNATIVAS.get(clip_id)
    p = ctrl.project
    c = p.clips.get(clip_id)
    if not info or c is None or not (0 <= k < len(info["alternativas"])):
        return None
    alt = info["alternativas"][k]
    if _trozo_para(ctrl, clip_id, alt, _mid_de_ruta(ctrl, alt)) is None:
        return None
    mid = _mid_de_ruta(ctrl, alt) or _importar(ctrl, [alt["ruta"]]).get(alt["ruta"])
    m = p.media.get(mid) if mid else None
    if m is None:
        return None
    src = _trozo_para(ctrl, clip_id, alt, m.id)           # (ya en Medios: también con su huella)
    if src is None:
        return None
    viejo = info.get("elegido")

    def fn(proj):
        cc = proj.clips.get(clip_id)
        if cc is None:
            raise EditError("Ese clip ya no está.")
        ctrl._check_clip(proj, cc)
        cc.media_id, cc.source_in = m.id, (0.0 if m.kind == KIND_IMAGE else float(src))
        cc.layout = ctrl._auto_layout(proj, m, cc.track_id)
        if m.kind == KIND_IMAGE:
            ctrl._image_style(proj, cc, "auto")
        ctrl._tras_colocar(proj, [cc.id])
    if not ctrl._edit("🎬 Cambiar el material de esta frase", fn):
        return None
    alts = list(info["alternativas"])
    nuevo = alts.pop(k)
    if viejo:
        alts.insert(0, viejo)                             # (lo de antes pasa a ser una alternativa: se puede volver)
    _ALTERNATIVAS[clip_id] = dict(info, alternativas=alts, elegido=dict(nuevo, media_id=m.id, source_in=src))
    return clip_id


def texto_alternativa(alt: dict) -> str:
    """«Tus clips: «Halo partida» · 00:12» para el menú «Cambiar»."""
    nombre = alt.get("nombre") or os.path.basename(alt.get("ruta") or "")
    nivel = NOMBRE_NIVEL.get(alt.get("nivel"), "")
    t = float(alt.get("source_in") or 0.0)
    pos = f" · {int(t // 60):02d}:{int(t % 60):02d}" if alt.get("tipo") == "video" else ""
    return f"{nivel}: «{nombre}»{pos}"


# ================================================================ «Seguir armando» (cerrar a medias y volver)
def _ruta_estado(ctrl) -> str:
    from ..core.paths import app_data_dir
    d = app_data_dir() / "armado"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / (hashlib.sha1(clave_proyecto(ctrl).encode("utf-8")).hexdigest()[:16] + ".json"))


def guardar_estado(ctrl, desde: float, hasta: float | None, hecho_hasta: float, ajustes: dict | None = None,
                   transcripcion_completa: bool = False) -> None:
    datos = {"proyecto": clave_proyecto(ctrl), "desde": desde, "hasta": hasta, "hecho_hasta": round(hecho_hasta, 3),
             "ajustes": {k: v for k, v in (ajustes or {}).items() if isinstance(v, (str, int, float, bool))},
             "transcripcion_completa": bool(transcripcion_completa), "fecha": time.time(),
             "alternativas": {cid: {"alternativas": v.get("alternativas"), "frase": v.get("frase"),
                                    "nivel": v.get("nivel"), "elegido": v.get("elegido")}
                              for cid, v in _ALTERNATIVAS.items() if cid in ctrl.project.clips}}
    tmp = _ruta_estado(ctrl) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, default=str)
        os.replace(tmp, _ruta_estado(ctrl))
    except OSError:
        pass


def pendiente(ctrl) -> dict | None:
    """El armado que quedó a medias en este proyecto (para «Seguir armando»), o None. También recupera las
    alternativas de «Cambiar» de los clips que siguen en la línea de tiempo."""
    try:
        with open(_ruta_estado(ctrl), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("proyecto") != clave_proyecto(ctrl):
        return None
    for cid, v in (d.get("alternativas") or {}).items():
        if cid in ctrl.project.clips and cid not in _ALTERNATIVAS:
            _ALTERNATIVAS[cid] = v
    return d


def borrar_estado(ctrl) -> None:
    try:
        os.remove(_ruta_estado(ctrl))
    except OSError:
        pass
