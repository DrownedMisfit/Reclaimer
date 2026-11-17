"""
🎞 Animaciones sencillas para imágenes (un personaje que dispara, otro que muere, algo que entra deslizándose…).

Son movimientos pequeños hechos con lo que Reclaimer ya sabe mover: fotogramas clave de posición y tamaño
(layout_kf, con sus curvas), opacidad (op_kf) y el temblor de efectos (fx["shake"]). Por eso se ven igual en el
visor y al exportar, y se pueden retocar a mano después. Sin Qt.

  ANIMS                 [(clave, nombre, descripción)] en el orden del menú
  plan(clave, caja, dur, lado) -> {"layout", "layout_kf", "op_kf", "fx"}   (segundos desde el inicio del clip)
  elegir(texto) -> clave | None    según lo que dices («dispara» → disparar, «muere» → morir, «llega» → entrar…)
  lado: +1 = el personaje mira a la DERECHA (el retroceso lo empuja a la izquierda), -1 = a la izquierda,
        0 = automático (según en qué mitad de la pantalla está: mira hacia el centro).
"""
from __future__ import annotations

import re
import unicodedata

ANIMS = [
    ("ninguna", "Quieta", "Sin movimiento."),
    ("disparo", "🔫 Disparar", "Retroceso pequeño en cada disparo (unos 3 por segundo)."),
    ("muere", "💀 Morir", "Recibe el impacto, cae hacia abajo y desaparece."),
    ("golpe", "💥 Recibir un golpe", "Sacudida hacia atrás y temblor que se apaga."),
    ("salta", "⤴ Saltar", "Da un par de botes."),
    ("entra", "⇥ Entrar deslizando", "Llega desde fuera de la pantalla (por su espalda) y se queda."),
    ("sale", "⇤ Salir deslizando", "Se queda y al final se va por delante, fuera de la pantalla."),
    ("cruza", "⇆ Cruzar la pantalla", "Pasa de un lado a otro a velocidad fija."),
    ("acerca", "🔍 Acercarse", "Se agranda despacio (un 12 %), como si la cámara se acercara."),
    ("tiembla", "〰 Temblar", "Tiembla todo el rato (miedo, frío, terremoto)."),
]
NAMES = {k: n for k, n, _d in ANIMS}
DESCS = {k: d for k, _n, d in ANIMS}

# Palabras que eligen la animación (sin tildes, en minúsculas). Se mira la frase alrededor de la palabra clave.
PALABRAS = {
    "disparo": {"dispara", "disparan", "disparo", "disparos", "disparar", "disparando", "disparo", "dispare",
                "disparaba", "balazo", "balazos", "balas", "tiro", "tiros", "tirotea", "tiroteo", "fuego",
                "ametralla", "ametralladora", "rafaga", "francotirador", "escopetazo", "dispararle"},
    "muere": {"muere", "mueren", "murio", "murieron", "morir", "muerto", "muertos", "muerte", "mata", "matan",
              "mato", "mataron", "matar", "asesina", "asesinado", "elimina", "eliminado", "derrota", "derrotado",
              "cae", "cayo", "caen", "fallece", "revienta", "liquida"},
    "golpe": {"golpe", "golpea", "golpean", "golpes", "pega", "pegan", "impacto", "herido", "hiere", "dano",
              "recibe", "sacude", "explota", "explosion", "patada", "punetazo", "choca", "choque"},
    "salta": {"salta", "saltan", "salto", "saltar", "brinca", "brinco", "rebota", "celebra", "festeja"},
    "entra": {"llega", "llegan", "llego", "aparece", "aparecen", "aparecio", "entra", "entran", "viene", "vienen",
              "presenta", "debuta", "regresa", "vuelve", "nuevo", "nueva"},
    "sale": {"huye", "huyen", "escapa", "escapan", "sale", "salen", "desaparece", "abandona", "retira", "marcha"},
    "cruza": {"corre", "corren", "cruza", "pasa", "vuela", "persigue", "persecucion", "conduce", "maneja",
              "acelera", "carrera", "atraviesa"},
    "acerca": {"mira", "observa", "fijense", "detalle", "detalles", "cara", "rostro", "atentos", "atencion"},
    "tiembla": {"tiembla", "temblor", "miedo", "asustado", "terror", "panico", "nervioso", "terremoto", "frio"},
}
FRASES = {"se va": "sale", "se van": "sale", "se fue": "sale", "se acerca": "entra", "le dispara": "disparo",
          "abre fuego": "disparo", "lo mata": "muere", "la mata": "muere", "los mata": "muere"}
