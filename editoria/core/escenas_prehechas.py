"""
⚡ Escenas prehechas: plantillas de acción listas para usar en 🎬 Escenas («estos dos se disparan», «uno contra un
grupo», «huye y le persiguen», «cara a cara»…). Cada una define sus papeles (A, B o un grupo de N), dónde está cada
uno (posiciones relativas que encajan en horizontal y en vertical: scenes.caja_pos), sus fases con sus tiempos, los
sonidos ✦ de Reclaimer (core/sfx), los temblores de cámara (fase «📳 Sacudida») y los destellos de pantalla (una
imagen blanca que se desvanece). Lo que sale es una escena normal: todo se puede cambiar después. Sin Qt.

  CATALOGO                [{"clave", "nombre", "grupo", "desc", "dur", "fondo", "papeles": [(id, nombre, n|None)]}]
  GRUPOS                  los grupos en el orden del menú
  construir(clave, a, medios, media_de_ruta, vertical, dur=None, n_grupo=None) -> (escena, faltan)
      medios = {"A": media_id | None, "B": …, "G": …}; lo que falte queda con un MARCADOR (una silueta con su letra)
      y se devuelve en «faltan» («A (Tirador)»…). media_de_ruta(ruta, categoria) -> media_id (ctrl.media_for_path);
      None = solo para la vista previa (ids falsos, sin archivos).
  añadir_a(escena, otra, t)  mete una prehecha dentro de una escena ya hecha, desde su segundo t.
  ruta_imagen(nombre)     los PNG propios (marcadores, «VS», «!», blanco del destello), creados la primera vez.
"""
from __future__ import annotations

import copy
import os
import random
import wave

from . import image_anim, scenes, sfx

GRUPOS = ["⚔ Combate", "🏃 Persecución y huida", "💬 Reacción y diálogo", "🎉 Celebración y derrota", "🎤 Presentación"]
SHOT = image_anim.SHOT_EVERY


# ---------------------------------------------------------------- imágenes propias (PIL, sin Qt)
def _carpeta() -> str:
    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "escenas_prehechas")
    os.makedirs(d, exist_ok=True)
    return d


def es_propia(ruta: str) -> bool:
    """¿Es una imagen de las prehechas (marcador, «VS», «!», destello)? (no se enseñan en la lista de Local)."""
    try:
        return os.path.normcase(os.path.dirname(os.path.abspath(ruta))) == os.path.normcase(_carpeta())
    except OSError:
        return False


def _fuente(tam: int):
    from PIL import ImageFont
    for f in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, tam)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:
        return ImageFont.load_default()


COLOR_PAPEL = {"A": (70, 130, 230), "B": (220, 80, 70), "G": (70, 180, 110)}


