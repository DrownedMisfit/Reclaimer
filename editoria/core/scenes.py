"""
🎬 Escenas animadas: en un tramo de la línea de tiempo (p. ej. del segundo 15 al 19) aparecen personajes (imágenes,
mejor PNG recortados), hacen cosas y se van, con sus efectos de sonido. Se montan en la página «🎬 Escenas» y al
aplicarlas se convierten en clips normales (agrupados con la nota «🎬 <id>»): se ven y se exportan como cualquier
otro clip, y la escena se guarda en el proyecto (Project.scenes) para volver a abrirla y cambiarla. Sin Qt.

Una escena (un dict, para guardarla tal cual en el proyecto):
  {"id", "nombre", "a", "b" (segundos de la línea de tiempo), "fondo": "blur" | "normal" | "dark",
   "actores": [{"id", "media_id", "caja": {x, y, w, h}, "lado": 0 | 1 | -1, "inicio": s desde «a»,
                "fases": [{"tipo": "entrada" | "accion" | "salida", "anim": clave, "dur": s}, …]}],
   "sonidos": [{"id", "media_id", "t": s desde «a», "dur": s, "vol": 0–1}]}
Cada fase es un trozo de clip de la misma imagen, uno detrás de otro (sin saltos: todas empiezan o acaban en su caja),
con la animación de core/image_anim.plan_fase. El fondo desenfocado u oscurecido es una 🎨 capa de ajuste debajo de
los personajes durante toda la escena.

  nueva(a, b) · nuevo_actor(escena, media_id) · nuevo_sonido(escena, media_id, t, dur)
  duracion_actor(actor) · piezas(escena) -> [{"actor", "fase", "a", "b", "plan"}]   (segundos de la línea de tiempo)
  nota(id) / id_de_nota(nota)
"""
from __future__ import annotations

import copy
import uuid

from . import image_anim

FONDOS = [("blur", "Desenfocado"), ("normal", "Normal"), ("dark", "Oscurecido")]
FONDO_POR_DEFECTO = "blur"
BLUR = 0.6                  # como el estilo «encima, fondo desenfocado» de las imágenes
OSCURO = -0.9               # exposición del fondo oscurecido (pasos)
PREFIJO = "🎬 "
DUR_ENTRADA, DUR_SALIDA = 0.6, 0.8
COLORES = {"entrada": "#4a90d9", "accion": "#e0a030", "salida": "#d9534f"}
NOMBRE_TIPO = {"entrada": "Entrada", "accion": "Acción", "salida": "Salida"}


def _id() -> str:
    return uuid.uuid4().hex[:10]


def nota(escena_id: str) -> str:
    return PREFIJO + escena_id


def id_de_nota(texto: str | None) -> str | None:
    t = texto or ""
    return t[len(PREFIJO):].split()[0] if t.startswith(PREFIJO) and len(t) > len(PREFIJO) else None


def nueva(a: float, b: float, nombre: str = "") -> dict:
    a, b = sorted((max(0.0, float(a)), max(0.0, float(b))))
    if b - a < 0.3:
        b = a + 3.0
    return {"id": _id(), "nombre": nombre or "Escena", "a": round(a, 3), "b": round(b, 3),
            "fondo": FONDO_POR_DEFECTO, "actores": [], "sonidos": []}


def largo(escena: dict) -> float:
    return max(0.3, float(escena["b"]) - float(escena["a"]))


def caja_libre(escena: dict) -> dict:
    """Dónde poner al siguiente personaje: uno a la izquierda, otro a la derecha, luego al centro…"""
    sitios = [0.08, 0.57, 0.33, 0.0, 0.66]
    x = sitios[len(escena["actores"]) % len(sitios)]
    return {"x": x, "y": 0.22, "w": 0.34, "h": 0.66, "fit": "contain", "bg": "none"}


