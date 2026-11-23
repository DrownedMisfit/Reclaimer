"""
Prueba de «🔎 Buscar material conforme a frases y palabras clave» (editoria/ai/material_por_frases.py), SIN internet:
  · frase → tema + acciones + objetos → consultas en español e inglés («en GTA 5 hay carros que explotan con unos
    cuantos disparos» → «GTA 5 car explosion», «GTA 5 carros explotan»…); palabras corrientes que no son acciones
    («nada», «correo»); el tema dicho con números en palabras («red dead redemption dos»);
  · ranking con CLIP (los modelos ya descargados) sobre imágenes fabricadas: fuego para «explotan», cielo para «vuela»;
    y el orden con codificadores falsos (determinista);
  · plan automático con material local fabricado: una imagen por momento, sin repetir (ni la misma ni una casi igual),
    con su «.creditos.json» (licencia y autor);
  · colocación en el tiempo de la frase: pequeña, con sombra, sobre el video desenfocado (estilo «auto»), nunca a
    pantalla completa (tampoco donde no hay video debajo); TODO en un solo Ctrl+Z; rehacer lo devuelve;
  · resumen: «Quitar» y «Cambiar» (un Ctrl+Z cada uno);
  · versión pública: sin los módulos privados (se simula su ausencia) todo funciona y la lógica no los importa.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_material_por_frases.py <carpeta_salida>
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
    os.environ["USERPROFILE"] = tmp           # (las descargas «de verdad» nunca van a tu carpeta Vídeos)
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import threading  # noqa: E402

import numpy as np  # noqa: E402

# 🔒 SIN internet: cualquier intento de conectarse falla la prueba
import urllib.request  # noqa: E402


def _sin_internet(*_a, **_k):
    print("FALLO: la prueba intentó conectarse a internet")
    os._exit(1)


urllib.request.urlopen = _sin_internet


def _vigilante(segundos: float = 420.0):
    def fin():
        print(f"FALLO: la prueba tardó más de {segundos:.0f} s")
        os._exit(1)
    t = threading.Timer(segundos, fin)
    t.daemon = True
    t.start()


from _material_frases_comun import check  # noqa: E402


from _material_frases_comun import (FuentesLocales, ImagenFalsa, TextoFalso, esperar, fabricar,  # noqa: E402
                                     proyecto)


# ---------------------------------------------------------------- partes
def parte_frases(M):
    e = M.entender("en GTA 5 hay carros que explotan con unos cuantos disparos")
    check(e["tema"] == "GTA 5", f"tema de la frase del usuario: «GTA 5» ({e['tema']})")
    check([a["en"] for a in e["acciones"]] == ["exploding", "shooting"],
          f"acciones: explotan → exploding, disparos → shooting ({[a['en'] for a in e['acciones']]})")
    check([o["en"] for o in e["objetos"]] == ["car"], f"objeto: carros → car ({e['objetos']})")
    qs = M.consultas(e)
    check(qs[0] == "GTA 5 car explosion", f"la primera consulta, la más concreta en inglés ({qs[0]})")
    check("GTA 5 carros explotan" in qs, f"también en español ({qs})")
    check("car explosion" in qs, "para imágenes libres, una general sin el tema")
    check(len(qs) == len({q.lower() for q in qs}) and len(qs) <= 6, "sin consultas repetidas y como mucho 6")
    tx = M.textos_clip(e)
    check(tx[0] == "car explosion, in the video game GTA 5" and tx[1].startswith("en GTA 5"),
          f"lo que se compara con CLIP: descripción en inglés + la frase ({tx})")

    e2 = M.entender("y luego en red dead redemption dos el caballo corre por el bosque")
    check(e2["tema"] == "Red Dead Redemption 2", f"tema con el número en palabras ({e2['tema']})")
    check([o["en"] for o in e2["objetos"]] == ["horse", "forest"] and e2["acciones"][0]["en"] == "running",
          "caballo corre por el bosque → horse, forest, running")
    check(M.consultas(e2)[0] == "Red Dead Redemption 2 horse running", "consulta del caballo")

    e3 = M.entender("En Elden Ring los dragones vuelan sobre el castillo", termino="Elden Ring")
    check(e3["tema"] == "Elden Ring" and e3["objetos"][0]["en"] == "dragon" and e3["acciones"][0]["en"] == "flying",
          "con la palabra clave dada (la de «Dijiste…»): dragones vuelan → dragon flying")

    e4 = M.entender("no hay nada que hacer, mejor te mando un correo", buscar_tema=False)
    check(not e4["acciones"] and not e4["objetos"], "«nada» no es nadar y «correo» no es correr")
    e5 = M.entender("los zombis persiguen a la policía por la ciudad")
    check([o["en"] for o in e5["objetos"]] == ["zombie", "police", "city"] and e5["acciones"][0]["en"] == "chasing",
          "plurales y tildes: zombis, policía, ciudad; persiguen → chasing")
    q5 = M.consultas(e5)
    check(q5[0] == "zombie police chase" and all(len(q.split()) >= 2 for q in q5),
          f"sin tema: varios objetos + acción y ninguna consulta de una sola palabra ({q5})")
    e6 = M.entender("el dragón quema el pueblo", buscar_tema=False)
    check(M.textos_clip(e6)[0] == "dragon fire village", f"texto CLIP con varios objetos ({M.textos_clip(e6)[0]})")
    e7 = M.entender("Fortnite está cada vez más aburrido y repetitivo")
    check(e7["tema"] == "Fortnite" and "Fortnite aburrido repetitivo" in M.consultas(e7),
          f"frase de opinión: el tema y 1–2 palabras de lo que dices ({M.consultas(e7)})")
    check(M.es_juego("GTA 5") and not M.es_juego("Elon Musk"), "el tema es un juego o no")
    check(not M.es_juego("Nintendo") and not M.es_juego("Epic Games") and not M.es_juego("Nintendo Switch")
          and M.es_juego("Mario"), "una empresa, un estudio o una consola no es un juego")
    check(M.es_juego("EA Sports FC 25") and not M.es_empresa("EA Sports FC 25")
          and not M.es_empresa("Microsoft Flight Simulator") and M.es_empresa("PlayStation 6"),
          "un juego que empieza como una empresa sigue siendo juego; una consola con número, no")
    e9 = M.entender("Nintendo anunció un nuevo mando increíble", termino="Nintendo")
    check(M.textos_clip(e9)[0] == "a photo of Nintendo", f"empresa: sin «video game» ({M.textos_clip(e9)[0]})")
    check(e9["resto"] == ["mando", "increíble"] and "Nintendo mando increíble" in M.consultas(e9),
          f"opinión: fuera verbos y vacías («anunció», «nuevo»), quedan sustantivos y adjetivos ({e9['resto']})")
    e8 = M.entender("Elon Musk compró un cohete", termino="Elon Musk")
    check(M.textos_clip(e8)[0] == "rocket, Elon Musk", f"sin «video game» si no es un juego ({M.textos_clip(e8)[0]})")
    # licencias (segunda comprobación antes de bajar)
    for lic, ok in (("cc0", True), ("by", True), ("by-sa", True), ("CC BY 4.0", True), ("pdm", True),
                    ("by-nc", False), ("by-nc-sa", False), ("CC BY-ND 4.0", False), ("", False)):
        check(M.licencia_ok({"license": lic}) is ok, f"licencia «{lic or '(vacía)'}» → {'sí' if ok else 'no'}")
    # una consulta UNA vez por pasada, una pausa entre peticiones y los fallos a la vista
    from editoria.ai import web_images
    llamadas = []

    def falso_openverse(q, **_k):
        llamadas.append(("ov", q))
        if q == "falla":
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return [{"id": f"ov_{q}", "url": f"https://ejemplo.invalid/{q}.jpg", "license": "cc0", "title": q}]

    def falso_commons(q, **_k):
        llamadas.append(("wm", q))
        return []
    viejo = (web_images.search, web_images.search_commons)
    web_images.search, web_images.search_commons = falso_openverse, falso_commons
    try:
        f = M.Fuentes()
        f.PAUSA = 0.05
        t0 = time.monotonic()
        f.buscar_imagenes(["GTA 5 car", "GTA 5"])
        f.buscar_imagenes(["GTA 5 dragon", "GTA 5"])
        check(sum(1 for c in llamadas if c == ("ov", "GTA 5")) == 1,
              f"el tema solo se busca UNA vez en la pasada ({llamadas})")
        check(time.monotonic() - t0 >= 0.05 * (len(llamadas) - 1) - 0.01, "con una pausa entre peticiones")
        f.buscar_imagenes(["falla"])
        check(f.fallos and "429" in f.fallos[0], f"si la web limita, queda apuntado para avisar ({f.fallos})")
    finally:
        web_images.search, web_images.search_commons = viejo
    check(M.accion_de("explotó") == ("exploding", "explosion") and M.objeto_de("camiones") == "truck",
          "acciones con tilde y plurales en -es")


def parte_ranking(M, rutas):
    cands = [{"id": n, "title": n, "thumb_local": r} for n, r in rutas.items() if n != "fuego_copia"]
    r = M.ordenar_por_clip([dict(c) for c in cands], ["fuego, explotan"], TextoFalso(), ImagenFalsa())
    check(r[0]["id"] == "fuego", f"codificadores falsos: «explotan» → la imagen de fuego primero ({[c['id'] for c in r]})")
    check(all("vec" in c and "parecido" in c for c in r), "cada candidato con su huella y su parecido")
    r = M.ordenar_por_clip([dict(c) for c in cands] + [{"id": "rota", "thumb_local": "no_existe.jpg"}],
                           ["sky"], TextoFalso(), ImagenFalsa())
    check(r[0]["id"] == "cielo" and all(c["id"] != "rota" for c in r), "«sky» → cielo; sin miniatura, fuera")

    from editoria.ai import embeddings
    if not (embeddings.is_downloaded("clip_text") and embeddings.is_downloaded("clip_image")):
        print("· (sin los modelos CLIP descargados: se salta el ranking con CLIP real)")
        return False
    e = M.entender("en GTA 5 hay carros que explotan con unos cuantos disparos")
    r = M.ordenar_por_clip([dict(c) for c in cands], ["a huge explosion with fire and flames"])
    check(r[0]["id"] == "fuego", f"CLIP real: explosión → fuego ({[(c['id'], c['parecido']) for c in r]})")
    r = M.ordenar_por_clip([dict(c) for c in cands], ["a blue sky with clouds"])
    check(r[0]["id"] == "cielo", f"CLIP real: cielo azul → cielo ({[(c['id'], c['parecido']) for c in r]})")
    r = M.ordenar_por_clip([dict(c) for c in cands], M.textos_clip(e), ent=e)
    check(r[0]["id"] == "fuego", f"CLIP real con la frase del usuario → fuego ({[(c['id'], c['parecido']) for c in r]})")
    return True


def parte_colocar(app, M, rutas, out, clip_real: bool):
    from editoria.ai.mentions import find_mentions
    ctrl, v1, _words = proyecto(app, out, rutas)
    p = ctrl.project
    menciones = find_mentions(p)
    check(any(m["term"] == "GTA 5" for m in menciones) and any(m["term"] == "Elden Ring" for m in menciones),
          f"«Dijiste…» encuentra GTA 5 y Elden Ring ({[m['term'] for m in menciones]})")
    mos = M.momentos(p, menciones, separacion=8.0)
    check(len(mos) == 3 and all(abs(m["tl"] - t) < 0.05 for m, t in zip(mos, (1.35, 11.35, 24.7))),
          f"un momento por frase, cuando se dice la palabra clave ({[(m['tl'], m['termino']) for m in mos]})")
    check(mos[0]["frase"].startswith("En GTA 5 hay carros") and mos[0]["frase"].endswith("disparos."),
          f"la frase entera, cortada en el punto ({mos[0]['frase']})")
    junto = M.momentos(p, menciones, separacion=30.0)
    check(len(junto) == 1, "con separación grande, uno solo (las imágenes, pocas)")

    fuentes = FuentesLocales(rutas, os.path.join(out, "bajadas"))
    enc = {} if clip_real else {"enc_texto": TextoFalso(), "enc_imagen": ImagenFalsa()}
    progreso = []
    elegidos = M.plan_automatico(mos, fuentes, progress=lambda f, t: progreso.append((f, t)), **enc)
    check(len(elegidos) == 3, f"una imagen para cada momento ({len(elegidos)})")
    check(all(fuentes.consultas[i][0] == q for i, q in enumerate(["GTA 5 car explosion", "Elden Ring dragon flight",
                                                                   "GTA 5 car explosion"])),
          f"cada momento busca con SUS consultas ({[c[0] for c in fuentes.consultas]})")
    ids = [e["item"]["id"] for e in elegidos]
    check(len(set(ids)) == 3, f"sin repetir imágenes ({ids})")
    check(not ({"loc_fuego", "loc_fuego_copia"} <= set(ids)),
          "sin repetir la MISMA escena aunque venga con otro nombre (huella CLIP casi igual)")
    if clip_real:
        check(ids[0] in ("loc_fuego", "loc_fuego_copia"), f"CLIP elige el fuego para «carros que explotan» ({ids[0]})")
    cred = os.path.splitext(elegidos[0]["ruta"])[0] + ".creditos.json"
    datos = json.load(open(cred, encoding="utf-8"))
    check(datos["license_text"].startswith("CC0") and datos["channel"] == "Autor de prueba" and datos["term"] == "GTA 5",
          "«.creditos.json» con licencia, autor y palabra clave")
    check(progreso and progreso[-1][0] == 1.0, "informa del progreso")

    n_antes = len(p.clips)
    pasos_antes = ctrl.undo_stack.count()
    resumen = M.colocar_imagenes(ctrl, elegidos)
    p = ctrl.project
    check(len(resumen) == 3, f"las tres imágenes colocadas ({len(resumen)})")
    check(ctrl.undo_stack.count() == pasos_antes + 1, "todo en UN solo paso del historial")
    vt_idx = {t.id: p.track_index(t.id) for t in p.tracks}
    for r in resumen:
        c = p.clips[r["clip_id"]]
        check(abs(c.start - r["tl"]) < 0.01, f"«{r['termino']}» en el segundo de su frase ({c.start:.2f})")
        check(vt_idx[c.track_id] < vt_idx[v1.id], "en una pista ENCIMA del video de fondo")
        check(c.layout is not None and c.layout.get("h", 1) < 0.9, "nunca a pantalla completa")
        check((c.fx or {}).get("ovl", {}).get("style") == "auto" and "shadow" in (c.fx or {}),
              "estilo «Encima, fondo desenfocado y sombra»")
        check(c.note == M.NOTA, "marcada como material por frases")
    c0 = p.clips[resumen[0]["clip_id"]]
    check(1.5 <= c0.duration <= 6.0, f"dura lo que la frase ({c0.duration:.2f} s)")
    fondo = [c for c in p.clips.values() if c.track_id == v1.id and (c.fx or {}).get("ovl_bg", {}).get("ov") == c0.id]
    check(fondo and all(abs((c.fx or {}).get("blur", 0) - 0.6) < 1e-6 for c in fondo),
          "el video de debajo, desenfocado solo mientras está la imagen")
    c2 = p.clips[resumen[2]["clip_id"]]
    check(c2.start >= 20.0 and c2.layout is not None, "sin video debajo (a los 24 s) también pequeña y con sombra")

    ctrl.undo_stack.undo()
    p = ctrl.project
    check(len(p.clips) == n_antes and not any(c.note == M.NOTA for c in p.clips.values()),
          "UN Ctrl+Z quita todo (y devuelve el fondo sin desenfocar)")
    check(not any((c.fx or {}).get("ovl_bg") for c in p.clips.values()), "sin restos de desenfoque")
    ctrl.undo_stack.redo()
    p = ctrl.project
    check(sum(1 for c in p.clips.values() if c.note == M.NOTA) == 3, "rehacer las devuelve")

    # ---- créditos: las imágenes con su licencia en la descripción
    from editoria.core import credits
    txt = credits.text(credits.collect(p))
    check("🖼 Imágenes:" in txt and "(CC0 (dominio público))" in txt and "Autor de prueba" in txt,
          f"la descripción lleva «Imágenes» con autor y licencia ({txt[:160]!r})")
    # ---- lo ya puesto: no se vuelve a buscar
    check(M.momentos_libres(p, mos) == [], "una segunda pasada no vuelve a esas frases (ya tienen material)")
    claves = M.claves_en_proyecto(p)
    check({e["item"]["id"] for e in elegidos} <= claves, "las claves de lo puesto se leen de sus créditos")
    otra = M.plan_automatico(mos, fuentes, urls_usadas=claves, **enc)
    check(not ({e["item"]["id"] for e in otra} & {e["item"]["id"] for e in elegidos}),
          "aunque se forzara otra pasada, no repite lo ya puesto (claves de los créditos)")
    # ---- momentos recalculados antes de colocar (si editas mientras se busca)
    narr = next(c for c in p.clips.values() if c.media_id in p.transcripts)
    ctrl.move_clips({narr.id: (narr.start + 2.0, narr.track_id)}, "mover la narración")
    nuevos = M.actualizar_momentos(ctrl.project, elegidos)
    check(all(abs(n["momento"]["tl"] - (e["momento"]["tl"] + 2.0)) < 0.02 for n, e in zip(nuevos, elegidos)),
          "si mueves la narración mientras se busca, cada frase va a su sitio nuevo")
    ctrl.undo_stack.undo()
    p = ctrl.project

    # ---- resumen: quitar y cambiar
    r0 = resumen[0]
    alt = r0["alternativas"][0] if r0["alternativas"] else None
    check(alt is not None, "cada elegida trae alternativas para «Cambiar»")
    ruta_alt = M.bajar_elegido(alt, fuentes, r0["termino"], r0["frase"])
    viejo = r0["clip_id"]
    pasos = ctrl.undo_stack.index()
    nuevo = M.cambiar(ctrl, r0, ruta_alt, alt)
    p = ctrl.project
    check(nuevo and viejo not in p.clips and abs(p.clips[nuevo].start - r0["tl"]) < 0.01
          and ctrl.undo_stack.index() == pasos + 1, "«Cambiar»: otra imagen en el mismo momento, un Ctrl+Z")
    check((p.clips[nuevo].fx or {}).get("ovl", {}).get("style") == "auto", "la cambiada, con el mismo estilo")
    r1 = resumen[1]
    cid1 = r1["clip_id"]
    check(M.quitar(ctrl, r1) and cid1 not in ctrl.project.clips, "«Quitar» la borra de la línea de tiempo")
    ctrl.undo_stack.undo()
    check(cid1 in ctrl.project.clips, "y Ctrl+Z la devuelve")

    # ---- manual: una imagen en el cabezal
    pasos = ctrl.undo_stack.index()          # (index: tras un Ctrl+Z, count() aún cuenta el paso deshecho)
    cid = M.poner_en(ctrl, rutas["nieve"], 15.0)
    check(cid and abs(ctrl.project.clips[cid].start - 15.0) < 0.01 and ctrl.undo_stack.index() == pasos + 1,
          "manual: un clic pone la imagen en el cabezal (un Ctrl+Z)")

    # ---- 🙈 censurar: recuadro automático sobre la cara, mover y redimensionar (como el visor), un Ctrl+Z cada cosa
    from _material_frases_comun import CARA, detector_falso, detector_vacio, fabricar_cara
    ruta_cara = fabricar_cara(os.path.join(out, "material"))
    z = M.zona_censura(ruta_cara, detector=detector_falso)
    x, y, w, h = CARA
    check(z["cara"] and abs(z["x"] - (x + w / 2)) < 0.01 and abs(z["y"] - (y + h / 2)) < 0.01
          and z["w"] > w and z["h"] > h, f"recuadro automático justo encima de la cara, con margen ({z})")
    z0 = M.zona_censura(ruta_cara, detector=detector_vacio)
    check(not z0["cara"] and z0["x"] > 0.7 and z0["y"] > 0.7, "sin cara: la esquina típica de la cámara (abajo a la derecha)")
    modelo = os.path.join(os.environ["EDITORIA_MODELOS"], "caras", "face_detection_yunet_2023mar.onnx")
    if os.path.isfile(modelo):          # (sin el modelo se bajaría de internet: entonces se salta)
        zr = M.zona_censura(ruta_cara)
        check(set(zr) >= {"x", "y", "w", "h", "cara"},
              f"con el detector de verdad (ai/tracking) también responde (cara: {zr['cara']})")
    cid_cara = M.poner_en(ctrl, ruta_cara, 18.0)
    pasos = ctrl.undo_stack.index()
    check(M.aplicar_censura(ctrl, cid_cara, z) and ctrl.undo_stack.index() == pasos + 1, "«Censurar»: un Ctrl+Z")
    c = ctrl.project.clips[cid_cara]
    regs = (c.fx or {}).get("blur_regions") or []
    check(len(regs) == 1 and regs[0]["shape"] == "rect" and regs[0]["amount"] == 0.6,
          "con el MISMO sistema que «Tapar (censurar)» (fx blur_regions: cuadro, desenfoque, fuerza 0,6)")
    from editoria.core import transform
    box = c.layout or transform.FULL
    m = ctrl.project.media_of(c)
    esperado = M._a_caja(z, m.width, m.height, box["w"] * ctrl.project.width, box["h"] * ctrl.project.height)
    check(all(abs(regs[0][k] - esperado[k]) < 1e-3 for k in "xywh") and regs[0]["x"] > 0.5,
          f"en la caja del clip, donde está la cara en la imagen ({ {k: round(regs[0][k], 3) for k in 'xywh'} })")
    fx = dict(c.fx)
    fx["blur_regions"] = [dict(regs[0], x=0.3, y=0.4, w=0.2, h=0.25, mode="pixel", shape="ellipse")]
    ctrl.set_clip_props([cid_cara], "Mover desenfoque", fx=fx)      # (lo que hace el visor al soltar los tiradores)
    r2 = ctrl.project.clips[cid_cara].fx["blur_regions"][0]
    check((r2["x"], r2["y"], r2["w"], r2["h"], r2["mode"], r2["shape"]) == (0.3, 0.4, 0.2, 0.25, "pixel", "ellipse"),
          "se mueve, cambia de tamaño y pasa a círculo pixelado como cualquier zona tapada")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    check(not (ctrl.project.clips[cid_cara].fx or {}).get("blur_regions"), "Ctrl+Z quita el movimiento y la censura")
    pasos = ctrl.undo_stack.index()
    cid2 = M.poner_en(ctrl, ruta_cara, 19.0, censura=z)
    check(cid2 and len(ctrl.project.clips[cid2].fx.get("blur_regions") or []) == 1
          and ctrl.undo_stack.index() == pasos + 1, "un resultado marcado se censura AL PONERLO, en el mismo Ctrl+Z")

    # ---- lo que ya está en la línea de tiempo no se repite
    usados = [e["item"]["vec"] for e in elegidos]
    otra = M.plan_automatico(mos[:1], fuentes, usados=usados, urls_usadas={e["item"]["id"] for e in elegidos}, **enc)
    check(not otra or otra[0]["item"]["id"] not in ids, "una segunda pasada no repite lo ya puesto")


def parte_publica():
    """Sin los módulos privados (se simula su ausencia): la lógica importa y funciona; y nunca los importa."""
    codigo = r'''
import sys, os
sys.path.insert(0, %r)
for m in ("editoria.ai.clip_search", "editoria.ai.clip_download", "editoria.ui.clips_internet"):
    sys.modules[m] = None          # (como si no existieran: la versión pública)
from editoria.ai import material_por_frases as M
assert M.hay_videos() is False, "hay_videos sin módulos privados"
e = M.entender("en GTA 5 hay carros que explotan con unos cuantos disparos")
assert M.consultas(e)[0] == "GTA 5 car explosion"
assert not any(m in sys.modules and sys.modules[m] is not None for m in
               ("editoria.ai.clip_search", "editoria.ai.clip_download", "editoria.ui.clips_internet"))
print("OK")
''' % ROOT
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ), timeout=120)
    check(r.returncode == 0 and "OK" in r.stdout, f"versión pública sin módulos privados ({r.stderr[-400:]})")
    fuente = open(os.path.join(ROOT, "editoria", "ai", "material_por_frases.py"), encoding="utf-8").read()
    privados = {"clip_search", "clip_download", "clips_internet", "sound_search", "sounds_internet",
                "character_search"}
    importa = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.ImportFrom):
            importa |= {(nodo.module or "").split(".")[-1]} | {a.name for a in nodo.names}
        elif isinstance(nodo, ast.Import):
            importa |= {a.name.split(".")[-1] for a in nodo.names}
    check(not (importa & privados), f"la lógica pública no importa nada privado ({importa & privados})")
    from editoria.ai import material_por_frases as M
    hay = all(os.path.isfile(os.path.join(ROOT, "editoria", "ai", f))
              for f in ("clip_search.py", "clip_download.py", "material_videos.py"))
    check(M.hay_videos() == hay, f"hay_videos() mira si están los módulos privados ({hay})")


def main():
    _vigilante(420)
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp", "material_frases"))
    os.makedirs(out, exist_ok=True)
    import atexit
    atexit.register(shutil.rmtree, out, True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import material_por_frases as M

    rutas = fabricar(os.path.join(out, "material"))
    parte_frases(M)
    clip_real = parte_ranking(M, rutas)
    parte_colocar(app, M, rutas, out, clip_real)
    parte_publica()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