def ruta_imagen(nombre: str, papel: str = "A") -> str:
    """El PNG de ese accesorio («blanco», «vs», «exclamacion») o del marcador de un papel («marcador»)."""
    from PIL import Image, ImageDraw
    archivo = {"blanco": "Destello blanco.png", "vs": "VS.png", "exclamacion": "Exclamación.png"}.get(
        nombre, f"Falta personaje {papel}.png" if papel != "G" else "Falta grupo.png")
    ruta = os.path.join(_carpeta(), archivo)
    if os.path.isfile(ruta):
        return ruta
    if nombre == "blanco":
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(ruta)
    elif nombre == "vs":
        im = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f = _fuente(300)
        d.text((320, 180), "VS", font=f, anchor="mm", fill=(255, 205, 40, 255), stroke_width=16,
               stroke_fill=(20, 20, 20, 255))
        im.save(ruta)
    elif nombre == "exclamacion":
        im = Image.new("RGBA", (220, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((110, 200), "!", font=_fuente(360), anchor="mm", fill=(255, 70, 50, 255), stroke_width=14,
               stroke_fill=(255, 255, 255, 255))
        im.save(ruta)
    else:                                              # 👤 marcador: silueta con su letra y una interrogación
        col = COLOR_PAPEL.get(papel, (140, 140, 150))
        im = Image.new("RGBA", (300, 500), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        relleno, borde = col + (200,), (255, 255, 255, 230)
        d.ellipse((95, 20, 205, 130), fill=relleno, outline=borde, width=6)
        d.rounded_rectangle((55, 140, 245, 480), radius=60, fill=relleno, outline=borde, width=6)
        letra = "G" if papel == "G" else papel
        d.text((150, 75), "?", font=_fuente(80), anchor="mm", fill=(255, 255, 255, 255))
        d.text((150, 310), letra, font=_fuente(170), anchor="mm", fill=(255, 255, 255, 255), stroke_width=6,
               stroke_fill=(30, 30, 30, 255))
        im.save(ruta)
    return ruta


def _dur_wav(ruta: str) -> float:
    try:
        with wave.open(ruta, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 48000)
    except (OSError, wave.Error, EOFError):
        return 1.0


# ---------------------------------------------------------------- lo que usan las plantillas
class _Ctx:
    def __init__(self, escena: dict, vertical: bool, medios: dict, media_de_ruta, n_grupo: int | None,
                 papeles: list, semilla: int):
        self.e, self.vertical, self.medios, self.mdr = escena, vertical, dict(medios or {}), media_de_ruta
        self.n_grupo = n_grupo
        self.nombres = {p[0]: p[1] for p in papeles}
        self.faltan: list[str] = []
        self._marcadores: dict[str, str] = {}
        self.temblores: list[tuple[float, float]] = []
        self.destellos: list[tuple[float, float]] = []
        self.rnd = random.Random(semilla)

    # ---- medios
    def _id_de(self, ruta: str, categoria: str, falso: str) -> str | None:
        if self.mdr is None:
            return falso
        return self.mdr(ruta, categoria)

    def medio(self, papel: str) -> str:
        mid = self.medios.get(papel)
        if mid:
            return mid
        if papel not in self._marcadores:
            nombre = self.nombres.get(papel, papel)
            self.faltan.append(f"{papel} ({nombre})")
            self._marcadores[papel] = self._id_de(ruta_imagen("marcador", papel), "Escenas", f"~{papel}") or ""
        return self._marcadores[papel]

    # ---- personajes
    def actor(self, papel: str, cx: float, fases: list, inicio: float = 0.0, lado: int = 0, pie: float = 0.88,
              esc: float = 1.0, ancho: float = 1.0, alto: float = 1.0, media: str | None = None, extra=None) -> dict:
        pos = {"cx": round(cx, 4), "pie": round(pie, 4), "esc": round(esc, 4)}
        if ancho != 1.0:
            pos["ancho"] = ancho
        if alto != 1.0:
            pos["alto"] = alto
        a = {"id": scenes._id(), "media_id": media or self.medio(papel), "caja": scenes.caja_pos(pos, self.vertical),
             "lado": lado, "inicio": round(max(0.0, inicio), 3), "fases": fases, "papel": papel, "pos": pos}
        if extra:
            a.update(extra)
        self.e["actores"].append(a)
        return a

    def prop(self, nombre: str, cx: float, pie: float, esc: float, ancho: float, alto: float, fases: list,
             inicio: float, sobre: dict | None = None) -> dict:
        mid = self._id_de(ruta_imagen(nombre), "Escenas", f"~prop:{nombre}")
        a = self.actor("", cx, fases, inicio, 0, pie, esc, ancho, alto, media=mid, extra={"prop": nombre})
        if sobre:
            a["pos"]["sobre"] = dict(sobre)
            a["caja"] = scenes.caja_pos(a["pos"], self.vertical)
        return a

    def n(self, defecto: int) -> int:
        return max(1, min(12, int(self.n_grupo or defecto)))

    def var(self, x: float) -> float:
        """Una pequeña variación (siempre la misma para la misma prehecha)."""
        return self.rnd.uniform(-x, x)

    # ---- sonidos y cámara
    def sonido(self, clave: str, t: float, vol: float = 0.5, dur: float | None = None) -> None:
        if self.mdr is None:
            self.e["sonidos"].append({"id": scenes._id(), "media_id": f"~sfx:{clave}", "t": round(t, 3),
                                      "dur": dur or 0.5, "vol": vol, "sfx": clave})
            return
        ruta = sfx.path_for(clave)
        mid = self.mdr(ruta, "Efectos")
        if mid:
            largo = _dur_wav(ruta)
            s = scenes.nuevo_sonido(self.e, mid, t, min(largo, dur or largo), vol)
            s["sfx"] = clave

    def temblor(self, t: float, dur: float = 0.3) -> None:
        self.temblores.append((t, dur))

    def destello(self, t: float, dur: float = 0.25) -> None:
        self.destellos.append((t, dur))


def F(*eventos, fin: str = "q") -> list[dict]:
    """Las fases de un personaje a partir de sus momentos: (segundo, tipo, anim, dur[, extra]) con tipo e/a/s
    (entrada, acción, salida); los huecos se rellenan con «Quieto»; fin="q" = al final, el «Quieto» elástico."""
    tipos = {"e": "entrada", "a": "accion", "s": "salida"}
    out, cur = [], 0.0
    for ev in sorted(eventos, key=lambda x: x[0]):
        t, tipo, anim, d = ev[:4]
        if t > cur + 0.01:
            out.append({"tipo": "accion", "anim": "ninguna", "dur": round(t - cur, 3)})
        f = {"tipo": tipos[tipo], "anim": anim, "dur": round(d, 3)}
        if len(ev) > 4:
            f.update(ev[4])
        out.append(f)
        cur = max(cur, t) + d
    if fin == "q":
        out.append({"tipo": "accion", "anim": "ninguna", "dur": 0.1, "auto": True})
    return out


def disparos(t0: float, dur: float) -> list[float]:
    """Los segundos en que se ve cada retroceso de una fase «🔫 Disparar» que empieza en t0 (como image_anim.plan)."""
    n = min(image_anim.MAX_SHOTS, max(1, int((dur - 0.1) / SHOT)))
    out = []
    for j in range(n):
        s = 0.08 + j * SHOT
        if s + 0.2 > dur:
            break
        out.append(round(t0 + s + 0.04, 3))
    return out


IMPACTO_ATAQUE = 0.12          # (el golpe de «👊 Atacar» llega a los 0,12 s)


# ---------------------------------------------------------------- ⚔ combate
def _tiroteo(c: _Ctx):
    a_ini, a_dur, b_ini, b_dur = 0.8, 1.3, 1.05, 1.0
    golpe = 2.1
    c.actor("A", 0.25, F((0, "e", "izquierda", 0.5), (a_ini, "a", "disparo", a_dur)), lado=1)
    c.actor("B", 0.75, F((0, "e", "derecha", 0.5), (b_ini, "a", "disparo", b_dur), (golpe, "a", "golpe", 0.45),
                         (golpe + 0.45, "s", "muere", 1.0), fin=""), lado=-1)
    for t in disparos(a_ini, a_dur) + disparos(b_ini, b_dur):
        c.sonido("disparo", t, 0.45, 0.35)
    c.sonido("golpe", golpe, 0.45)


def _duelo(c: _Ctx):
    tiro = 2.0
    imp = disparos(tiro, 0.5)[0]
    c.actor("A", 0.22, F((tiro, "a", "disparo", 0.5)), lado=1)
    c.actor("B", 0.78, F((imp, "a", "golpe", 0.45), (imp + 0.45, "s", "muere", 1.0), fin=""), lado=-1)
    c.sonido("riser", 0.0, 0.3, 1.9)
    c.sonido("disparo", imp, 0.55, 0.6)
    c.destello(imp, 0.25)


def _pelea(c: _Ctx):
    i = IMPACTO_ATAQUE
    c.actor("A", 0.33, F((0, "e", "izquierda", 0.5), (0.8, "a", "ataca", 0.5), (1.6 + i, "a", "golpe", 0.45),
                         (2.4, "a", "ataca", 0.5), (3.1, "a", "ataca", 0.5), (4.0, "a", "celebra", 0.9)), lado=1)
    c.actor("B", 0.67, F((0, "e", "derecha", 0.5), (0.8 + i, "a", "golpe", 0.45), (1.6, "a", "ataca", 0.5),
                         (2.4, "a", "esquiva", 0.6), (3.1 + i, "a", "derribado", 1.0)), lado=-1)
    for t in (0.8 + i, 1.6 + i, 3.1 + i):
        c.sonido("punetazo", t, 0.55)
    c.sonido("whoosh", 2.42, 0.35)
    c.sonido("impacto", 3.1 + i, 0.35)


def _intercambio(c: _Ctx):
    i = IMPACTO_ATAQUE
    ataques_a, ataques_b = (0.6, 1.8, 3.0), (1.2, 2.4)
    ev_a = [(0, "e", "izquierda", 0.4)] + [(t, "a", "ataca", 0.5) for t in ataques_a] + \
           [(t + i, "a", "golpe", 0.35) for t in ataques_b]
    ev_b = [(0, "e", "derecha", 0.4)] + [(t, "a", "ataca", 0.5) for t in ataques_b] + \
           [(t + i, "a", "golpe", 0.35) for t in ataques_a]
    c.actor("A", 0.34, F(*ev_a), lado=1)
    c.actor("B", 0.66, F(*ev_b), lado=-1)
    for t in sorted(ataques_a + ataques_b):
        c.sonido("punetazo", t + i, 0.5)


def _golpe_y_cae(c: _Ctx):
    imp = 0.6 + IMPACTO_ATAQUE
    c.actor("A", 0.37, F((0, "e", "izquierda", 0.45), (0.6, "a", "ataca", 0.5)), lado=1)
    c.actor("B", 0.67, F((imp, "a", "derribado", 1.0)), lado=-1)
    c.sonido("whoosh", 0.0, 0.4)
    c.sonido("punetazo", imp, 0.6)
    c.sonido("impacto", imp + 0.02, 0.4)
    c.destello(imp, 0.2)


def _contra_grupo(c: _Ctx):
    d_ini, d_dur = 1.2, 2.4
    tiros = disparos(d_ini, d_dur)
    c.actor("A", 0.2, F((0, "e", "izquierda", 0.5), (d_ini, "a", "disparo", d_dur)), lado=1)
    n = c.n(3)
    for k in range(n):
        retraso = k * 0.2 + abs(c.var(0.06))
        cx = 0.62 + (0.3 * k / (n - 1) if n > 1 else 0.13) + c.var(0.02)
        hondo = k % 2
        imp = tiros[min(len(tiros) - 1, 1 + 2 * k)] + (0.05 * (k // 4))
        c.actor("G", cx, F((0, "e", "derecha", 0.5), (imp - retraso, "a", "golpe", 0.35),
                           (imp - retraso + 0.35, "s", "muere", 0.9), fin=""), inicio=retraso, lado=-1,
                pie=0.88 - 0.05 * hondo, esc=(0.85 - 0.1 * hondo) * (1 + c.var(0.05)), extra={"grupo": "G"})
    for t in tiros:
        c.sonido("disparo", t, 0.4, 0.3)


def _emboscada(c: _Ctx):
    c.actor("A", 0.42, F((0, "e", "izquierda", 0.6), (0.6, "a", "camina", 1.0), (1.8, "a", "susto", 0.5),
                         (2.3, "a", "tiembla", 1.7), fin=""), lado=1)
    n = c.n(3)
    sitios = [0.1, 0.9, 0.24, 0.78, 0.04, 0.96, 0.33, 0.68]
    for k in range(n):
        cx = sitios[k % len(sitios)] + c.var(0.02)
        hondo = 1 if k >= 2 else 0
        c.actor("G", cx, F((0, "e", "pop", 0.35)), inicio=1.7 + k * 0.08 + abs(c.var(0.03)),
                lado=1 if cx > 0.5 else -1, pie=0.88 - 0.06 * hondo, esc=(0.9 - 0.12 * hondo) * (1 + c.var(0.05)),
                extra={"grupo": "G"})
    c.sonido("pasos", 0.6, 0.35, 1.1)
    c.sonido("susto", 1.72, 0.55)
    c.destello(1.72, 0.2)


def _explota(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "tiembla", 1.2), (1.2, "a", "explota", 0.8), fin=""), esc=1.1)
    c.sonido("riser", 0.0, 0.25, 1.2)
    c.sonido("explosion", 1.2, 0.6)
    c.destello(1.2, 0.35)


# ---------------------------------------------------------------- 🏃 persecución y huida
def _persecucion(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "cruza_corre", 2.4), fin=""), lado=1)
    c.actor("B", 0.5, F((0, "a", "cruza_corre", 2.4), fin=""), inicio=0.7, lado=1)
    c.sonido("pasos", 0.0, 0.4)
    c.sonido("pasos", 0.9, 0.35)
    c.sonido("whoosh", 0.5, 0.3)


def _huida(c: _Ctx):
    c.actor("A", 0.5, F((0, "e", "aparece", 0.3), (1.0, "a", "susto", 0.45), (1.5, "s", "huye", 1.2), fin=""), lado=1)
    c.sonido("susto", 1.0, 0.5)
    c.sonido("pasos", 1.5, 0.4, 1.2)
    c.sonido("whoosh", 1.6, 0.35)


def _carrera(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "cruza_corre", 2.2), fin=""), inicio=0.1, lado=1, pie=0.78, esc=0.85)
    c.actor("B", 0.5, F((0, "a", "cruza_corre", 2.6), fin=""), lado=1, pie=0.95)
    c.sonido("pasos", 0.0, 0.4)
    c.sonido("pasos", 0.3, 0.3)
    c.sonido("whoosh", 1.4, 0.35)