def nuevo_actor(escena: dict, media_id: str, caja: dict | None = None) -> dict:
    """Entra desde abajo, se queda quieto hasta el final de la escena (sin salida: la eliges tú)."""
    total = largo(escena)
    entrada = min(DUR_ENTRADA, total * 0.3)
    actor = {"id": _id(), "media_id": media_id, "caja": dict(caja or caja_libre(escena)), "lado": 0, "inicio": 0.0,
             "fases": [{"tipo": "entrada", "anim": "abajo", "dur": round(entrada, 3)},
                       {"tipo": "accion", "anim": "ninguna", "dur": round(total - entrada, 3), "auto": True}]}
    escena["actores"].append(actor)
    return actor


def nuevo_sonido(escena: dict, media_id: str, t: float, dur: float, vol: float = 0.5) -> dict:
    """Un sonido en la escena (a la MITAD de volumen por defecto: los efectos suenan muy fuertes)."""
    s = {"id": _id(), "media_id": media_id, "t": round(max(0.0, float(t)), 3), "dur": round(max(0.05, float(dur)), 3),
         "vol": float(vol)}
    escena["sonidos"].append(s)
    return s


def duracion_actor(actor: dict) -> float:
    return sum(max(0.0, float(f["dur"])) for f in actor["fases"])


def ordenar_fases(actor: dict) -> None:
    """Siempre: entrada (como mucho una) → acciones → salida (como mucho una)."""
    orden = {"entrada": 0, "accion": 1, "salida": 2}
    actor["fases"].sort(key=lambda f: orden.get(f["tipo"], 1))


def encajar(escena: dict) -> None:
    """El «Quieto» elástico de cada personaje (fase con "auto") ocupa lo que sobra hasta el final de la escena: así una
    acción o una salida nueva cabe dentro, y alargar o acortar el tramo no deja a nadie a medias."""
    total = largo(escena)
    for actor in escena["actores"]:
        elastica = next((f for f in actor["fases"] if f.get("auto")), None)
        if elastica is None:
            continue
        resto = total - max(0.0, float(actor.get("inicio", 0.0))) - sum(
            max(0.0, float(f["dur"])) for f in actor["fases"] if f is not elastica)
        elastica["dur"] = round(max(0.1, resto), 3)


def fijar(fase: dict) -> None:
    """La duración la eligió el usuario: deja de ser elástica."""
    fase.pop("auto", None)


def poner_fase(actor: dict, tipo: str, anim: str, dur: float | None = None) -> dict:
    """Pone (o cambia) la entrada / salida, o añade una acción: justo antes del «Quieto» elástico si lo hay (entra →
    hace eso → espera), si no, al final de las acciones."""
    dur = float(dur if dur is not None else (DUR_ENTRADA if tipo == "entrada" else
                                            DUR_SALIDA if tipo == "salida" else 1.0))
    if tipo in ("entrada", "salida"):
        f = next((f for f in actor["fases"] if f["tipo"] == tipo), None)
        if f is not None:
            f["anim"] = anim
            return f
    f = {"tipo": tipo, "anim": anim, "dur": round(max(0.1, dur), 3)}
    elastica = next((i for i, x in enumerate(actor["fases"]) if x.get("auto")), None)
    if tipo == "accion" and elastica is not None:
        actor["fases"].insert(elastica, f)
    else:
        actor["fases"].append(f)
    ordenar_fases(actor)
    return f


def quitar_fase(actor: dict, fase: dict) -> None:
    if fase in actor["fases"] and len(actor["fases"]) > 1:
        actor["fases"].remove(fase)