# Si en la misma frase hay varias, gana la más «fuerte» (morir pesa más que disparar, que pesa más que entrar…)
PRIORIDAD = ["muere", "disparo", "golpe", "salta", "tiembla", "cruza", "sale", "entra", "acerca"]

KICK = 0.035        # retroceso de un disparo: fracción del ancho de la imagen
SHOT_EVERY = 0.32   # segundos entre disparos
MAX_SHOTS = 10      # una ráfaga de ~3 s; después se queda quieto (y la expresión de FFmpeg no crece sin fin)
SLIDE = 0.45        # segundos que tarda en entrar o salir
SHAKE_AMP = 0.012   # temblor (fracción de la pantalla)


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def elegir(texto: str) -> str | None:
    """La animación que pide lo que dices (None = nada claro)."""
    t = _sin_tildes(texto or "")
    halladas = {k for f, k in FRASES.items() if re.search(rf"\b{re.escape(f)}\b", t)}
    palabras = set(re.findall(r"[a-zñ]+", t))
    for k, ws in PALABRAS.items():
        if palabras & ws:
            halladas.add(k)
    return next((k for k in PRIORIDAD if k in halladas), None)


def _r(v: float) -> float:
    return round(float(v), 4)


def _k(t: float, box: dict, dx: float = 0.0, dy: float = 0.0, s: float = 1.0, i: str | None = None) -> dict:
    """Clave: la caja movida (dx, dy en fracción de pantalla) y escalada desde su centro (s)."""
    w, h = box["w"] * s, box["h"] * s
    k = {"t": _r(max(0.0, t)), "x": _r(box["x"] + (box["w"] - w) / 2 + dx), "y": _r(box["y"] + (box["h"] - h) / 2 + dy),
         "w": _r(w), "h": _r(h)}
    if i:
        k["i"] = i
    return k


def _limpiar(kf: list[dict], dur: float) -> list[dict]:
    """Ordenadas, dentro del clip y sin dos claves en el mismo instante (gana la última)."""
    por_t: dict[float, dict] = {}
    for k in kf:
        if -1e-6 <= k["t"] <= dur + 1e-6:
            por_t[round(min(max(k["t"], 0.0), dur), 3)] = dict(k, t=round(min(max(k["t"], 0.0), dur), 3))
    return [por_t[t] for t in sorted(por_t)]


def plan_propia(caja: dict, dur: float, kf: list) -> dict:
    """🎥 Movimiento propio: las posiciones grabadas (t de 0 a 1 de la fase, dx/dy en fracción de pantalla respecto a
    la caja), con curvas lineales entre muestras (así sigue la mano)."""
    dur = max(0.05, float(dur))
    box = {k: float(caja.get(k, d)) for k, d in (("x", 0.25), ("y", 0.15), ("w", 0.5), ("h", 0.7))}
    layout = dict(caja)
    layout.update({k: _r(v) for k, v in box.items()})
    layout["bg"] = "none"
    pts = sorted((dict(p) for p in kf if isinstance(p, dict)), key=lambda p: float(p.get("t", 0)))
    if not pts:
        return {"layout": layout, "layout_kf": [], "op_kf": [], "fx": {}}
    keys = []
    for p in pts:                                      # (◆ a mano: cada clave con su escala y la curva de su tramo)
        k = _k(float(p.get("t", 0)) * dur, box, float(p.get("dx", 0)), float(p.get("dy", 0)),
               s=max(0.05, float(p.get("s", 1.0) or 1.0)), i=_curva(p.get("i", "linear")))
        keys.append(k)
    return {"layout": layout, "layout_kf": _limpiar(keys, dur), "op_kf": [], "fx": {}}