def _persigue_grupo(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "cruza_corre", 2.4), fin=""), lado=1)
    n = c.n(4)
    for k in range(n):
        hondo = k % 2
        c.actor("G", 0.5, F((0, "a", "cruza_corre", 2.6 + c.var(0.2)), fin=""), inicio=0.8 + k * 0.25 + c.var(0.05),
                lado=1, pie=0.88 - 0.06 * hondo + c.var(0.01), esc=(0.9 - 0.12 * hondo) * (1 + c.var(0.05)),
                extra={"grupo": "G"})
    c.sonido("pasos", 0.0, 0.4)
    c.sonido("pasos", 0.9, 0.35)
    c.sonido("pasos", 1.8, 0.3)


# ---------------------------------------------------------------- 💬 reacción y diálogo
def _discuten(c: _Ctx):
    c.actor("A", 0.27, F((0, "e", "izquierda", 0.5), (0.6, "a", "habla", 1.0), (2.8, "a", "habla", 0.7),
                         (4.2, "a", "habla", 0.8)), lado=1)
    c.actor("B", 0.73, F((0, "e", "derecha", 0.5), (1.7, "a", "habla", 1.0), (3.5, "a", "habla", 0.7),
                         (4.2, "a", "habla", 0.8)), lado=-1)


def _sorpresa(c: _Ctx):
    a = c.actor("A", 0.5, F((0.6, "a", "susto", 0.5), (1.1, "a", "tiembla", 1.4), fin=""))
    c.prop("exclamacion", 0.6, 0.0, 0.6, 0.6, 0.7, F((0, "e", "pop", 0.3), (1.3, "s", "desvanece", 0.3), fin=""),
           inicio=0.6, sobre=a["pos"])                 # (el «!» justo encima de su cabeza)
    c.sonido("susto", 0.6, 0.5)


