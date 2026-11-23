"""
🔎 El buscador preciso (ai/buscador.py), SIN RED y sin ventanas (22/11, el usuario: «el buscador de descargas, lo más
preciso que puedas»). Con resultados simulados para «GTA 6 consola PS5 crasheo»:
  · entiende las dos entidades (GTA 6 y PS5, con sus variantes) y la clave («crasheo» → crash…), y que es actualidad;
  · las consultas de cada fuente: YouTube con la entidad entre comillas, X con filter:videos y min_faves, hashtags;
  · el ORDEN HÍBRIDO pone arriba lo que nombra TODAS las entidades (también con variantes: «GTA VI», «PlayStation 5»)
    y abajo las reacciones (con «Sin gente hablando»), las resubidas casi idénticas y lo que no nombra lo que buscas;
  · cada resultado dice por qué salió;
  · lo que eliges sube un poco la próxima vez (su canal, para ese tema);
  · SENTIDO: con una consola, «crasheo» es el juego que se cuelga: «Plane Crash Random Event» al fondo y «GTA 6
    crashing on PS5» arriba; la consulta busca «crashing», no «crash»; «humo» pide humo de verdad;
  · LA ACCIÓN cuenta: nombrar GTA 6 y PS5 sin el crasheo no gana a quien sí lo nombra;
  · ACTUALIDAD: un video de hoy poco relevante no gana a uno de hace 2 meses que es justo el tema (la fecha solo
    desempata entre los igual de relevantes);
  · «PS5 Pro vs PS5»: las dos consolas son entidades distintas.
Ejecutar (con el turno):  turno.py tests/test_buscador_orden.py
"""
from __future__ import annotations

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_buscador_", dir=os.path.join(RAIZ, "_pruebas_tmp"))
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)

FALLOS = []


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def main():
    from editoria.ai import buscador as B
    ent = B.entender("GTA 6 consola PS5 crasheo")
    nombres = [e["nombre"] for e in ent["entidades"]]
    chk(nombres == ["GTA 6", "PS5"] and "GTA VI" in ent["entidades"][0]["variantes"] and
        "PlayStation 5" in ent["entidades"][1]["variantes"], f"entidades con variantes: {ent['entidades']}")
    chk(any("crash" in c["formas"] for c in ent["claves"]) and ent["actualidad"] and
        not any(c["es"].lower() == "consola" for c in ent["claves"]), f"clave «crasheo» → crash; actualidad "
        f"({ent['claves']})")
    yt = B.consultas_youtube(ent)
    chk(yt[0] == '"GTA 6" PS5 crashing' and any("freezing" in q for q in yt) and len(yt) >= 3,
        f"YouTube, en el sentido de fallo («crashing», «freezing»): {yt}")
    chk(not hasattr(B, "consultas_reddit"), "sin consultas de Reddit (no es una fuente de búsqueda)")
    x = B.consulta_x(ent)
    chk("filter:videos" in x and "min_faves:" in x and "lang:es" in x, f"X: {x}")
    chk(B.hashtags(ent)[:2] == ["gta6", "ps5"], f"Instagram: {B.hashtags(ent)}")

    def r(id_, titulo, canal="Canal", vistas=10000, **k):
        return dict({"id": id_, "title": titulo, "channel": canal, "views": vistas, "duration": 240,
                     "url": f"https://ejemplo.invalid/{id_}", "official": False}, **k)
    res = [
        r("reaccion", "GTA 6 PS5 crash REACTION!!", vistas=3_000_000),
        r("compil", "Forza crash compilation", vistas=1_500_000),
        r("solo_ps5", "PS5 crash fix", vistas=200_000),
        r("copia", "GTA 6 Crashing on PS5 - How to fix", canal="Resubidas", vistas=900),
        r("buena", "GTA 6 Crashing on PS5 - How to fix", canal="TechFix", vistas=60_000),
        r("variantes", "GTA VI keeps crashing on PlayStation 5", canal="Otro", vistas=20_000),
    ]
    B.puntuar(res, ent, sin_gente=True, prefs={})
    orden = [x["id"] for x in res]
    chk(set(orden[:2]) == {"buena", "variantes"}, f"arriba, lo que nombra GTA 6 y PS5 (con variantes): {orden}")
    chk(orden.index("solo_ps5") < orden.index("compil"), f"una entidad, antes que ninguna: {orden}")
    chk(set(orden[-3:]) == {"reaccion", "copia", "compil"},
        f"abajo, la reacción (Sin gente hablando), la resubida y la recopilación sin lo que buscas: {orden}")
    copia = next(x for x in res if x["id"] == "copia")
    buena = next(x for x in res if x["id"] == "buena")
    chk(copia.get("resubida") == "buena" and "resubida" in copia["motivo"], f"la copia lo dice: «{copia['motivo']}»")
    chk("GTA 6" in buena["motivo"] and "PS5" in buena["motivo"] and "crash" in buena["motivo"],
        f"por qué salió: «{buena['motivo']}»")
    # (sin «Sin gente hablando», la reacción no se castiga por ser charla)
    res2 = [dict(x) for x in res]
    B.puntuar(res2, ent, sin_gente=False, prefs={})
    chk(next(x for x in res2 if x["id"] == "reaccion")["puntos"] >
        next(x for x in res if x["id"] == "reaccion")["puntos"], "la reacción solo baja con «Sin gente hablando»")
    # aprender: el canal de lo que eliges sube un poco en el mismo tema
    antes = next(x for x in res2 if x["id"] == "variantes")["puntos"]
    chk(B.aprender({"channel": "Otro"}, ent) and B.preferencias()["temas"]["gta6"]["Otro"] == 1,
        "lo elegido se apunta (canal, por tema) en los datos de Reclaimer")
    res3 = [dict(x) for x in res2]
    B.puntuar(res3, ent, sin_gente=False)
    chk(next(x for x in res3 if x["id"] == "variantes")["puntos"] > antes, "y la próxima vez sube un poco")
    chk(os.path.isfile(os.path.join(os.environ["EDITORIA_DATOS"], B.ARCHIVO_PREFS)), "guardado en datos/ (local)")
    sentido_y_actualidad(B, ent, r)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s)")
        sys.exit(1)
    print("TODO OK")