# ◆ Curvas de las claves a mano (las mismas de transform.CURVES; «smooth» = suave, que allí es None)
CURVAS_CLAVE = [("smooth", "Suave (entra y sale suave)"), ("linear", "Lineal (velocidad fija)"),
                ("in", "Entrar suave (acelera)"), ("out", "Salir suave (frena al llegar)"),
                ("bounce", "Rebote (se pasa un poco y vuelve)"), ("hold", "Mantener (salta en la siguiente)")]


def _curva(i):
    return None if i in (None, "smooth", "") else str(i)


def simplificar_trazo(muestras: list[tuple[float, float, float]], dur: float, paso: float = 0.08,
                      tol: float = 0.004) -> list[dict]:
    """Las muestras del ratón [(t, dx, dy)] → claves [{"t": 0–1, "dx", "dy"}]: como mucho una cada «paso» segundos y
    solo si se movió (así la expresión de FFmpeg no crece sin fin y el trazo se ve igual)."""
    if not muestras or dur <= 0:
        return []
    out = [muestras[0]]
    for m in muestras[1:-1]:
        u = out[-1]
        if m[0] - u[0] >= paso and (abs(m[1] - u[1]) > tol or abs(m[2] - u[2]) > tol):
            out.append(m)
    if len(muestras) > 1:
        out.append(muestras[-1])
    t0 = muestras[0][0]
    return [{"t": round(min(1.0, max(0.0, (t - t0) / dur)), 4), "dx": round(dx, 4), "dy": round(dy, 4)}
            for t, dx, dy in out]


def lado_de(caja: dict, lado: int = 0) -> int:
    """Hacia dónde mira: el pedido (+1 / -1) o, con 0, el automático: si está en la mitad izquierda de la pantalla
    mira a la derecha (hacia el centro), y al revés."""
    if lado:
        return -1 if lado < 0 else 1
    centro = float(caja.get("x", 0.25)) + float(caja.get("w", 0.5)) / 2
    return 1 if centro <= 0.5 else -1