def _aparece_golpe(c: _Ctx):
    c.actor("A", 0.3, F((1.2, "a", "susto", 0.45), (1.65, "a", "retrocede", 1.0)), lado=1)
    c.actor("B", 0.7, F((0, "e", "pop", 0.35)), inicio=1.2, lado=-1, esc=1.1)
    c.sonido("susto", 1.2, 0.5)
    c.sonido("impacto", 1.2, 0.35)
    c.destello(1.2, 0.2)


def _acerca_y_va(c: _Ctx):
    c.actor("A", 0.5, F((0, "e", "izquierda", 1.0), (3.4, "s", "derecha", 1.0), fin=""), lado=1)
    c.sonido("pasos", 0.0, 0.3, 1.0)
    c.sonido("pasos", 3.4, 0.3, 1.0)


# ---------------------------------------------------------------- 🎉 celebración y derrota
def _victoria(c: _Ctx):
    c.actor("A", 0.5, F((0, "e", "pop", 0.4), (0.4, "a", "celebra", 2.1)), esc=1.1)
    c.sonido("victoria", 0.1, 0.5)
    c.sonido("brillo", 0.4, 0.3)
    c.destello(0.0, 0.3)


def _saltan(c: _Ctx):
    n = c.n(3)
    for k in range(n):
        cx = 0.5 if n == 1 else 0.18 + 0.64 * k / (n - 1)
        ret = abs(c.var(0.15))
        c.actor("G", cx + c.var(0.02), F((0, "e", "abajo", 0.5), (0.5, "a", "celebra", 2.8 - ret)), inicio=ret,
                pie=0.88 - 0.04 * (k % 2), esc=(0.9 if n > 2 else 1.0) * (1 + c.var(0.05)), extra={"grupo": "G"})
    c.sonido("victoria", 0.4, 0.5)