def piezas(escena: dict) -> list[dict]:
    """Los trozos de clip de cada personaje (en segundos de la línea de tiempo), con su animación. Lo que pase del final
    de la escena se corta (la escena manda)."""
    encajar(escena)
    a0, b0 = float(escena["a"]), float(escena["b"])
    out = []
    for actor in escena["actores"]:
        t = a0 + max(0.0, float(actor.get("inicio", 0.0)))
        dx = dy = 0.0                    # (lo que se ha desplazado: caminar, correr, un movimiento propio…)
        for fase in actor["fases"]:
            d = max(0.0, float(fase["dur"]))
            caja = actor["caja"]
            if (dx or dy) and fase["tipo"] != "entrada":   # cada fase empieza donde acabó la anterior (no da un salto)
                caja = dict(caja, x=round(float(caja["x"]) + dx, 4), y=round(float(caja["y"]) + dy, 4))
            plan = image_anim.plan_fase(fase["tipo"], fase["anim"], caja, d, int(actor.get("lado", 0)),
                                        kf=fase.get("kf"))
            if fase["tipo"] == "accion" and plan["layout_kf"]:
                fin_k = plan["layout_kf"][-1]       # dónde acaba respecto a SU caja (por el centro: acercarse no cuenta;
                cx = float(caja["x"]) + float(caja["w"]) / 2   # y «frenar», que empieza fuera, no da un salto)
                cy = float(caja["y"]) + float(caja["h"]) / 2
                dx += (fin_k["x"] + fin_k["w"] / 2) - cx
                dy += (fin_k["y"] + fin_k["h"] / 2) - cy
            if d < 0.05 or t >= b0 - 0.01:
                t += d
                continue
            fin = min(b0, t + d)
            out.append({"actor": actor["id"], "fase": fase, "a": round(t, 4), "b": round(fin, 4), "plan": plan})
            t += d
            if fase["anim"] == "explota":           # 💥 tras explotar ya no está (lo de después no lo hace reaparecer)
                break
    return out


def sonidos(escena: dict) -> list[dict]:
    """Los sonidos en segundos de la línea de tiempo (cortados al final de la escena)."""
    a0, b0 = float(escena["a"]), float(escena["b"])
    out = []
    for s in escena["sonidos"]:
        a = a0 + max(0.0, float(s["t"]))
        if a >= b0 - 0.01:
            continue
        out.append(dict(s, a=round(a, 4), b=round(min(b0, a + max(0.05, float(s["dur"]))), 4)))
    return out


def copia(escena: dict) -> dict:
    return copy.deepcopy(escena)


def mover(escena: dict, a: float) -> None:
    """Cambia dónde empieza la escena (lo de dentro va con ella)."""
    d = largo(escena)
    escena["a"] = round(max(0.0, float(a)), 3)
    escena["b"] = round(escena["a"] + d, 3)


def estirar(escena: dict, dur: float) -> None:
    """Cambia cuánto dura la escena ESTIRANDO (o encogiendo) todo en proporción: entradas, acciones, salidas y cuándo
    aparece cada personaje; los sonidos se recolocan en proporción (su duración no cambia: no se deforma el audio)."""
    viejo = largo(escena)
    nuevo = max(0.3, float(dur))
    k = nuevo / viejo
    for actor in escena["actores"]:
        actor["inicio"] = round(float(actor.get("inicio", 0.0)) * k, 3)
        for f in actor["fases"]:
            f["dur"] = round(max(0.05, float(f["dur"]) * k), 3)
    for s in escena["sonidos"]:
        s["t"] = round(float(s["t"]) * k, 3)
    escena["b"] = round(float(escena["a"]) + nuevo, 3)
    encajar(escena)


def otra_copia(escena: dict, a: float | None = None) -> dict:
    """La misma animación como escena NUEVA (otro id, otros ids dentro), en «a» si se da."""
    nueva_e = copy.deepcopy(escena)
    nueva_e["id"] = _id()
    for x in nueva_e["actores"] + nueva_e["sonidos"]:
        x["id"] = _id()
    if a is not None:
        mover(nueva_e, a)
    return nueva_e


# ---------------------------------------------------------------- 📚 mis animaciones (para cualquier proyecto)
def _carpeta_plantillas() -> str:
    import os

    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "animaciones")
    os.makedirs(d, exist_ok=True)
    return d


RESERVADOS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def _archivo(nombre: str) -> str:
    """El .json de esa animación, SIEMPRE dentro de la carpeta (sin barras, ni «..», ni nombres reservados)."""
    import os
    import re
    limpio = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', " ", nombre)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")[:80] or "Animación"
    if limpio.lower() in RESERVADOS:
        limpio = "_" + limpio
    return os.path.join(_carpeta_plantillas(), limpio + ".json")