def plan(clave: str, caja: dict, dur: float, lado: int = 0) -> dict:
    """Lo que cambia una animación en el clip. caja = dónde está la imagen (x, y, w, h en fracciones de pantalla,
    con «fit», «rot»…). Las claves van en segundos desde el inicio del clip."""
    dur = max(0.3, float(dur))
    box = {k: float(caja.get(k, d)) for k, d in (("x", 0.25), ("y", 0.15), ("w", 0.5), ("h", 0.7))}
    layout = dict(caja)
    layout.update({k: _r(v) for k, v in box.items()})
    lado = lado_de(box, lado)
    atras = -lado                                  # hacia la espalda del personaje
    kf: list[dict] = []
    op: list[dict] = []
    fx: dict = {}
    if clave == "disparo":
        n = min(MAX_SHOTS, max(1, int((dur - 0.1) / SHOT_EVERY)))
        dx = atras * KICK * box["w"]
        kf.append(_k(0.0, box))
        for j in range(n):
            t0 = 0.08 + j * SHOT_EVERY
            if t0 + 0.2 > dur:
                break
            kf += [_k(t0, box, i="linear"), _k(t0 + 0.04, box, dx, -0.004, i="out"), _k(t0 + 0.2, box)]
    elif clave == "muere":
        golpe = min(0.12, dur * 0.3)
        caida = min(dur * 0.8, max(golpe + 0.25, dur * 0.35))
        kf = [_k(0.0, box, i="out"), _k(golpe, box, atras * 0.06 * box["w"], -0.02 * box["h"]),
              _k(caida, box, atras * 0.07 * box["w"], -0.02 * box["h"], i="in"),
              _k(dur, box, atras * 0.09 * box["w"], 0.55 * box["h"])]
        op = [{"t": 0.0, "v": 1.0}, {"t": _r(caida + (dur - caida) * 0.3), "v": 1.0}, {"t": _r(dur), "v": 0.0}]
        fx = {"shake": round(min(0.35, dur * 0.3), 3), "shake_amp": SHAKE_AMP}
    elif clave == "golpe":
        kf = [_k(0.0, box, i="out"), _k(0.08, box, atras * 0.05 * box["w"]), _k(min(0.45, dur), box)]
        fx = {"shake": round(min(0.5, dur), 3), "shake_amp": SHAKE_AMP * 1.4}
    elif clave == "salta":
        alto = 0.12 * box["h"]
        kf = [_k(0.0, box, i="out")]
        bote = min(0.5, dur)                           # (un clip cortito: un solo bote, más rápido)
        t = 0.0
        for j in range(2):
            if t + bote > dur + 1e-6:
                break
            kf += [_k(t + bote * 0.44, box, 0.0, -alto * (1 - 0.35 * j), i="in"), _k(t + bote * 0.88, box, i="out")]
            t += bote
    elif clave == "entra":
        fuera = (box["x"] + box["w"]) if atras < 0 else (1.0 - box["x"])   # lo que hay que mover para esconderla
        kf = [_k(0.0, box, atras * fuera, i="out"), _k(min(SLIDE, dur * 0.5), box)]
    elif clave == "sale":
        fuera = (1.0 - box["x"]) if lado > 0 else (box["x"] + box["w"])
        t1 = max(0.0, dur - min(SLIDE, dur * 0.5))
        kf = [_k(0.0, box), _k(t1, box, i="in"), _k(dur, box, lado * fuera)]
    elif clave == "cruza":
        desde = -(box["x"] + box["w"]) if lado > 0 else (1.0 - box["x"])
        hasta = (1.0 - box["x"]) if lado > 0 else -(box["x"] + box["w"])
        kf = [_k(0.0, box, desde, i="linear"), _k(dur, box, hasta)]
    elif clave == "acerca":
        kf = [_k(0.0, box, i="linear"), _k(dur, box, s=1.12)]
    elif clave == "tiembla":
        fx = {"shake": round(dur, 3), "shake_amp": SHAKE_AMP}
    elif clave in ("camina", "corre"):
        # avanza hacia donde mira, con un bote suave a cada paso
        largo_paso, alto, cada = (0.18, 0.025, 0.36) if clave == "camina" else (0.45, 0.05, 0.22)
        avance = lado * largo_paso
        n = max(1, int(dur / cada))
        kf = [_k(0.0, box, i="out")]
        for j in range(n):
            t1, t2 = (j + 0.5) * cada, (j + 1) * cada
            kf += [_k(min(dur, t1), box, avance * t1 / dur, -alto * box["h"], i="in"),
                   _k(min(dur, t2), box, avance * t2 / dur, 0.0, i="out")]
        kf.append(_k(dur, box, avance))
    elif clave == "agacha":
        bajo = 0.18 * box["h"]                         # (se encoge desde los pies: baja la cabeza)
        b2 = dict(box, y=box["y"] + bajo, h=box["h"] - bajo)
        kf = [_k(0.0, box, i="out"), _k(min(0.25, dur * 0.3), b2), _k(max(0.0, dur - 0.25), b2, i="in"), _k(dur, box)]
    elif clave == "conduce":
        desde = -(box["x"] + box["w"]) if lado > 0 else (1.0 - box["x"])
        hasta = (1.0 - box["x"]) if lado > 0 else -(box["x"] + box["w"])
        kf = [_k(0.0, box, desde, i="linear"), _k(dur, box, hasta)]
        fx = {"shake": round(dur, 3), "shake_amp": SHAKE_AMP * 0.35}   # (el motor vibra un poco)
    elif clave == "frena":
        fuera = (box["x"] + box["w"]) if atras < 0 else (1.0 - box["x"])
        llega = min(0.7, dur * 0.6)
        kf = [_k(0.0, box, atras * fuera, i="bounce"), _k(llega, box)]   # (se pasa un pelín y vuelve: el frenazo)
        fx = {"shake": round(min(0.3, dur), 3), "shake_amp": SHAKE_AMP * 0.6}
    elif clave == "flota":
        alto = 0.04
        kf = [_k(0.0, box)]
        t, arriba = 0.0, True
        while t + 0.6 <= dur + 1e-6:
            t += 0.6
            kf.append(_k(min(t, dur), box, 0.0, -alto if arriba else 0.0))
            arriba = not arriba
    elif clave == "explota":
        kf = [_k(0.0, box, i="out"), _k(min(0.15, dur * 0.3), box, s=1.18), _k(dur, box, s=1.3)]
        op = [{"t": 0.0, "v": 1.0}, {"t": _r(min(0.15, dur * 0.3)), "v": 1.0}, {"t": _r(min(dur, 0.6)), "v": 0.0}]
        fx = {"shake": round(min(0.6, dur), 3), "shake_amp": SHAKE_AMP * 2.5, "flash": round(min(0.25, dur), 3)}
    elif clave == "pop":
        kf = [_k(0.0, box, s=0.4, i="bounce"), _k(min(0.35, dur * 0.6), box)]
    elif clave == "ataca":
        # 👊 embestida: se lanza hacia delante (golpea a los 0,12 s) y vuelve a su sitio
        ida = lado * 0.35 * box["w"]
        kf = [_k(0.0, box, i="in"), _k(min(0.12, dur * 0.3), box, ida, 0.01 * box["h"], s=1.04, i="linear"),
              _k(min(0.2, dur * 0.5), box, ida * 0.9, 0.01 * box["h"], s=1.04), _k(min(0.5, dur), box)]
    elif clave == "esquiva":
        atras_x = atras * 0.25 * box["w"]
        kf = [_k(0.0, box, i="out"), _k(min(0.15, dur * 0.35), box, atras_x, -0.06 * box["h"]),
              _k(min(0.3, dur * 0.6), box, atras_x, 0.0, i="out"), _k(min(0.6, dur), box)]
    elif clave == "derribado":
        # 💫 recibe el golpe, cae al suelo y se queda ahí (no desaparece: para un «K.O.»)
        g = min(0.1, dur * 0.2)
        cae = min(dur, max(g + 0.2, 0.5))
        abajo = (atras * 0.12 * box["w"], 0.45 * box["h"])
        kf = [_k(0.0, box, i="out"), _k(g, box, atras * 0.08 * box["w"], -0.03 * box["h"], i="in"),
              _k(cae, box, abajo[0], abajo[1], i="hold"), _k(dur, box, abajo[0], abajo[1])]
        fx = {"shake": round(min(0.3, dur), 3), "shake_amp": SHAKE_AMP}
    elif clave in ("huye", "cruza_corre"):
        # 💨 huir: se da la vuelta y sale corriendo por su espalda · 🏃 cruzar corriendo: de un lado a otro
        if clave == "huye":
            ini, fin = 0.0, (-(box["x"] + box["w"]) if atras < 0 else 1.0 - box["x"])
            layout["flip_h"] = not bool(caja.get("flip_h"))        # (mira hacia donde corre)
        else:
            ini = -(box["x"] + box["w"]) if lado > 0 else 1.0 - box["x"]
            fin = (1.0 - box["x"]) if lado > 0 else -(box["x"] + box["w"])
        cada, alto = 0.2, 0.045 * box["h"]
        n = max(1, int(dur / cada))
        kf = [_k(0.0, box, ini, i="linear")]
        for j in range(n):
            t1, t2 = (j + 0.5) * cada, (j + 1) * cada
            if t2 > dur + 1e-6:
                break
            kf += [_k(t1, box, ini + (fin - ini) * t1 / dur, -alto, i="linear"),
                   _k(t2, box, ini + (fin - ini) * t2 / dur, 0.0, i="linear")]
        kf.append(_k(dur, box, fin))
    elif clave == "celebra":
        kf = [_k(0.0, box, i="out")]
        t, cada = 0.0, 0.42
        while t + cada <= dur + 1e-6:
            kf += [_k(t + cada * 0.45, box, 0.0, -0.15 * box["h"], s=1.05, i="in"), _k(t + cada, box, i="out")]
            t += cada
    elif clave == "abatido":
        b2 = dict(box, y=box["y"] + 0.06 * box["h"])
        kf = [_k(0.0, box, i="out"), _k(min(1.2, dur), b2, s=0.94), _k(dur, b2, s=0.94)]
    elif clave == "susto":
        kf = [_k(0.0, box, i="out"), _k(min(0.1, dur * 0.3), box, atras * 0.04 * box["w"], -0.1 * box["h"], s=1.08),
              _k(min(0.4, dur), box, atras * 0.04 * box["w"]), _k(dur, box, atras * 0.04 * box["w"])]
        fx = {"shake": round(min(0.4, dur), 3), "shake_amp": SHAKE_AMP * 1.2}
    elif clave == "retrocede":
        kf = [_k(0.0, box, i="out"), _k(dur, box, atras * 0.12)]
        fx = {"shake": round(dur, 3), "shake_amp": SHAKE_AMP * 0.45}
    elif clave == "habla":
        kf = [_k(0.0, box)]
        t, j = 0.0, 0
        while t + 0.26 <= dur + 1e-6:
            t += 0.26
            arriba = j % 2 == 0
            kf.append(_k(min(t, dur), box, lado * 0.012 * box["w"] if arriba else 0.0,
                         -0.018 * box["h"] if arriba else 0.0, s=1.02 if arriba else 1.0))
            j += 1
        if kf[-1]["x"] != _k(0.0, box)["x"] or kf[-1]["y"] != _k(0.0, box)["y"]:
            kf.append(_k(dur, box))                     # (acaba en su sitio: lo de después no da un salto)
    elif clave == "sacudida":
        fx = {"shake": round(max(0.1, min(dur, 0.8)), 3), "shake_amp": SHAKE_AMP * 2.0}
    elif clave == "destello":
        fx = {"flash": round(min(0.3, dur), 3)}
    if clave in ("entra", "cruza", "sale", "conduce", "frena", "camina", "corre", "huye", "cruza_corre", "derribado",
                 "ataca", "esquiva", "retrocede"):         # (lo de fuera de la pantalla no debe dejar bandas)
        layout["bg"] = "none"
    return {"layout": layout, "layout_kf": _limpiar(kf, dur), "op_kf": op, "fx": fx}