def _derrota(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "abatido", 1.4), (1.8, "a", "derribado", 1.0)))
    c.sonido("derrota", 0.2, 0.5)
    c.sonido("golpe", 1.9, 0.4)


def _ganador_perdedor(c: _Ctx):
    c.actor("A", 0.3, F((0, "e", "abajo", 0.5), (0.6, "a", "celebra", 3.0)), lado=1)
    c.actor("B", 0.72, F((0, "e", "abajo", 0.5), (0.7, "a", "abatido", 1.6)), lado=-1)
    c.sonido("victoria", 0.5, 0.45)


# ---------------------------------------------------------------- 🎤 presentación
def _protagonista(c: _Ctx):
    acercar = {"mano": True, "kf": [{"t": 0.0, "dx": 0.0, "dy": 0.0, "s": 1.0, "i": "smooth"},
                                    {"t": 1.0, "dx": 0.0, "dy": -0.01, "s": 1.12, "i": "smooth"}]}
    c.actor("A", 0.5, F((0, "e", "abajo", 0.8), (0.8, "a", "propia", 3.2, acercar)), esc=1.1)
    c.sonido("whoosh", 0.0, 0.45)
    c.sonido("brillo", 0.75, 0.3)


def _impacto(c: _Ctx):
    llega = 0.2 + 0.6 * 0.7
    c.actor("A", 0.5, F((0, "e", "cae", 0.6)), inicio=0.2, esc=1.1)
    c.sonido("swoosh_grave", 0.0, 0.4, 0.62)
    c.sonido("impacto", llega, 0.55)
    c.destello(llega, 0.25)