def existe_plantilla(nombre: str) -> bool:
    """¿Ya hay una animación guardada con ese nombre? (Windows no distingue mayúsculas: «Pelea» = «pelea»)."""
    import os
    return os.path.exists(_archivo(nombre))


def guardar_plantilla(escena: dict, project, nombre: str) -> str:
    import os
    """Guarda la animación (sin sitio en la línea de tiempo) para usarla en cualquier proyecto: los personajes y los
    sonidos van por la RUTA de su archivo (en otro proyecto se importan al usarla)."""
    import json
    from . import sfx
    rutas = {mid: m.path for mid, m in project.media.items()}
    propios = {os.path.normcase(sfx.path_for(k)): k for k in sfx.CATALOG} if escena["sonidos"] else {}
    t = {"nombre": nombre, "dur": round(largo(escena), 3), "fondo": escena.get("fondo", FONDO_POR_DEFECTO),
         "actores": [], "sonidos": []}
    for a in escena["actores"]:
        if a["media_id"] in rutas:
            t["actores"].append(dict(copy.deepcopy({k: v for k, v in a.items() if k not in ("id", "media_id")}),
                                     ruta=rutas[a["media_id"]]))
    for s in escena["sonidos"]:
        if s["media_id"] in rutas:
            x = dict({k: v for k, v in s.items() if k not in ("id", "media_id")}, ruta=rutas[s["media_id"]])
            clave = propios.get(os.path.normcase(rutas[s["media_id"]]))
            if clave:                                  # (un ✦ de Reclaimer: se vuelve a crear si falta su archivo)
                x["sfx"] = clave
            t["sonidos"].append(x)
    ruta = _archivo(nombre)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=1)
    return ruta


def plantillas() -> list[dict]:
    """[{"nombre", "dur", "ruta", "actores", "sonidos"}] de las animaciones guardadas, por nombre."""
    import json
    import os
    out = []
    d = _carpeta_plantillas()
    for f in sorted(os.listdir(d), key=str.lower):
        if f.lower().endswith(".json"):
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    t = json.load(fh)
                if not isinstance(t, dict):            # (un archivo raro no tumba los menús)
                    continue
                try:
                    t["dur"] = max(0.3, float(t.get("dur") or 4.0))
                except (TypeError, ValueError):
                    t["dur"] = 4.0
                t["nombre"] = str(t.get("nombre") or os.path.splitext(f)[0])
                t["actores"] = [x for x in (t.get("actores") or []) if isinstance(x, dict)]
                t["sonidos"] = [x for x in (t.get("sonidos") or []) if isinstance(x, dict)]
                t["archivo"] = os.path.join(d, f)
                out.append(t)
            except (OSError, ValueError):
                continue
    return out


def borrar_plantilla(t: dict) -> None:
    import os
    try:
        os.remove(t["archivo"])
    except (OSError, KeyError):
        pass


def desde_plantilla(t: dict, a: float, media_de_ruta, dur: float | None = None) -> tuple[dict, list[str]]:
    """Una escena nueva a partir de una animación guardada, que empieza en «a» (y dura «dur», estirada, si se da).
    media_de_ruta(ruta, categoria) -> media_id (importa el archivo si hace falta: «Escenas» los personajes,
    «Efectos» los sonidos). Devuelve (escena, archivos que faltan)."""
    import os

    from . import sfx
    e = nueva(a, a + float(t.get("dur") or 4.0), t.get("nombre") or "Animación")
    e["fondo"] = t.get("fondo", FONDO_POR_DEFECTO)
    faltan = []
    for x in t.get("actores") or []:
        ruta = x.get("ruta", "")
        mid = media_de_ruta(ruta, "Escenas") if ruta and os.path.isfile(ruta) else None
        if not mid:
            faltan.append(ruta)
            continue
        act = copy.deepcopy({k: v for k, v in x.items() if k != "ruta"})
        act.update(id=_id(), media_id=mid)
        e["actores"].append(act)
    for x in t.get("sonidos") or []:
        ruta = x.get("ruta", "")
        if x.get("sfx") in sfx.CATALOG:                # (✦ de Reclaimer: se regenera si se limpió la caché)
            ruta = sfx.path_for(x["sfx"])
        mid = media_de_ruta(ruta, "Efectos") if ruta and os.path.isfile(ruta) else None
        if not mid:
            faltan.append(ruta)
            continue
        s = {k: v for k, v in x.items() if k not in ("ruta", "sfx")}
        s.update(id=_id(), media_id=mid)
        e["sonidos"].append(s)
    if dur is not None and abs(float(dur) - largo(e)) > 1e-3:
        estirar(e, dur)
    return e, faltan