# 🎬 Fases de las escenas (core/scenes.py): cada personaje entra → hace cosas → sale; cada fase es un trozo de clip.
ENTRADAS = [("abajo", "⬆ Desde abajo"), ("izquierda", "→ Desde la izquierda"), ("derecha", "← Desde la derecha"),
            ("arriba", "⬇ Desde arriba"), ("aparece", "✨ Aparecer (fundido)"), ("pop", "💫 Aparecer de golpe (rebote)"),
            ("cae", "💥 Caer desde arriba (impacto)")]
# Las acciones, por categoría (el menú «＋» de cada fila de la escena las enseña así)
ACCIONES_CAT = [
    ("🧍 Personaje", [("ninguna", "Quieto"), ("disparo", "🔫 Disparar"), ("golpe", "💥 Recibir un golpe"),
                      ("salta", "⤴ Saltar"), ("camina", "🚶 Caminar"), ("corre", "🏃 Correr"),
                      ("agacha", "⤵ Agacharse"), ("tiembla", "〰 Temblar"), ("acerca", "🔍 Acercarse")]),
    ("⚔ Pelea", [("ataca", "👊 Atacar (embestida)"), ("esquiva", "↩ Esquivar"), ("derribado", "💫 Caer al suelo"),
                 ("retrocede", "😨 Retroceder con miedo")]),
    ("🏃 Moverse", [("cruza_corre", "🏃 Cruzar corriendo"), ("cruza", "⇆ Cruzar la pantalla"),
                    ("huye", "💨 Huir (se da la vuelta)")]),
    ("💬 Reacción", [("habla", "💬 Hablar (gesticula)"), ("susto", "😱 Sobresaltarse"), ("celebra", "🎉 Celebrar"),
                     ("abatido", "😞 Abatido (se hunde)")]),
    ("🚗 Vehículo", [("conduce", "🚗 Pasar conduciendo"), ("frena", "🛑 Llegar y frenar"), ("flota", "🛸 Flotar / volar"),
                     ("explota", "💥 Explotar")]),
    ("✨ Efectos", [("pop", "✨ Aparecer de golpe (rebote)"), ("destello", "⚡ Destello"),
                    ("sacudida", "📳 Sacudida (temblor de cámara)")]),
]
# Acciones tras las que el personaje ya no está (se fue de la pantalla o explotó): lo de después no lo hace reaparecer
TERMINAN = {"explota", "huye", "cruza_corre"}      # («⇆ Cruzar» no: lo de después sigue viéndose, como antes)
ACCIONES = [a for _cat, lst in ACCIONES_CAT for a in lst]
NOMBRE_ACCION = dict(ACCIONES) | {"propia": "🎥 Movimiento propio"}
SALIDAS = [("muere", "💀 Morir (cae)"), ("abajo", "⬇ Irse por abajo"), ("izquierda", "← Irse por la izquierda"),
           ("derecha", "→ Irse por la derecha"), ("arriba", "⬆ Irse por arriba"), ("desvanece", "Desvanecerse"),
           ("huye", "💨 Huir corriendo (se da la vuelta)")]