def _cara_a_cara(c: _Ctx):
    c.actor("A", 0.25, F((0, "e", "izquierda", 0.45)), lado=1)
    c.actor("B", 0.75, F((0, "e", "derecha", 0.45)), lado=-1)
    c.prop("vs", 0.5, 0.72, 0.85, 1.3, 0.55, F((0, "e", "pop", 0.35)), inicio=0.6)
    c.sonido("whoosh", 0.0, 0.4)
    c.sonido("impacto", 0.6, 0.5)
    c.destello(0.6, 0.25)
    c.temblor(0.62, 0.3)


def _presenta_grupo(c: _Ctx):
    n = c.n(4)
    for k in range(n):
        cx = 0.5 if n == 1 else 0.14 + 0.72 * k / (n - 1)
        c.actor("G", cx, F((0, "e", "pop", 0.35)), inicio=0.2 + k * 0.45, pie=0.88 - 0.03 * (k % 2),
                esc=(0.85 if n > 3 else 1.0) * (1 + c.var(0.04)), extra={"grupo": "G"})
        c.sonido("clic", 0.2 + k * 0.45, 0.5)


def _vehiculo(c: _Ctx):
    c.actor("A", 0.5, F((0, "a", "frena", 1.2)), lado=1, esc=1.0, ancho=1.7)
    c.sonido("whoosh_largo", 0.0, 0.45)