# ---------------------------------------------------------------- insertar en un momento · interacciones
def fase_en(actor: dict, t: float) -> tuple[int, float] | None:
    """(índice de la fase que se ve en el segundo t de la escena, segundos dentro de ella) o None (aún no salió o ya
    se fue)."""
    x = float(actor.get("inicio", 0.0))
    for i, f in enumerate(actor["fases"]):
        d = max(0.0, float(f["dur"]))
        if x - 1e-6 <= t < x + d - 1e-6:
            return i, t - x
        x += d
    return None


def insertar_en(escena: dict, actor: dict, t: float, fase: dict) -> dict:
    """Pone la fase (una acción) justo en el segundo t de la escena: parte en dos la fase que haya ahí (lo de después
    sigue después); si cae en la entrada, va justo tras ella; en la salida, justo antes; antes de que salga, al
    principio de sus acciones; después de irse, al final."""
    encajar(escena)
    f = dict(fase)
    f["dur"] = round(max(0.1, float(f.get("dur", 1.0))), 3)
    donde = fase_en(actor, t)
    fases = actor["fases"]
    if donde is None:
        if t < float(actor.get("inicio", 0.0)):
            i = next((k for k, x in enumerate(fases) if x["tipo"] != "entrada"), len(fases))
        else:
            i = next((k for k, x in enumerate(fases) if x["tipo"] == "salida"), len(fases))
        fases.insert(i, f)
    else:
        i, dentro = donde
        actual = fases[i]
        if actual["tipo"] == "entrada" or actual.get("anim") == "propia":   # (un movimiento propio no se parte)
            fases.insert(i + 1, f)
        elif actual["tipo"] == "salida":
            fases.insert(i, f)
        elif dentro < 0.05:
            fases.insert(i, f)
        else:
            resto = max(0.0, float(actual["dur"]) - dentro)
            actual["dur"] = round(dentro, 3)
            despues = dict(actual, dur=round(resto, 3))
            if actual.get("auto"):                    # (el «Quieto» elástico sigue siéndolo solo en lo de después)
                actual.pop("auto", None)
            fases[i + 1:i + 1] = [f] + ([despues] if resto >= 0.05 else [])
    encajar(escena)
    return f


