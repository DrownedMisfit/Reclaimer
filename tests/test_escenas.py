"""
Prueba de 🎬 Escenas (core/scenes.py, image_anim.plan_fase, controller.apply_scene / remove_scene, la página
ui/scenes_page.py y su sitio en la ventana principal). Sin ventanas (offscreen), sin sonido, sin internet.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_escenas.py [carpeta_temporal]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = sys.argv[1] if len(sys.argv) > 1 else None
if _BASE:
    os.makedirs(_BASE, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="escenas_", dir=_BASE)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "datos")
os.environ["RECLAIMER_RAIZ"] = _TMP
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from editoria.core import image_anim as A  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core import scenes as S  # noqa: E402
from editoria.core import sfx  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Project  # noqa: E402


def pump(app, s=0.2):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def png(nombre: str, color) -> str:
    im = QImage(200, 300, QImage.Format_ARGB32)
    im.fill(Qt.transparent)
    for y in range(40, 280):
        for x in range(50, 150):
            im.setPixelColor(x, y, color)
    ruta = os.path.join(_TMP, nombre)
    assert im.save(ruta)
    return ruta


def prueba_nucleo():
    caja = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.6, "fit": "contain", "bg": "none"}
    e = A.plan_fase("entrada", "abajo", caja, 0.6)["layout_kf"]
    assert e[0]["y"] >= 1.0 - 1e-6 and abs(e[-1]["y"] - caja["y"]) < 1e-6, "entra desde abajo hasta su sitio"
    s = A.plan_fase("salida", "izquierda", caja, 0.8)["layout_kf"]
    assert abs(s[0]["x"] - caja["x"]) < 1e-6 and s[-1]["x"] + s[-1]["w"] <= 1e-6, "se va por la izquierda"
    ap = A.plan_fase("entrada", "aparece", caja, 0.5)
    assert ap["op_kf"][0]["v"] == 0.0 and ap["op_kf"][-1]["v"] == 1.0 and not ap["layout_kf"]
    m = A.plan_fase("salida", "muere", caja, 1.0)
    assert m["op_kf"][-1]["v"] == 0.0 and m["fx"]["shake"] > 0
    esc = S.nueva(15, 19)
    assert esc["fondo"] == "blur" and S.largo(esc) == 4.0
    a1 = S.nuevo_actor(esc, "mc")
    a2 = S.nuevo_actor(esc, "elite")
    assert a1["caja"]["x"] < 0.5 < a2["caja"]["x"] + a2["caja"]["w"], "uno a la izquierda y otro a la derecha"
    assert abs(S.duracion_actor(a1) - 4.0) < 1e-6
    S.poner_fase(a1, "accion", "disparo", 1.5)
    S.fijar(a1["fases"][2])                              # el «Quieto», fijado a mano en 2,5 s: 0,6 + 1,5 + 2,5 > 4
    a1["fases"][2]["dur"] = 2.5                          # (pasa del final de la escena: se corta)
    S.poner_fase(a2, "salida", "muere", 1.0)
    a2["fases"][1]["dur"] = 2.4
    assert [f["tipo"] for f in a2["fases"]] == ["entrada", "accion", "salida"]
    S.poner_fase(a2, "entrada", "derecha")              # cambiar la entrada no añade otra
    assert sum(1 for f in a2["fases"] if f["tipo"] == "entrada") == 1
    pz = S.piezas(esc)
    assert all(15.0 - 1e-6 <= p["a"] < p["b"] <= 19.0 + 1e-6 for p in pz)
    ult = [p for p in pz if p["actor"] == a1["id"]][-1]
    assert ult["fase"]["anim"] == "ninguna" and abs(ult["b"] - 19.0) < 1e-6, "lo que pasa del final se corta"
    assert S.id_de_nota(S.nota(esc["id"])) == esc["id"] and S.id_de_nota("🔑⚡ algo") is None
    # sin tocar duraciones a mano: «Quieto» es elástico, así que disparar y morir caben dentro de la escena
    e2 = S.nueva(15, 19)
    b1, b2 = S.nuevo_actor(e2, "mc"), S.nuevo_actor(e2, "elite")
    S.poner_fase(b1, "accion", "disparo", 1.5)
    S.poner_fase(b2, "salida", "muere", 1.0)
    pz2 = S.piezas(e2)
    assert [p["fase"]["anim"] for p in pz2 if p["actor"] == b1["id"]] == ["abajo", "disparo", "ninguna"]
    muere = [p for p in pz2 if p["actor"] == b2["id"] and p["fase"]["anim"] == "muere"]
    assert muere and abs(muere[0]["a"] - 18.0) < 1e-6 and abs(muere[0]["b"] - 19.0) < 1e-6, "muere al final"
    e2["b"] = 25.0                                    # alargar el tramo: nadie desaparece antes
    assert max(p["b"] for p in S.piezas(e2) if p["actor"] == b2["id"]) == 25.0
    print("✓ núcleo: entradas/salidas con dirección, fases en orden, piezas dentro de la escena")


def esperar(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def proyecto(app):
    ctrl = ProjectController()
    fondo = os.path.join(_TMP, "fondo.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=640x360:r=30:d=10", "-f", "lavfi", "-i", "sine=f=220:d=10", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", fondo],
                   check=True, creationflags=media_tools.NO_WINDOW)
    (fid,) = ctrl.import_now([fondo])
    esperar(app, ctrl)
    v1 = next(t for t in ctrl.project.tracks if t.name == "V1")
    ctrl.add_media([fid], v1.id, 0.0)
    (mc,) = ctrl.import_now([png("jefe.png", Qt.darkGreen)])
    (el,) = ctrl.import_now([png("elite.png", Qt.darkMagenta)])
    (snd,) = ctrl.import_now([sfx.path_for("golpe")])
    esperar(app, ctrl)
    return ctrl, fid, mc, el, snd


def montar(esc, mc, el, snd):
    a1 = S.nuevo_actor(esc, mc)
    a2 = S.nuevo_actor(esc, el)
    S.poner_fase(a1, "accion", "disparo", 2.0)
    S.poner_fase(a2, "entrada", "derecha")
    S.poner_fase(a2, "salida", "muere", 1.2)
    S.nuevo_sonido(esc, snd, 1.5, 0.5)
    return a1, a2


def prueba_controlador(app):
    ctrl, fid, mc, el, snd = proyecto(app)
    p = ctrl.project
    esc = S.nueva(2.0, 6.0, "Tiroteo")
    montar(esc, mc, el, snd)
    ids = ctrl.apply_scene(esc)
    assert ids, "no se aplicó"
    mios = ctrl.scene_clips(p, esc["id"])
    assert len(mios) == len(ids)
    v1i = p.track_index(next(t.id for t in p.tracks if t.name == "V1"))
    fondo = [c for c in mios if p.media[c.media_id].gen.get("kind") == "adjust"]
    assert len(fondo) == 1 and (fondo[0].fx or {}).get("blur") == S.BLUR, "fondo desenfocado (capa de ajuste)"
    assert abs(fondo[0].start - 2.0) < 1e-6 and abs(fondo[0].end - 6.0) < 1e-6
    i_fondo = p.track_index(fondo[0].track_id)
    i_mc = {p.track_index(c.track_id) for c in mios if c.media_id == mc}
    i_el = {p.track_index(c.track_id) for c in mios if c.media_id == el}
    assert len(i_mc) == 1 and len(i_el) == 1, "cada personaje en UNA pista (sus fases seguidas)"
    assert v1i > i_fondo > i_mc.pop() > i_el.pop(), "fondo encima del video; el primero, debajo del segundo"
    sonidos = [c for c in mios if p.track(c.track_id).kind == TRACK_AUDIO]
    assert len(sonidos) == 1 and abs(sonidos[0].start - 3.5) < 1e-6
    fases_mc = sorted((c for c in mios if c.media_id == mc), key=lambda c: c.start)
    assert [round(c.start, 2) for c in fases_mc] == [2.0, 2.6, 4.6], [c.start for c in fases_mc]
    fin_el = max(c.end for c in mios if c.media_id == el)
    assert abs(fin_el - 6.0) < 1e-6, "el Elite muere al final de la escena"
    # clic en un clip de la escena = el grupo entero
    assert set(ctrl.linked_ids([fases_mc[0].id])) >= {c.id for c in mios}
    assert all(abs(x.end - y.start) < 1e-6 for x, y in zip(fases_mc, fases_mc[1:])), "sin huecos entre fases"
    assert esc["id"] in p.scenes and p.scenes[esc["id"]]["nombre"] == "Tiroteo"
    # volver a aplicar con cambios: sustituye (no duplica) · fondo oscurecido
    esc2 = S.copia(p.scenes[esc["id"]])
    esc2["fondo"] = "dark"
    esc2["sonidos"] = []
    ids2 = ctrl.apply_scene(esc2)
    mios2 = ctrl.scene_clips(p, esc["id"])
    assert len(mios2) == len(ids2) == len(ids) - 1
    f2 = next(c for c in mios2 if p.media[c.media_id].gen.get("kind") == "adjust")
    assert (f2.color or {}).get("exposure") == S.OSCURO and "blur" not in (f2.fx or {})
    # deshacer / rehacer: clips y definición de la escena
    ctrl.undo_stack.undo()
    assert len(ctrl.scene_clips(p, esc["id"])) == len(ids) and p.scenes[esc["id"]]["fondo"] == "blur"
    ctrl.undo_stack.undo()
    assert not ctrl.scene_clips(p, esc["id"]) and esc["id"] not in p.scenes
    ctrl.undo_stack.redo()
    assert len(ctrl.scene_clips(p, esc["id"])) == len(ids)
    # se guarda con el proyecto
    q = Project.from_dict(p.to_dict())
    assert esc["id"] in q.scenes and len(q.scenes[esc["id"]]["actores"]) == 2
    # si sus clips se mueven en el editor (o se recorre lo de antes), al abrirla la escena está en su sitio nuevo
    est, aviso = ctrl.scene_state(esc["id"])
    assert aviso == "" and abs(est["a"] - 2.0) < 1e-6
    for c in ctrl.scene_clips(p, esc["id"]):
        c.start += 1.0
    est, aviso = ctrl.scene_state(esc["id"])
    assert aviso == "" and abs(est["a"] - 3.0) < 1e-6, (aviso, est["a"])
    uno = ctrl.scene_clips(p, esc["id"])[0]
    uno.duration *= 0.5
    assert ctrl.scene_state(esc["id"])[1] == "retocada"
    ctrl.undo_stack.undo()                            # (los cambios hechos a mano arriba no pasan por el deshacer)
    ctrl.undo_stack.redo()
    ctrl.remove_scene(esc["id"])
    assert esc["id"] not in p.scenes and not ctrl.scene_clips(p, esc["id"])
    ctrl.undo_stack.undo()
    assert esc["id"] in p.scenes
    print("✓ aplicar: fondo desenfocado/oscurecido, una pista por personaje en orden, sonido, sin duplicar; deshacer; "
          "se guarda en el proyecto")
    return ctrl, esc


def prueba_exportar(ctrl, esc):
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    out = os.path.join(_TMP, "escena.mp4")
    opts = ExportOptions(path=out, width=640, height=360, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
    args, _t = build_command(ctrl.project, opts, media_tools.ffmpeg(), os.path.join(_TMP, "filtro.txt"))
    r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
    if r.returncode != 0:
        print(r.stderr.decode(errors="replace")[-2500:])
    assert r.returncode == 0

    def fotograma(t):
        raw = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", out,
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "160x90", "-"],
                             capture_output=True, creationflags=media_tools.NO_WINDOW).stdout
        return np.frombuffer(raw, np.uint8).reshape(90, 160).astype(np.int16)
    # el primero entra desde abajo: al principio de la escena su zona (izquierda) es distinta que ya en su sitio
    inicio, sitio = fotograma(2.05), fotograma(3.0)
    assert np.abs(inicio[20:80, 10:60] - sitio[20:80, 10:60]).mean() > 3, "el personaje no entró en el video"
    print("✓ se exporta y el personaje se mueve en el video")


class _Ventana(QMainWindow):
    """Lo que usa la página de la ventana principal."""
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.engine = type("E", (), {"time": 1.0, "seek": lambda *_a: None, "pause": lambda *_a: None})()


def prueba_pagina(app):
    from editoria.ui.scenes_page import ScenesPage, estado_en
    ctrl, fid, mc, el, snd = proyecto(app)
    p = ctrl.project
    p.mark_in, p.mark_out = 1.0, 5.0                    # el tramo marcado con I/O
    win = _Ventana(ctrl)
    pg = ScenesPage(win, None)
    assert (pg.escena["a"], pg.escena["b"]) == (1.0, 5.0) and pg.escena["fondo"] == "blur"
    assert pg.lista_img.count() == 2 and pg.lista_img.item(0).text().startswith("✓"), "recortes marcados con ✓"
    t0 = time.time()                                  # el fondo: el fotograma del tramo, renderizado aparte
    while getattr(pg, "_fondo_pix", None) is None and time.time() - t0 < 30:
        pump(app, 0.2)
    assert getattr(pg, "_fondo_pix", None) is not None and not pg._fondo_pix.isNull(), "no se preparó el fondo"
    pg._añadir_actor(mc)
    pg.tl.sel = ("fase", pg.escena["actores"][0]["fases"][0])   # (una fase elegida en la línea de la escena…)
    pg._añadir_actor(el)                                        # (…y añadir otro personaje: antes daba error)
    assert len(pg._items) == 2 and pg.tl.sel[0] == "actor"
    act = pg.escena["actores"][1]
    pg._elegir("actor", act)
    pg.a_salida.setCurrentIndex(pg.a_salida.findData("muere"))
    pg._fase_extrema("salida", "muere")
    pg._añadir_accion("disparo")
    assert [f["tipo"] for f in act["fases"]] == ["entrada", "accion", "accion", "salida"]
    pg.tl.t = 2.0
    pg._añadir_sonido(sfx.path_for("golpe"))
    assert pg.escena["sonidos"] and abs(pg.escena["sonidos"][0]["t"] - 2.0) < 1e-6
    # vista previa: en el segundo 0,05 el que entra desde abajo aún está abajo; luego en su sitio
    st0, st1 = estado_en(pg.escena, 0.05), estado_en(pg.escena, 1.5)
    a0 = pg.escena["actores"][0]["id"]
    assert st0[a0]["box"]["y"] > st1[a0]["box"]["y"] + 0.3
    pg.vista_previa_en(0.05)
    assert not pg._items[a0].editable and pg._items[a0].pos().y() > pg.H * 0.6
    pg._poner_en_reposo()
    assert pg._items[a0].editable
    # arrastrar al personaje en el visor cambia su caja
    it = pg._items[a0]
    it.setPos(pg.W * 0.5, pg.H * 0.1)
    pg._actor_movido(a0)
    assert abs(pg.escena["actores"][0]["caja"]["x"] - 0.5) < 0.01
    # la línea de tiempo de la escena: bloques por fase y por sonido, en su sitio
    pg.tl.resize(900, 200)
    bl = pg.tl.bloques()
    assert sum(1 for b in bl if b[1] == "fase") == 2 + 4 and sum(1 for b in bl if b[1] == "sonido") == 1
    # reproducir unos fotogramas (sin sonido en pruebas)
    pg.tl.t = 0.0
    pg.reproducir()
    pump(app, 0.3)
    pg.parar()
    assert pg.tl.t > 0.1
    # aplicar
    assert pg.sucia and pg.aplicar() and not pg.sucia
    eid = pg.escena["id"]
    assert eid in p.scenes and ctrl.scene_clips(p, eid)
    assert pg.sel_escena.findData(eid) >= 0
    # abrirla otra vez (como con doble clic) trae lo mismo
    pg2 = ScenesPage(win, p.scenes[eid])
    assert len(pg2.escena["actores"]) == 2 and not pg2.sucia
    pg2.deleteLater()
    print("✓ página: tramo de I/O, añadir personajes y sonido, fases, vista previa, arrastrar, reproducir, aplicar")


def prueba_donde_y_cuanto(app):
    """Crear la animación primero y luego elegir dónde va y cuánto dura; copias; 📚 mis animaciones."""
    from editoria.ui.scenes_page import ScenesPage
    ctrl, fid, mc, el, snd = proyecto(app)
    p = ctrl.project
    win = _Ventana(ctrl)
    pg = ScenesPage(win, None)                        # sin tramo marcado: en el cabezal (1 s), 4 s
    assert (pg.escena["a"], S.largo(pg.escena)) == (1.0, 4.0)
    pg._añadir_actor(mc)
    pg._añadir_actor(el)
    act = pg.escena["actores"][0]
    pg._elegir("actor", act)
    pg._añadir_accion("disparo")
    pg._elegir("actor", pg.escena["actores"][1])
    pg._fase_extrema("salida", "muere")
    pg.tl.t = 1.0
    pg._añadir_sonido(sfx.path_for("golpe"))
    disparo0 = next(f["dur"] for f in act["fases"] if f["anim"] == "disparo")
    # cuánto dura: se estira entera, en proporción
    pg.dura.setValue(8.0)
    assert abs(S.largo(pg.escena) - 8.0) < 1e-6
    assert abs(next(f["dur"] for f in act["fases"] if f["anim"] == "disparo") - disparo0 * 2) < 1e-3
    assert abs(pg.escena["sonidos"][0]["t"] - 2.0) < 1e-3, "el sonido se recoloca en proporción"
    # dónde: se mueve entera (la duración no cambia)
    pg.desde.setValue(0.5)
    assert abs(pg.escena["a"] - 0.5) < 1e-6 and abs(S.largo(pg.escena) - 8.0) < 1e-6
    p.mark_in, p.mark_out = 2.0, 5.0
    pg._usar_marcas()                                 # en el tramo I/O, durando lo que dura
    assert (pg.escena["a"], S.largo(pg.escena)) == (2.0, 3.0)
    pg._llenar_donde()
    assert any("cabezal" in a.text() for a in pg.menu_donde.actions())
    # una copia en cada momento (un solo paso de Ctrl+Z)
    n0 = len(p.scenes)                                # (la escena está en 2–5 s)
    pg._copias_en([1.0, 2.0, 4.0, 7.0, 8.0])           # 2 y 4 caen en la original; 8 se solapa con la del 7
    starts = sorted(e["a"] for e in p.scenes.values())
    assert len(p.scenes) == n0 + 2 and starts == [1.0, 7.0], starts
    pg._copias_en([7.0])                              # repetir no duplica
    assert len(p.scenes) == n0 + 2
    ctrl.undo_stack.undo()
    assert len(p.scenes) == n0
    # 📚 guardarla y usarla en otro sitio con otra duración (y en otro proyecto: por la ruta de los archivos)
    pg.nombre.setText("Tiroteo")
    pg.escena["nombre"] = "Tiroteo"
    pg._guardar_plantilla()
    tp = next(t for t in S.plantillas() if t["nombre"] == "Tiroteo")
    assert len(tp["actores"]) == 2 and len(tp["sonidos"]) == 1 and all(os.path.isfile(a["ruta"]) for a in tp["actores"])
    pg._usar_plantilla(tp, 7.0, 2.0)
    assert (pg.escena["a"], S.largo(pg.escena)) == (7.0, 2.0) and len(pg.escena["actores"]) == 2 and pg.sucia
    ctrl2, *_r = proyecto(app)                        # otro proyecto: importa los archivos al usarla
    e2, faltan = S.desde_plantilla(tp, 3.0, ctrl2.media_for_path)
    assert not faltan and len(e2["actores"]) == 2 and all(a["media_id"] in ctrl2.project.media for a in e2["actores"])
    assert ctrl2.apply_scene(e2)
    snd2 = ctrl2.project.media[e2["sonidos"][0]["media_id"]]
    assert snd2.category != "Escenas", snd2.category        # (un sonido no se clasifica como personaje)
    assert tp["sonidos"][0].get("sfx") == "golpe", "un ✦ de Reclaimer se guarda por su nombre (se regenera)"
    assert S.existe_plantilla("tiroteo"), "Windows no distingue mayúsculas"
    # otra copia en el cabezal: escena nueva (otro id) que se edita aquí
    eid = pg.escena["id"]
    pg.aplicar()
    pg._copia_en(1.0)
    assert pg.escena["id"] != eid and pg.escena["a"] == 1.0 and pg.sucia
    S.borrar_plantilla(tp)
    assert not any(t["nombre"] == "Tiroteo" for t in S.plantillas())
    print("✓ crear primero y elegir dónde y cuánto: Dura estira, Empieza mueve, I/O, copias en cada momento, "
          "📚 guardar y usar (también en otro proyecto)")


def prueba_mas(app):
    """«＋» de cada fila, acciones por categoría, «Disparar a…», cortar, imán, grabar mi movimiento, soltar
    personajes, «Aplicar en …»."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    from editoria.ui.scenes_page import ScenesPage, estado_en
    ctrl, fid, mc, el, snd = proyecto(app)
    p = ctrl.project
    p.mark_in, p.mark_out = 1.0, 7.0
    win = _Ventana(ctrl)
    pg = ScenesPage(win, None)
    pg.resize(1400, 800)
    pg.tl.resize(1000, 200)
    assert "Aplicar en 00:01" in pg.b_aplicar.text() and "00:07" in pg.b_aplicar.text(), pg.b_aplicar.text()
    # soltar personajes en el visor: aparecen donde se sueltan
    pg.lista_img.setCurrentRow(0)
    pg._soltar_personaje(pg.lista_img, 0.25, 0.5)
    pg.lista_img.setCurrentRow(1)
    pg._soltar_personaje(pg.lista_img, 0.75, 0.5)
    a1, a2 = pg.escena["actores"]
    assert abs(a1["caja"]["x"] + a1["caja"]["w"] / 2 - 0.25) < 0.01 and abs(a2["caja"]["x"] + a2["caja"]["w"] / 2 - 0.75) < 0.01
    # «＋»: una acción de cada categoría en la línea roja
    for clave in ("camina", "conduce", "pop"):
        pg.tl.t = 1.0
        f = pg._accion_en(a1, clave)
        assert f["anim"] == clave and pg.tl.sel == ("fase", f)
    # (la última que pones queda en la línea roja y empuja a las de antes)
    assert [f["anim"] for f in a1["fases"]] == ["abajo", "ninguna", "pop", "conduce", "camina", "ninguna"],         [f["anim"] for f in a1["fases"]]
    # 🎯 disparar a: el otro recibe el golpe justo cuando le llega el disparo y cae
    pg.tl.t = 3.0
    pg._disparar(a1, a2, True)
    pz = [x for x in S.piezas(pg.escena) if x["actor"] == a2["id"]]
    golpe = next(x for x in pz if x["fase"]["anim"] == "golpe")
    assert abs(golpe["a"] - (pg.escena["a"] + 3.12)) < 0.02 and pz[-1]["fase"]["anim"] == "muere"
    # ✂ cortar con Ctrl+B en la línea de la escena (la fase elegida)
    n0 = len(a1["fases"])
    disparo = next(f for f in a1["fases"] if f["anim"] == "disparo")
    pg.tl.sel = ("fase", disparo)
    pg.tl.t = 3.5
    pg.tl.setFocus()
    QTest.keyClick(pg.tl, Qt.Key_B, Qt.ControlModifier)
    assert len(a1["fases"]) == n0 + 1 and sum(1 for f in a1["fases"] if f["anim"] == "disparo") == 2
    # 🔍 acercar y desplazar · 🧲 imán a la línea roja
    x_antes = pg.tl.x_de(2.0)
    pg.tl.zoom, pg.tl.off = 4.0, 1.0
    assert pg.tl.x_de(2.0) - pg.tl.IZQ > (x_antes - pg.tl.IZQ) * 1.5
    pg.tl.t = 2.0
    cerca = 2.0 + 3 / pg.tl._pps()
    assert pg.tl._imantar(cerca) == 2.0, "el imán no pegó a la línea roja"
    assert pg.tl._imantar(2.0 + 40 / pg.tl._pps()) != 2.0
    pg.tl.zoom, pg.tl.off = 1.0, 0.0
    # 🎥 grabar mi movimiento: se mueve con el ratón mientras suena la escena
    pg.tl.t = 4.5
    pg._armar_grabacion(a1)
    it = pg._items[a1["id"]]
    assert it.grabar is not None
    it.grabar("pulsa", it)
    pg.parar()                                     # (la prueba lleva el tiempo a mano)
    x0 = it.pos()
    for k in range(1, 11):
        pg.tl.t = 4.5 + k * 0.1
        it.setPos(x0 + QPointF(k * 6.0, -k * 2.0))
        pg._muestra_grabacion()
    pg._grab["grabando"] = True
    it.grabar("suelta", it)
    propia = next(f for f in a1["fases"] if f["anim"] == "propia")
    assert abs(propia["dur"] - 1.0) < 0.05 and propia["kf"][-1]["dx"] > 0.05, propia
    st = estado_en(pg.escena, 5.45)
    assert st[a1["id"]]["box"]["x"] > estado_en(pg.escena, 4.55)[a1["id"]]["box"]["x"] + 0.05, "no se mueve"
    pg._elegir("fase", (a1, propia))
    assert pg.b_guardar_mov.isVisibleTo(pg)
    pg._guardar_movimiento()
    movs = S.movimientos()
    assert movs and movs[0]["kf"], "no se guardó en mis movimientos"
    pg.tl.t = 0.7
    f2 = pg._insertar(a2, S.fase_de_movimiento(movs[0]))
    assert f2["anim"] == "propia" and f2["kf"] == movs[0]["kf"]
    # ↔ voltear
    pg._elegir("actor", a1)
    pg.a_flip.setChecked(True)
    assert a1["caja"].get("flip_h") is True and pg._items[a1["id"]].flip
    # aplicar: se exporta bien con todo esto (claves de muchas acciones seguidas)
    assert pg.aplicar() and pg.resaltar and pg.resaltar[1] == 1.0
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    out = os.path.join(_TMP, "escena_mas.mp4")
    opts = ExportOptions(path=out, width=640, height=360, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
    args, _t = build_command(p, opts, media_tools.ffmpeg(), os.path.join(_TMP, "filtro_mas.txt"))
    r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
    if r.returncode != 0:
        print(r.stderr.decode(errors="replace")[-2000:])
    assert r.returncode == 0
    for mv in movs:
        os.remove(mv["archivo"])
    print("✓ «＋»: acciones por categoría en la línea roja, disparar a (el otro cae a tiempo), cortar Ctrl+B, acercar "
          "e imán, grabar mi movimiento y guardarlo, voltear, soltar personajes, «Aplicar en…» y se exporta")


def prueba_comparativa(app):
    """⚖ Comparativa: dos tomas (A y B) con su etiqueta, en los cuatro modos; encima de todo y sin tapar tu video."""
    from editoria.ui.scenes_page import ScenesPage
    ctrl, fid, mc, el, snd = proyecto(app)
    p = ctrl.project
    otro = os.path.join(_TMP, "remake.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=s=640x360:r=30:d=12", "-c:v", "libx264", "-preset", "ultrafast", otro],
                   check=True, creationflags=media_tools.NO_WINDOW)
    (rid,) = ctrl.import_now([otro])
    esperar(app, ctrl)
    p.mark_in, p.mark_out = 2.0, 6.0
    win = _Ventana(ctrl)
    pg = ScenesPage(win, None)
    pg.sel_escena.setCurrentIndex(pg.sel_escena.findData("__nueva_comp__"))
    assert S.es_comparativa(pg.escena) and pg.cuerpo.currentIndex() == 1 and not pg.fondo.isVisibleTo(pg)
    ed = pg.comp_editor
    assert not pg.aplicar(), "sin las dos tomas no se aplica"
    ed.campos["A"][0].setCurrentIndex(ed.campos["A"][0].findData(fid))
    ed.campos["A"][1].setValue(1.0)
    ed.campos["B"][0].setCurrentIndex(ed.campos["B"][0].findData(rid))
    ed.campos["B"][2].setText("Remake (2026)")
    ed._cambio("B", "etiqueta")
    assert pg.escena["comp"]["A"]["etiqueta"], "la etiqueta de entrada es el nombre de la toma"
    t0 = time.time()
    while ed._imgs.get("A") is None and time.time() - t0 < 20:
        pump(app, 0.1)
    assert ed._imgs.get("A") is not None and ed._imgs.get("B") is not None, "sin vista previa"
    v1 = next(t for t in p.tracks if t.name == "V1")
    antes_v1 = [c.id for c in p.clips_on(v1.id)]
    assert pg.aplicar()
    eid = pg.escena["id"]
    mios = ctrl.scene_clips(p, eid)
    vids = [c for c in mios if c.text is None]
    textos = [c for c in mios if c.text is not None]
    assert len(vids) == 2 and len(textos) == 2, (len(vids), len(textos))
    assert {c.layout["x"] for c in vids} == {0.0, 0.5}, "lado a lado"
    a_clip = next(c for c in vids if c.media_id == fid)
    assert abs(a_clip.source_in - 1.0) < 1e-6 and a_clip.volume == 0.0
    assert [c.id for c in p.clips_on(v1.id)] == antes_v1, "tapó o cortó tu video"
    assert all(p.track_index(c.track_id) < p.track_index(v1.id) for c in vids), "debe ir encima"
    assert ctrl.scene_state(eid)[1] == "", "al reabrirla no debe salir como retocada"
    for modo, n_vid in (("arriba", 2), ("fundido", 2), ("alternar", 2)):
        ed.modo.setCurrentIndex(ed.modo.findData(modo))
        assert pg.aplicar()
        mios = ctrl.scene_clips(p, eid)
        vids = [c for c in mios if c.text is None]
        assert len(vids) >= n_vid, (modo, len(vids))
        if modo == "fundido":
            arriba_a = next(c for c in vids if c.media_id == fid)
            assert arriba_a.op_kf and arriba_a.op_kf[-1]["v"] == 0.0, "A no se desvanece"
        if modo == "alternar":
            assert [c.media_id for c in sorted(vids, key=lambda c: c.start)][:2] == [fid, rid]
    # se reabre como comparativa y se exporta
    pg2 = ScenesPage(win, p.scenes[eid])
    assert pg2.cuerpo.currentIndex() == 1 and pg2.comp_editor.modo.currentData() == "alternar"
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    out = os.path.join(_TMP, "comparativa.mp4")
    opts = ExportOptions(path=out, width=640, height=360, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
    args, _t = build_command(p, opts, media_tools.ffmpeg(), os.path.join(_TMP, "filtro_comp.txt"))
    r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    print("✓ comparativa: dos tomas con etiqueta (lado a lado, arriba y abajo, fundido, alternar), encima de todo sin "
          "tapar tu video, vista previa, se reabre y se exporta")


def prueba_ventana_principal(app):
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1400, 900)
    pump(app, 0.4)
    assert "scenes" in win.page_buttons
    visibles = {k for k, d in win.docks.items() if d.isVisible()}
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    assert pg is not None and win.central_stack.currentWidget() is pg
    assert not any(d.isVisible() for k, d in win.docks.items() if k != "guide" and not d.isFloating())
    win.go_page("edit")
    pump(app, 0.3)
    assert win._scenes_widget is None and win.central_stack.currentWidget() is win.preview
    assert {k for k, d in win.docks.items() if d.isVisible()} == visibles, "el editor vuelve como estaba"
    # 🔑 «Crear escena aquí» abre la página con ese tramo
    # 📚 desde el clic derecho de una palabra clave: una animación guardada, puesta tal cual
    ctrl = win.ctrl
    (img,) = ctrl.import_now([png("solo.png", Qt.darkCyan)])
    e = S.nueva(0, 2, "Saludo")
    S.nuevo_actor(e, img)
    S.guardar_plantilla(e, ctrl.project, "Saludo")
    tp = next(t for t in S.plantillas() if t["nombre"] == "Saludo")
    ids = win.put_template(tp["archivo"], 1.5)
    assert ids and any(abs(x["a"] - 1.5) < 1e-6 for x in ctrl.project.scenes.values())
    S.borrar_plantilla(tp)
    win.timeline.scene_requested.emit(3.0, 6.5)
    pump(app, 0.2)
    assert win._scenes_widget is not None and (win._scenes_widget.escena["a"], win._scenes_widget.escena["b"]) == \
        (3.0, 6.5)
    # ✨ al volver al editor tras aplicar: va a la escena y resalta sus clips
    pg = win._scenes_widget
    (img2,) = ctrl.import_now([png("otro.png", Qt.darkRed)])
    pg._añadir_actor(img2)
    assert pg.aplicar()
    pg.volver()
    pump(app, 0.2)
    assert win.timeline._flash is not None and win.timeline._flash[0], "no se resaltaron los clips al volver"
    assert abs(win.engine.time - 3.0) < 0.05
    pump(app, 2.3)
    assert win.timeline._flash is None, "el resaltado no se apaga solo"
    win.ctrl.undo_stack.setClean()                   # (si no, al cerrar pregunta «¿guardar los cambios?»)
    win.ctrl._media_dirty = False
    win.close()
    print("✓ ventana principal: página «🎬 Escenas» arriba, el editor vuelve tal cual; 🔑 «Crear escena aquí»")


def main():
    app = QApplication.instance() or QApplication([])
    prueba_nucleo()
    ctrl, esc = prueba_controlador(app)
    prueba_exportar(ctrl, esc)
    prueba_pagina(app)
    prueba_donde_y_cuanto(app)
    prueba_mas(app)
    prueba_comparativa(app)
    prueba_ventana_principal(app)
    assert TRACK_VIDEO
    print("TODO OK")


if __name__ == "__main__":
    main()