FASES = {"entrada": ENTRADAS, "accion": ACCIONES + [("propia", "🎥 Movimiento propio")], "salida": SALIDAS}


def _fuera(box: dict, hacia: str) -> tuple[float, float]:
    """(dx, dy) que esconde la caja entera por ese borde de la pantalla."""
    return {"abajo": (0.0, 1.0 - box["y"]), "arriba": (0.0, -(box["y"] + box["h"])),
            "izquierda": (-(box["x"] + box["w"]), 0.0), "derecha": (1.0 - box["x"], 0.0)}.get(hacia, (0.0, 0.0))


def plan_fase(tipo: str, clave: str, caja: dict, dur: float, lado: int = 0, kf: list | None = None) -> dict:
    """Una fase de una escena: «entrada» (llega desde un borde o aparece), «accion» (las de ACCIONES, o «propia»: el
    movimiento grabado con el ratón, kf = [{"t": 0–1, "dx", "dy"}] respecto a su caja) o «salida» (muere, se va por un
    borde o se desvanece). Mismo formato que plan()."""
    if tipo == "accion" and clave == "propia":
        return plan_propia(caja, dur, kf or [])
    if tipo == "accion":
        return plan(clave, caja, dur, lado)
    dur = max(0.05, float(dur))
    box = {k: float(caja.get(k, d)) for k, d in (("x", 0.25), ("y", 0.15), ("w", 0.5), ("h", 0.7))}
    layout = dict(caja)
    layout.update({k: _r(v) for k, v in box.items()})
    layout["bg"] = "none"
    if (tipo == "salida" and clave in ("muere", "huye")) or (tipo == "entrada" and clave == "pop"):
        p = plan(clave, caja, dur, lado)
        p["layout"]["bg"] = "none"
        return p
    if tipo == "entrada" and clave == "cae":            # 💥 cae desde arriba, aplasta un poco al llegar y se recupera
        llega = dur * 0.7
        b2 = dict(box, y=box["y"] + 0.07 * box["h"], h=box["h"] * 0.93, x=box["x"] - box["w"] * 0.03,
                  w=box["w"] * 1.06)
        kf = [_k(0.0, box, 0.0, -(box["y"] + box["h"]), i="in"), _k(llega, box, i="out"),
              _k(llega + (dur - llega) * 0.4, b2, i="out"), _k(dur, box)]
        return {"layout": layout, "layout_kf": _limpiar(kf, dur), "op_kf": [], "fx": {}}
    if clave in ("aparece", "desvanece"):
        op = [{"t": 0.0, "v": 0.0}, {"t": _r(dur), "v": 1.0}] if tipo == "entrada" else \
             [{"t": 0.0, "v": 1.0}, {"t": _r(dur), "v": 0.0}]
        return {"layout": layout, "layout_kf": [], "op_kf": op, "fx": {}}
    dx, dy = _fuera(box, clave)
    if tipo == "entrada":
        kf = [_k(0.0, box, dx, dy, i="out"), _k(dur, box)]
    else:
        kf = [_k(0.0, box, i="in"), _k(dur, box, dx, dy)]
    return {"layout": layout, "layout_kf": _limpiar(kf, dur), "op_kf": [], "fx": {}}