def disparar_a(escena: dict, tirador: dict, objetivo: dict, t: float, dur: float = 1.2,
               muere: bool = True) -> tuple[dict, list[dict]]:
    """🎯 El tirador dispara desde el segundo t; al objetivo le llega el primer disparo y reacciona justo entonces:
    un golpe y, si muere=True, cae y desaparece (si no, solo el golpe y sigue). Lo que el objetivo hacía después del
    impacto se quita (ya no tiene sentido). Devuelve (fase de disparo, fases nuevas del objetivo)."""
    disparo = insertar_en(escena, tirador, t, {"tipo": "accion", "anim": "disparo", "dur": dur})
    impacto = t + 0.12                                # (el primer retroceso del disparo: image_anim.SHOT_EVERY)
    encajar(escena)
    fases = objetivo["fases"]
    x = float(objetivo.get("inicio", 0.0))
    nuevas, quedan = [], []
    for f in fases:
        d = float(f["dur"])
        if x + d <= impacto + 1e-6:
            quedan.append(f)
        elif x < impacto:                             # (la que estaba haciendo cuando le dan: hasta el impacto)
            quedan.append(dict({k: v for k, v in f.items() if k != "auto"}, dur=round(impacto - x, 3)))
        x += d
    if x < impacto - 1e-6 and quedan:                  # (aún no había llegado al impacto: espera quieto)
        quedan.append({"tipo": "accion", "anim": "ninguna", "dur": round(impacto - x, 3)})
    reaccion = [{"tipo": "accion", "anim": "golpe", "dur": 0.45}]
    if muere:
        reaccion.append({"tipo": "salida", "anim": "muere", "dur": 1.0})
    else:
        reaccion.append({"tipo": "accion", "anim": "ninguna", "dur": 1.0, "auto": True})
    objetivo["fases"] = [f for f in quedan if f["tipo"] != "salida"] + reaccion
    nuevas = reaccion
    encajar(escena)
    return disparo, nuevas


# ---------------------------------------------------------------- 🎥 mis movimientos (grabados con el ratón)
def _carpeta_movimientos() -> str:
    import os

    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "movimientos")
    os.makedirs(d, exist_ok=True)
    return d


def guardar_movimiento(fase: dict, nombre: str) -> str:
    """Guarda un movimiento propio (sus claves relativas a la caja: sirve para cualquier personaje o vehículo)."""
    import json
    import os
    import re
    limpio = re.sub(r'[\x00-\x1f\/:*?"<>|]+', " ", nombre)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")[:80] or "Movimiento"
    if limpio.lower() in RESERVADOS:
        limpio = "_" + limpio
    ruta = os.path.join(_carpeta_movimientos(), limpio + ".json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"nombre": nombre, "dur": float(fase["dur"]), "kf": fase.get("kf") or []}, f, ensure_ascii=False,
                  indent=1)
    return ruta


def movimientos() -> list[dict]:
    import json
    import os
    out = []
    d = _carpeta_movimientos()
    for f in sorted(os.listdir(d), key=str.lower):
        if not f.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                m = json.load(fh)
            if isinstance(m, dict) and isinstance(m.get("kf"), list):
                m["archivo"] = os.path.join(d, f)
                m["nombre"] = str(m.get("nombre") or os.path.splitext(f)[0])
                try:
                    m["dur"] = max(0.1, float(m.get("dur") or 1.0))
                except (TypeError, ValueError):
                    m["dur"] = 1.0
                out.append(m)
        except (OSError, ValueError):
            continue
    return out


def fase_de_movimiento(m: dict) -> dict:
    return {"tipo": "accion", "anim": "propia", "dur": float(m["dur"]), "kf": copy.deepcopy(m["kf"])}


def cortar_en(escena: dict, actor: dict, t: float) -> bool:
    """✂ Corta en dos la fase de ese personaje que hay en el segundo t (como Ctrl+B en el editor): las dos mitades
    hacen lo mismo. No se cortan la entrada, la salida ni un movimiento propio (no tendría sentido partirlos)."""
    encajar(escena)
    donde = fase_en(actor, t)
    if donde is None:
        return False
    i, dentro = donde
    f = actor["fases"][i]
    if f["tipo"] != "accion" or f["anim"] == "propia" or dentro < 0.05 or float(f["dur"]) - dentro < 0.05:
        return False
    resto = round(float(f["dur"]) - dentro, 3)
    f["dur"] = round(dentro, 3)
    otra = {k: v for k, v in f.items()}
    otra["dur"] = resto
    if f.get("auto"):                                  # (el elástico sigue siéndolo en la parte de después)
        f.pop("auto", None)
    actor["fases"].insert(i + 1, otra)
    encajar(escena)
    return True


# ---------------------------------------------------------------- ⚖ comparativas (original y remake, dos versiones…)
MODOS_COMP = [("lado", "Lado a lado"), ("arriba", "Arriba y abajo"), ("fundido", "Fundido (de uno al otro)"),
              ("alternar", "Alternar (uno, otro, uno…)")]