# ---------------------------------------------------------------- el catálogo
AB = [("A", "Personaje A", None), ("B", "Personaje B", None)]
CATALOGO = [
    # ⚔ Combate
    dict(clave="tiroteo", nombre="🔫 Se disparan", grupo=GRUPOS[0], dur=4.5, fondo="blur", fn=_tiroteo,
         papeles=[("A", "Tirador", None), ("B", "Rival", None)],
         desc="Uno a cada lado, entran y se disparan; al de la derecha le alcanzan y cae."),
    dict(clave="duelo", nombre="🤠 Duelo: quién dispara primero", grupo=GRUPOS[0], dur=4.0, fondo="dark", fn=_duelo,
         papeles=[("A", "El rápido", None), ("B", "El que cae", None)],
         desc="Tensión quietos, un solo disparo con destello y el otro cae."),
    dict(clave="pelea", nombre="👊 Pelea cuerpo a cuerpo", grupo=GRUPOS[0], dur=5.0, fondo="blur", fn=_pelea,
         papeles=[("A", "Gana", None), ("B", "Pierde", None)],
         desc="Golpe, respuesta, esquiva y el golpe final: uno cae al suelo y el otro lo celebra."),
    dict(clave="intercambio", nombre="💥 Intercambio de golpes", grupo=GRUPOS[0], dur=4.0, fondo="blur",
         fn=_intercambio, papeles=AB, desc="Se golpean por turnos, sin ganador (los dos siguen en pie)."),
    dict(clave="golpe_y_cae", nombre="💫 Un golpe y cae", grupo=GRUPOS[0], dur=3.5, fondo="blur", fn=_golpe_y_cae,
         papeles=[("A", "Golpea", None), ("B", "Cae", None)],
         desc="Uno llega corriendo, un solo golpe con destello y el otro cae al suelo y se queda."),
    dict(clave="contra_grupo", nombre="🛡 Uno contra un grupo", grupo=GRUPOS[0], dur=5.0, fondo="blur",
         fn=_contra_grupo, papeles=[("A", "Protagonista", None), ("G", "Grupo", 3)],
         desc="El protagonista dispara a un grupo que entra por la derecha; caen uno detrás de otro."),
    dict(clave="emboscada", nombre="🎯 Emboscada", grupo=GRUPOS[0], dur=4.0, fondo="dark", fn=_emboscada,
         papeles=[("A", "Protagonista", None), ("G", "Grupo", 3)],
         desc="Camina tranquilo y de golpe le rodean por los dos lados; se asusta y tiembla."),
    dict(clave="explota", nombre="💥 Algo explota", grupo=GRUPOS[0], dur=3.0, fondo="blur", fn=_explota,
         papeles=[("A", "Objeto o vehículo", None)],
         desc="Tiembla, explota con destello de pantalla y desaparece."),
    # 🏃 Persecución y huida
    dict(clave="persecucion", nombre="🏃 Huye y le persiguen", grupo=GRUPOS[1], dur=3.5, fondo="blur",
         fn=_persecucion, papeles=[("A", "Huye", None), ("B", "Persigue", None)],
         desc="Cruzan la pantalla corriendo, uno detrás de otro."),
    dict(clave="huida", nombre="💨 Escapa por un lado", grupo=GRUPOS[1], dur=3.0, fondo="blur", fn=_huida,
         papeles=[("A", "Huye", None)], desc="Se asusta, se da la vuelta y sale corriendo."),
    dict(clave="carrera", nombre="🏁 Carrera", grupo=GRUPOS[1], dur=3.5, fondo="blur", fn=_carrera,
         papeles=[("A", "Al fondo", None), ("B", "Delante", None)],
         desc="Dos cruzan corriendo a la vez, uno más lejos que el otro."),
    dict(clave="persigue_grupo", nombre="🧟 Le persigue un grupo", grupo=GRUPOS[1], dur=4.5, fondo="blur",
         fn=_persigue_grupo, papeles=[("A", "Huye", None), ("G", "Grupo", 4)],
         desc="Cruza corriendo y detrás va un montón (el mismo PNG repetido, con tamaños y tiempos distintos)."),
    dict(clave="vehiculo", nombre="🚗 Llega un vehículo y frena", grupo=GRUPOS[1], dur=3.0, fondo="blur",
         fn=_vehiculo, papeles=[("A", "Vehículo", None)], desc="Entra deprisa por un lado y frena en el centro."),
    # 💬 Reacción y diálogo
    dict(clave="discuten", nombre="💬 Dos discuten", grupo=GRUPOS[2], dur=5.0, fondo="blur", fn=_discuten,
         papeles=AB, desc="Hablan por turnos, cada vez más rápido, y al final a la vez."),
    dict(clave="sorpresa", nombre="😱 Sorpresa / susto", grupo=GRUPOS[2], dur=2.5, fondo="blur", fn=_sorpresa,
         papeles=[("A", "Se asusta", None)], desc="Se sobresalta con un «!» encima de la cabeza y se queda temblando."),
    dict(clave="aparece_golpe", nombre="👻 Aparece de golpe", grupo=GRUPOS[2], dur=3.5, fondo="dark",
         fn=_aparece_golpe, papeles=[("A", "Se asusta", None), ("B", "Aparece", None)],
         desc="Algo aparece de golpe con destello; el otro se asusta y retrocede."),
    dict(clave="acerca_y_va", nombre="🚶 Se acerca y se va", grupo=GRUPOS[2], dur=4.5, fondo="blur",
         fn=_acerca_y_va, papeles=[("A", "Personaje", None)],
         desc="Entra por la izquierda, se queda un momento y se va por la derecha."),
    # 🎉 Celebración y derrota
    dict(clave="victoria", nombre="🏆 Victoria", grupo=GRUPOS[3], dur=3.5, fondo="blur", fn=_victoria,
         papeles=[("A", "Ganador", None)], desc="Aparece de golpe con destello y salta de alegría con fanfarria."),
    dict(clave="saltan", nombre="🎉 Saltan de alegría", grupo=GRUPOS[3], dur=3.5, fondo="blur", fn=_saltan,
         papeles=[("G", "Grupo", 3)], desc="Uno o varios suben desde abajo y saltan de alegría (a destiempo)."),
    dict(clave="derrota", nombre="😞 Cae derrotado", grupo=GRUPOS[3], dur=4.0, fondo="dark", fn=_derrota,
         papeles=[("A", "Derrotado", None)], desc="Se hunde abatido con el trombón triste y cae al suelo."),
    dict(clave="ganador_perdedor", nombre="🥇 Ganador y perdedor", grupo=GRUPOS[3], dur=4.0, fondo="blur",
         fn=_ganador_perdedor, papeles=[("A", "Gana", None), ("B", "Pierde", None)],
         desc="Uno lo celebra saltando mientras el otro se hunde."),
    # 🎤 Presentación
    dict(clave="protagonista", nombre="⭐ Entra el protagonista", grupo=GRUPOS[4], dur=4.0, fondo="blur",
         fn=_protagonista, papeles=[("A", "Protagonista", None)],
         desc="Sube desde abajo y la cámara se le acerca despacio (claves a mano: puedes retocarlas)."),
    dict(clave="impacto", nombre="💥 Aparece con impacto", grupo=GRUPOS[4], dur=3.0, fondo="blur", fn=_impacto,
         papeles=[("A", "Personaje", None)], desc="Cae desde arriba, aterriza con golpe grave y destello."),
    dict(clave="cara_a_cara", nombre="🆚 Cara a cara", grupo=GRUPOS[4], dur=4.0, fondo="dark", fn=_cara_a_cara,
         papeles=[("A", "Rival A", None), ("B", "Rival B", None)],
         desc="Los dos rivales entran por los lados y aparece un «VS» con destello y temblor."),
    dict(clave="presenta_grupo", nombre="👥 Presentar un grupo", grupo=GRUPOS[4], dur=4.0, fondo="blur",
         fn=_presenta_grupo, papeles=[("G", "Grupo", 4)], desc="Aparecen de uno en uno, de izquierda a derecha."),
]
POR_CLAVE = {t["clave"]: t for t in CATALOGO}