def sentido_y_actualidad(B, ent, r):
    import time

    def hace(dias):
        return time.strftime("%Y%m%d", time.localtime(time.time() - dias * 86400))
    # 🧭 sentido: «crash» con una consola = el juego se cuelga, no un avión que se estrella
    res = [
        r("avion", "GTA 6 | Plane Crash Random Event (PS5 Pro Gameplay 4K)", vistas=900_000, upload_date=hace(0)),
        r("aterriza", "GTA 6 Army Jet | Beach Crash Landing PS5 4K", vistas=300_000, upload_date=hace(1)),
        r("cuelga", "GTA 6 keeps crashing on PS5 - how to fix", vistas=8_000, upload_date=hace(40)),
        r("congela", "GTA 6 freezing on PlayStation 5", vistas=5_000, upload_date=hace(20)),
        r("sin_accion", "GTA 6 PS5 Pro gameplay 4K", vistas=2_000_000, upload_date=hace(0)),
    ]
    B.puntuar(res, ent, sin_gente=True, prefs={})
    orden = [x["id"] for x in res]
    chk(set(orden[:2]) == {"cuelga", "congela"} and set(orden[-2:]) == {"avion", "aterriza"},
        f"sentido: el juego que se cuelga arriba, el avión que se estrella al fondo: {orden}")
    avion = next(x for x in res if x["id"] == "avion")
    chk("otro sentido" in avion["motivo"] and "plane" in avion["motivo"], f"y lo dice: «{avion['motivo']}»")
    chk(orden.index("sin_accion") > orden.index("congela"),
        f"la acción cuenta: «GTA 6 PS5» sin crasheo no gana a quien lo nombra: {orden}")
    # 🕒 actualidad: la fecha solo desempata dentro de lo relevante
    res = [r("hoy", "GTA 6 PS5 new update gameplay", vistas=50_000, upload_date=hace(0)),
           r("dos_meses", "GTA 6 crashing on PS5 fix", vistas=50_000, upload_date=hace(60))]
    B.puntuar(res, ent, sin_gente=True, prefs={})
    chk([x["id"] for x in res] == ["dos_meses", "hoy"],
        f"actualidad: el de hace 2 meses que es el tema gana al de hoy poco relevante: {[x['id'] for x in res]}")
    res = [r("viejo", "GTA 6 keeps crashing on my PS5", vistas=50_000, upload_date=hace(300)),
           r("nuevo", "GTA 6 crashing on PS5 again", canal="Otro", vistas=50_000, upload_date=hace(3))]
    B.puntuar(res, ent, sin_gente=True, prefs={})
    chk([x["id"] for x in res][0] == "nuevo", "entre dos igual de relevantes, desempata la fecha")
    # 🔥 «humo» pide humo de verdad (y el personaje Smoke de Mortal Kombat no es humo)
    eh = B.entender("PS5 humo ventilador")
    res = [r("limpiar", "Clean your PS5 fan in 2 minutes", vistas=900_000),
           r("mk", "Mortal Kombat 1 Smoke gameplay PS5", vistas=500_000),
           r("humo", "My PS5 started smoking and the fan got loud", vistas=3_000),
           r("desc", "PS5 problem", vistas=20_000, description="burning smell and smoke from the fan")]
    B.puntuar(res, eh, sin_gente=True, prefs={})
    orden = [x["id"] for x in res]
    chk(orden[:2] == ["humo", "desc"] and orden[-1] == "mk",
        f"humo de verdad (en el título, luego en la descripción) arriba; Mortal Kombat al fondo: {orden}")
    # «PS5 Pro vs PS5»: dos entidades; «PS5 Pro vs Xbox» no tiene la PS5 normal
    ev = B.entender("PS5 Pro vs PS5 GTA 6 rendimiento")
    chk([e["nombre"] for e in ev["entidades"]] == ["GTA 6", "PS5 Pro", "PS5"], f"entidades: {ev['entidades']}")
    res = [r("xbox", "GTA 6 PS5 Pro vs Xbox Series X performance", vistas=50_000),
           r("ps5", "GTA 6 PS5 vs PS5 Pro performance", vistas=50_000)]
    B.puntuar(res, ev, sin_gente=True, prefs={})
    chk([x["id"] for x in res] == ["ps5", "xbox"], f"«PS5» no se cuenta dentro de «PS5 Pro»: {[x['id'] for x in res]}")


if __name__ == "__main__":
    main()