def nueva_comparativa(a: float, b: float, nombre: str = "") -> dict:
    """Una escena de tipo «comparativa»: dos tomas (A y B) con su etiqueta, en uno de los MODOS_COMP."""
    e = nueva(a, b, nombre or "Comparativa")
    e["tipo"] = "comparativa"
    e["fondo"] = "normal"
    e["comp"] = {"A": {"media_id": "", "src": 0.0, "etiqueta": ""}, "B": {"media_id": "", "src": 0.0, "etiqueta": ""},
                 "modo": "lado", "cada": 2.0}
    return e


def es_comparativa(escena: dict) -> bool:
    return escena.get("tipo") == "comparativa"


def comp_piezas(escena: dict, vertical: bool = False, dur_de=None) -> tuple[list[dict], list[dict]]:
    """Los clips y las etiquetas de una comparativa (segundos de la línea de tiempo):
      clips    [{"lado": "A"|"B", "a", "b", "src", "layout": nombre de transform.LAYOUTS, "op_kf", "arriba": bool}]
      textos   [{"texto", "a", "b", "x", "y"}]
    dur_de(lado) -> duración del archivo (para no pasarse del final de un video; None = imagen o sin límite)."""
    c = escena["comp"]
    a0, b0 = float(escena["a"]), float(escena["b"])
    clips, textos = [], []

    def pieza(lado, a, b, layout, op=None, arriba=False):
        s = float(c[lado].get("src", 0.0)) + (a - a0)
        lim = dur_de(lado) if dur_de else None
        if lim is not None:
            b = min(b, a + max(0.0, lim - s))
        if b - a >= 0.05:
            clips.append({"lado": lado, "a": round(a, 4), "b": round(b, 4), "src": round(s, 4), "layout": layout,
                          "op_kf": op or [], "arriba": arriba})

    def etiqueta(lado, a, b, x, y):
        t = (c[lado].get("etiqueta") or "").strip()
        if t:
            textos.append({"texto": t, "a": round(a, 4), "b": round(b, 4), "x": x, "y": y})

    modo = c.get("modo", "lado")
    if modo in ("lado", "arriba"):
        horizontal = modo == "lado" and not vertical
        pieza("A", a0, b0, "Mitad izquierda" if horizontal else "Mitad superior")
        pieza("B", a0, b0, "Mitad derecha" if horizontal else "Mitad inferior", arriba=True)
        if horizontal:
            etiqueta("A", a0, b0, 0.25, 0.08)
            etiqueta("B", a0, b0, 0.75, 0.08)
        else:
            etiqueta("A", a0, b0, 0.5, 0.05)
            etiqueta("B", a0, b0, 0.5, 0.55)
    elif modo == "fundido":
        mid = (a0 + b0) / 2
        cruce = min(0.4, (b0 - a0) / 4)
        pieza("B", max(a0, mid - cruce), b0, "Pantalla completa")
        # (A, encima, se desvanece en el cruce: opacidad en segundos DEL ARCHIVO, es un video)
        sa = float(c["A"].get("src", 0.0))
        op = [{"t": round(sa + (mid - cruce - a0), 4), "v": 1.0}, {"t": round(sa + (mid + cruce - a0), 4), "v": 0.0}]
        pieza("A", a0, min(b0, mid + cruce), "Pantalla completa", op, arriba=True)
        etiqueta("A", a0, mid, 0.5, 0.08)
        etiqueta("B", mid, b0, 0.5, 0.08)
    else:                                              # alternar: cada «cada» segundos, una y otra
        cada = max(0.5, float(c.get("cada", 2.0)))
        t, i = a0, 0
        while t < b0 - 0.05:
            lado = "A" if i % 2 == 0 else "B"
            fin = min(b0, t + cada)
            pieza(lado, t, fin, "Pantalla completa")
            etiqueta(lado, t, fin, 0.5, 0.08)
            t, i = fin, i + 1
    return clips, textos