CAJA_PERSONAJE = {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.65, "fit": "contain", "bg": "none"}
TIEMBLAN = ("muere", "golpe", "tiembla")


def apply(clip, clave: str, lado: int = 0, caja: dict | None = None, es_imagen: bool = True) -> None:
    """Pone la animación en un clip (en un video, las claves se pasan a segundos del archivo). Quita el temblor de
    una animación anterior y recuerda la elegida en fx["anim"] (para el Inspector y para rehacerla)."""
    from . import transform
    base = caja or clip.layout or dict(transform.FULL, bg="none")   # (sin caja = a pantalla completa: se queda así)
    p = plan(clave, base, clip.duration, lado)
    fx = dict(clip.fx or {})
    fx.pop("ovl", None)                                    # (deja de ser un «🖼 Estilo de imagen»: ahora es esto)
    fx.pop("enter", None)
    if (fx.get("anim") or {}).get("key") in TIEMBLAN:     # (el temblor era de la animación de antes)
        fx.pop("shake", None)
        fx.pop("shake_amp", None)
    fx.update(p["fx"])
    if clave == "ninguna":
        fx.pop("anim", None)
    else:
        fx["anim"] = {"key": clave, "side": lado_de(p["layout"], lado)}
    clip.fx = fx or None
    clip.layout = p["layout"]
    kf, op = p["layout_kf"], p["op_kf"]
    if not es_imagen:
        kf = [dict(k, t=round(clip.src_at(k["t"]), 4)) for k in kf]
        op = [dict(k, t=round(clip.src_at(k["t"]), 4)) for k in op]
    clip.layout_kf = transform.sorted_kf(kf) if kf else []
    clip.op_kf = op