def resumen(t: dict) -> str:
    """El texto del tooltip: qué hace, sus papeles, cuánto dura y qué suena."""
    pap = ", ".join(f"{p[0]} = {p[1]}" + (f" (×{p[2]})" if p[2] else "") for p in t["papeles"])
    fondo = dict(scenes.FONDOS).get(t["fondo"], t["fondo"])
    muestra = construir(t["clave"], 0.0, {}, None, False)[0]
    sonidos = sorted({sfx.CATALOG[s["sfx"]][0] for s in muestra["sonidos"] if s.get("sfx") in sfx.CATALOG})
    return (f"{t['desc']}\nPapeles: {pap}\nDura {t['dur']:g} s (se estira al tramo) · fondo {fondo.lower()}" +
            (f"\nSonidos: {', '.join(sonidos)}" if sonidos else ""))


def construir(clave: str, a: float, medios: dict, media_de_ruta, vertical: bool, dur: float | None = None,
              n_grupo: int | None = None) -> tuple[dict, list[str]]:
    """La escena de esa prehecha empezando en «a» (estirada a «dur» si se da). Devuelve (escena, papeles que faltan)."""
    t = POR_CLAVE[clave]
    nombre = t["nombre"].split(" ", 1)[1] if " " in t["nombre"] else t["nombre"]
    e = scenes.nueva(a, a + float(t["dur"]), nombre)
    e["fondo"] = t["fondo"]
    e["prehecha"] = clave
    c = _Ctx(e, vertical, medios, media_de_ruta, n_grupo, t["papeles"], sum(map(ord, clave)))
    t["fn"](c)
    for tt, d in c.temblores:
        scenes.temblor_camara(e, tt, d)
    if c.destellos:
        blanco = c._id_de(ruta_imagen("blanco"), "Escenas", "~blanco")
        for tt, d in c.destellos:
            if blanco:
                scenes.nuevo_destello(e, blanco, tt, d)
    scenes.encajar(e)
    if dur is not None and abs(float(dur) - scenes.largo(e)) > 1e-3:
        scenes.estirar(e, dur)
    return e, c.faltan


def añadir_a(escena: dict, otra: dict, t: float) -> None:
    """Mete lo de «otra» (personajes y sonidos, con ids nuevos) en la escena, empezando en su segundo t; si no cabe,
    la escena se alarga lo justo."""
    otra = scenes.otra_copia(otra)
    fin = t + scenes.largo(otra)
    if fin > scenes.largo(escena):
        escena["b"] = round(float(escena["a"]) + fin, 3)
    for act in otra["actores"]:
        act["inicio"] = round(float(act.get("inicio", 0.0)) + t, 3)
        auto = next((f for f in act["fases"] if f.get("auto")), None)
        if auto is not None:                            # (lo elástico de la prehecha no se estira a toda la escena)
            auto.pop("auto", None)
            auto["dur"] = round(max(0.1, scenes.largo(otra) - float(act["inicio"]) + t -
                                    sum(float(f["dur"]) for f in act["fases"] if f is not auto)), 3)
        escena["actores"].append(act)
    for s in otra["sonidos"]:
        s["t"] = round(float(s["t"]) + t, 3)
        escena["sonidos"].append(s)
    destellos = [a for a in escena["actores"] if a.get("efecto") == "destello"]
    escena["actores"] = [a for a in escena["actores"] if a.get("efecto") != "destello"] + destellos
    scenes.encajar(escena)


def papeles_de(clave: str, n_grupo: int | None = None) -> list[tuple[str, str, int | None]]:
    return copy.deepcopy(POR_CLAVE[clave]["papeles"])