_ALFA: dict[tuple, bool] = {}


def tiene_transparencia(ruta: str) -> bool:
    """¿Es un recorte (PNG o WebP con transparencia, como un personaje sin fondo)? Solo lee la cabecera."""
    import os
    try:
        st = os.stat(ruta)
    except OSError:
        return False
    clave = (ruta, st.st_mtime, st.st_size)
    if clave in _ALFA:
        return _ALFA[clave]
    alfa = False
    try:
        with open(ruta, "rb") as f:
            cab = f.read(4096)
        if cab[:8] == b"\x89PNG\r\n\x1a\n" and len(cab) > 25:
            alfa = cab[25] in (4, 6) or b"tRNS" in cab           # (gris/color con alfa, o paleta con transparencia)
        elif cab[:4] == b"RIFF" and cab[8:12] == b"WEBP":
            if cab[12:16] == b"VP8X" and len(cab) > 20:
                alfa = bool(cab[20] & 0x10)
            elif cab[12:16] == b"VP8L" and len(cab) > 24:
                alfa = bool((cab[24] >> 4) & 1)
    except OSError:
        alfa = False
    _ALFA[clave] = alfa
    return alfa


def texto_en(project, t: float, antes: float = 2.0, despues: float = 2.5) -> str:
    """Lo que se dice alrededor del segundo t de la línea de tiempo (las transcripciones de los clips que suenan)."""
    out = []
    a, b = t - antes, t + despues
    for c in project.clips.values():
        words = (project.transcripts.get(c.media_id) or {}).get("words") if project.transcripts else None
        if not words or c.speed <= 0 or c.end <= a or c.start >= b:
            continue
        s0 = c.src_at(max(0.0, a - c.start))
        s1 = c.src_at(min(c.duration, b - c.start))
        lo, hi = min(s0, s1), max(s0, s1)
        out += [str(w[2]) for w in words if len(w) > 2 and lo <= float(w[0]) <= hi]
    return " ".join(out)


def descripcion_corta(clave: str) -> str:
    return f"{NAMES.get(clave, clave)} — {DESCS.get(clave, '')}"
