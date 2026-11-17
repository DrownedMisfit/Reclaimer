"""
⚡ Escenas prehechas y ◆ animar a mano (por claves) en 🎬 Escenas.
  · Todas las prehechas se crean con 1, 2 o un grupo de personajes (PNG sintéticos), con fases válidas (las animaciones
    existen), sus sonidos ✦ existen, se aplican a la línea de tiempo en horizontal y en vertical, se estiran, y si faltan
    personajes quedan marcadores y se avisa. Desde la página: papeles con lo elegido en Local, Ctrl+Z, tramo I/O,
    🔁 cambiar imagen (todo el grupo), guardar como plantilla propia, «Enviar a» Vertical (se recolocan).
  · ◆ Auto clave: 3 claves arrastrando en el visor, interpolación a mitad, mover un rombo, cambiar curva, borrar,
    Ctrl+Z, aplicar → las posiciones de la línea de tiempo coinciden con la vista previa; guardar en mis movimientos.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_prehechas.py <carpeta_salida>   (sin ventanas, sin sonido)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def png(nombre, color):
    from PIL import Image, ImageDraw
    ruta = os.path.join(_TMP, nombre)
    im = Image.new("RGBA", (200, 320), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((60, 10, 140, 90), fill=color + (255,))
    d.rounded_rectangle((40, 95, 160, 310), radius=30, fill=color + (255,))
    im.save(ruta)
    return ruta


def raton(widget, tipo, pos, botones):
    pos = QPointF(pos)
    ev = QMouseEvent(tipo, pos, QPointF(widget.mapToGlobal(pos.toPoint())),
                     Qt.LeftButton, botones, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)


def arrastrar_en_visor(app, pg, actor_id, dx_frac, dy_frac):
    """Arrastra al personaje en el visor (eventos de ratón de verdad sobre el visor)."""
    it = pg._items[actor_id]
    view, vp = pg.view, pg.view.viewport()
    p0 = view.mapFromScene(it.mapToScene(it.rect().center()))
    p1 = view.mapFromScene(it.mapToScene(it.rect().center()) + QPointF(dx_frac * pg.W, dy_frac * pg.H))
    raton(vp, QEvent.MouseButtonPress, p0, Qt.LeftButton)
    for k in range(1, 7):
        raton(vp, QEvent.MouseMove, QPointF(p0) + (QPointF(p1) - QPointF(p0)) * (k / 6), Qt.LeftButton)
    raton(vp, QEvent.MouseButtonRelease, p1, Qt.NoButton)
    app.processEvents()


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.core import escenas_prehechas as PH
    from editoria.core import image_anim, scenes, sfx, transform
    from editoria.ui.main_window import MainWindow
    rA, rB, rG = png("rojo.png", (220, 60, 60)), png("azul.png", (60, 90, 220)), png("verde.png", (60, 180, 90))
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ws, ctrl = win.workspaces, win.ctrl
        ws.switch("youtube")
        pump(app, 0.2)

        def ids():
            return [ctrl.media_for_path(r, "Escenas") for r in (rA, rB, rG)]

        # ------------------------------------------------ 1) todas: crear, fases, sonidos, aplicar (H y V), estirar
        assert 15 <= len(PH.CATALOGO) <= 30, len(PH.CATALOGO)
        assert {t["grupo"] for t in PH.CATALOGO} == set(PH.GRUPOS)
        for formato in ("youtube", "short"):
            ws.switch(formato)
            pump(app, 0.2)
            p = ctrl.project
            vertical = p.height > p.width
            assert vertical == (formato == "short"), (formato, p.width, p.height)
            a_id, b_id, g_id = ids()
            todas = []
            for i, t in enumerate(PH.CATALOGO):
                for caso, medios, n in (("1", {"A": a_id, "B": a_id, "G": a_id}, 1),      # (un mismo PNG en todo)
                                        ("2", {"A": a_id, "B": b_id, "G": b_id}, 2),
                                        ("grupo", {"A": a_id, "B": b_id, "G": g_id}, 4)):
                    e, faltan = PH.construir(t["clave"], 6.0 * len(todas), medios, ctrl.media_for_path, vertical,
                                             n_grupo=n)
                    assert not faltan, (t["clave"], caso, faltan)
                    solo, f1 = PH.construir(t["clave"], 0.0, {"A": a_id}, ctrl.media_for_path, vertical, n_grupo=n)
                    otros = [f"{x[0]} ({x[1]})" for x in t["papeles"] if x[0] != "A"]
                    assert f1 == otros, ("avisa de los que faltan", t["clave"], f1, otros)
                    assert e["actores"], t["clave"]
                    for act in e["actores"]:
                        assert act["media_id"] in p.media, (t["clave"], act)
                        for f in act["fases"]:
                            assert f["anim"] in dict(image_anim.FASES[f["tipo"]]), (t["clave"], f)
                    for s in e["sonidos"]:
                        assert s["media_id"] in p.media and os.path.isfile(p.media[s["media_id"]].path), t["clave"]
                        assert s.get("sfx") in sfx.CATALOG, (t["clave"], s)
                    pz = scenes.piezas(e)
                    assert pz and all(float(e["a"]) - 1e-6 <= x["a"] < x["b"] <= float(e["b"]) + 1e-6 for x in pz)
                    if any(x[2] for x in t["papeles"]):
                        g = [x for x in e["actores"] if x.get("grupo") == "G"]
                        assert len(g) == n, (t["clave"], caso, len(g))
                        cajas = {(round(x["caja"]["x"], 3), round(x["caja"]["w"], 3)) for x in g}
                        assert len(cajas) == len(g), ("el grupo varía de sitio o tamaño", t["clave"])
                    if caso == "2":
                        todas.append(e)
                # estirar a otra duración
                e7, _f = PH.construir(t["clave"], 0.0, {"A": a_id, "B": b_id, "G": g_id}, ctrl.media_for_path,
                                      vertical, dur=7.0)
                assert abs(scenes.largo(e7) - 7.0) < 1e-6, t["clave"]
                ult = max(x["b"] for x in scenes.piezas(e7))
                base = max(x["b"] for x in scenes.piezas(PH.construir(t["clave"], 0.0, {"A": a_id, "B": b_id,
                                                                                         "G": g_id}, None,
                                                                         vertical)[0]))
                assert ult > base + 0.5 or ult >= 6.9, ("se estira", t["clave"], ult, base)
                for act in e7["actores"]:                # (dentro de la pantalla, al menos en parte)
                    c = act["caja"]
                    assert c["x"] < 1 and c["x"] + c["w"] > 0 and c["y"] < 1 and c["y"] + c["h"] > 0, (t["clave"], c)
            res = ctrl.apply_scenes(todas)
            assert res, "se aplican"
            for e in todas:
                assert ctrl.scene_clips(ctrl.project, e["id"]), ("clips creados", e["nombre"], formato)
                assert e["id"] in ctrl.project.scenes
            print(f"✓ {len(PH.CATALOGO)} prehechas × (1, 2 y grupo) creadas, válidas y aplicadas en "
                  f"{'vertical' if vertical else 'horizontal'} ({len(res)} clips)")
            ctrl.undo_stack.undo()
            assert not any(ctrl.scene_clips(ctrl.project, e["id"]) for e in todas), "Ctrl+Z las quita"
        ws.switch("youtube")
        pump(app, 0.2)
        p = ctrl.project
        a_id, b_id, g_id = ids()

        # «⇆ Cruzar la pantalla» seguido de otra fase: lo de después sigue viéndose (escenas de antes, sin cambios)
        ec = scenes.nueva(0.0, 6.0)
        ac = scenes.nuevo_actor(ec, a_id)
        ac["fases"] = [{"tipo": "accion", "anim": "cruza", "dur": 2.0}, {"tipo": "accion", "anim": "salta", "dur": 1.0},
                       {"tipo": "accion", "anim": "ninguna", "dur": 0.1, "auto": True}]
        anims = [x["fase"]["anim"] for x in scenes.piezas(ec)]
        assert anims == ["cruza", "salta", "ninguna"], anims
        ac["fases"][0]["anim"] = "cruza_corre"           # (la nueva «🏃 Cruzar corriendo» sí acaba ahí)
        assert [x["fase"]["anim"] for x in scenes.piezas(ec)] == ["cruza_corre"]
        print("✓ «⇆ Cruzar» deja ver lo de después; «🏃 Cruzar corriendo» termina")

        # faltan personajes → marcadores y aviso
        e, faltan = PH.construir("contra_grupo", 0.0, {"A": a_id}, ctrl.media_for_path, False)
        assert faltan == ["G (Grupo)"], faltan
        marc = {p.media[x["media_id"]].path for x in e["actores"] if x.get("grupo")}
        assert len(marc) == 1 and PH.es_propia(marc.pop()), "el grupo lleva el marcador"
        print("✓ sin personaje: marcador (silueta con su letra) y aviso de lo que falta")

        # ------------------------------------------------ 2) desde la página
        p.mark_in = p.mark_out = None
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        assert pg.material.tabText(2) == "⚡ Prehechas"
        pg._llenar_imagenes()
        for i in range(pg.lista_img.count()):
            it = pg.lista_img.item(i)
            it.setSelected(it.data(Qt.UserRole) in (a_id, b_id))
            assert not PH.es_propia(p.media[it.data(Qt.UserRole)].path), "las imágenes propias no salen en Local"
        fila = next(i for i in range(pg.pre_lista.count()) if pg.pre_lista.item(i).data(Qt.UserRole) == "tiroteo")
        pg.pre_lista.setCurrentRow(fila)
        pump(app, 0.1)
        assert pg._pre_clave == "tiroteo" and pg.pre_vista.escena is not None
        assert set(pg._pre_medios().values()) == {a_id, b_id}, pg._pre_medios()
        assert pg._pre_combos["A"].currentData() != pg._pre_combos["B"].currentData()
        assert not pg._tiene_contenido()
        id0 = pg.escena["id"]
        pg._crear_prehecha()
        assert pg.escena["id"] == id0 and len(pg.escena["actores"]) == 2 and pg.escena["sonidos"]
        assert {x["media_id"] for x in pg.escena["actores"]} == {a_id, b_id}
        assert not pg.marca.text().startswith("⚠")
        pg.deshacer()
        assert not pg.escena["actores"] and not pg.escena["sonidos"], "Ctrl+Z de la escena la quita"
        pg.rehacer()
        assert len(pg.escena["actores"]) == 2, "Ctrl+Y la vuelve a poner"
        print("✓ página: papeles con lo elegido en Local, se crea en la escena vacía, Ctrl+Z / Ctrl+Y")

        # editable: estirar con «Dura», acción nueva, aplicar y Ctrl+Z del editor
        pg.dura.setValue(6.0)
        assert abs(scenes.largo(pg.escena) - 6.0) < 1e-6
        act = pg.escena["actores"][0]
        pg.tl.t = 0.3
        pg._accion_en(act, "habla")
        assert pg.aplicar()
        clips = ctrl.scene_clips(ctrl.project, pg.escena["id"])
        assert clips and any(ctrl.project.media[c.media_id].path == sfx.path_for("disparo") for c in clips)
        ctrl.undo_stack.undo()
        assert not ctrl.scene_clips(ctrl.project, pg.escena["id"])
        ctrl.undo_stack.redo()
        print("✓ se estira, se edita (acciones nuevas) y se aplica (Ctrl+Z en el editor la quita)")

        # plantilla propia a partir de una prehecha modificada
        ruta = scenes.guardar_plantilla(pg.escena, ctrl.project, "Prehecha mía")
        tp = next(x for x in scenes.plantillas() if x["archivo"] == ruta)
        e2, falt2 = scenes.desde_plantilla(tp, 20.0, ctrl.media_for_path)
        assert not falt2 and len(e2["actores"]) == len(pg.escena["actores"]) and \
            len(e2["sonidos"]) == len(pg.escena["sonidos"])
        assert any(f["anim"] == "habla" for x in e2["actores"] for f in x["fases"])
        print("✓ una prehecha retocada se guarda en 📚 y se vuelve a usar")

        # nueva con grupo sin imagen + tramo I/O (estirada) + 🔁 cambiar imagen en todo el grupo
        p.mark_in, p.mark_out = 30.0, 37.5
        pg._crear_prehecha("contra_grupo", medios={"A": a_id, "G": None}, n_grupo=5)
        assert abs(pg.escena["a"] - 30.0) < 1e-6 and abs(scenes.largo(pg.escena) - 7.5) < 1e-6
        grupo = [x for x in pg.escena["actores"] if x.get("grupo") == "G"]
        assert len(grupo) == 5 and pg.marca.text().startswith("⚠ faltan"), pg.marca.text()
        pg._cambiar_imagen(grupo[2], g_id)
        assert all(x["media_id"] == g_id for x in grupo), "se cambia en todo el grupo"
        assert not pg.marca.text().startswith("⚠ faltan"), pg.marca.text()
        p.mark_in = p.mark_out = None
        print("✓ tramo I/O (estirada), grupo ×5 con marcador → aviso → 🔁 cambiar imagen en todo el grupo")

        # añadir a esta escena desde la línea roja + temblor y destello sueltos
        n0 = len(pg.escena["actores"])
        pg.tl.t = 1.0
        pg._crear_prehecha("sorpresa", añadir=True, medios={"A": b_id})
        assert len(pg.escena["actores"]) == n0 + 2
        assert pg.escena["actores"][-1].get("efecto") in (None, "destello")
        pg._destello_aqui()
        assert pg.escena["actores"][-1].get("efecto") == "destello"
        print("✓ «＋ A esta escena», ⚡ destello de pantalla")

        # «Enviar a» Vertical: se recoloca
        pg._crear_prehecha("cara_a_cara", medios={"A": a_id, "B": b_id})
        pg.destino.setCurrentIndex(pg.destino.findData("short"))
        assert pg.aplicar()
        pump(app, 0.4)
        assert ws.current == "short"
        esc = next(x for x in ctrl.project.scenes.values() if x.get("prehecha") == "cara_a_cara")
        for act in esc["actores"]:
            if act.get("pos") and not act.get("efecto"):
                v = scenes.caja_pos(act["pos"], True)
                assert all(abs(act["caja"][k] - v[k]) < 1e-3 for k in ("x", "y", "w", "h")), act["caja"]
        assert ctrl.scene_clips(ctrl.project, esc["id"])
        print("✓ «Enviar a: 📱 Vertical»: la prehecha se recoloca para el formato vertical")
        win.go_page("edit")
        pump(app, 0.2)
        ws.switch("youtube")
        pump(app, 0.3)

        # ------------------------------------------------ 3) ◆ animar a mano (Auto clave)
        p = ctrl.project
        p.mark_in = p.mark_out = None
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        pg._cargar(scenes.nueva(50.0, 54.0, "A mano"), True)
        a_id = ctrl.media_for_path(rA, "Escenas")
        pg._añadir_actor(a_id)
        act = pg.escena["actores"][0]
        pg.b_auto.setChecked(True)
        pump(app, 0.1)
        movs = [(1.0, 0.0, 0.0), (2.0, 0.25, -0.05), (3.0, 0.1, 0.08)]
        for t, dx, dy in movs:
            pg._saltar_a(t)
            assert pg._items[act["id"]].editable, "con Auto clave el elegido se arrastra en la línea roja"
            arrastrar_en_visor(app, pg, act["id"], dx, dy)
        ks = scenes.claves(pg.escena, act)
        assert [round(t, 2) for t, _f, _k in ks] == [1.0, 2.0, 3.0], [t for t, _f, _k in ks]
        c1, c2 = scenes.caja_en(pg.escena, act, 1.0), scenes.caja_en(pg.escena, act, 2.0)
        assert abs((c2["x"] - c1["x"]) - 0.25) < 0.02 and abs((c2["y"] - c1["y"]) + 0.05) < 0.02, (c1, c2)
        mid = scenes.caja_en(pg.escena, act, 1.5)
        assert abs(mid["x"] - (c1["x"] + c2["x"]) / 2) < 1e-3, "suave: a mitad, la mitad del camino"
        from editoria.ui.scenes_page import estado_en
        prev = estado_en(pg.escena, 1.5)[act["id"]]["box"]
        assert abs(prev["x"] - mid["x"]) < 1e-6, "la vista previa interpola igual"
        print("✓ ◆ Auto clave: 3 claves arrastrando en el visor; a mitad interpola (visor = cálculo)")

        # mover un rombo en la línea de la escena (ratón)
        tl = pg.tl
        tl.zoom, tl.off = 1.0, 0.0
        c, _a, _f, k2, _t = next(x for x in tl._claves_vis() if abs(x[4] - 2.0) < 1e-3)
        raton(tl, QEvent.MouseButtonPress, c, Qt.LeftButton)
        destino = QPointF(tl.x_de(2.4), c.y())
        raton(tl, QEvent.MouseMove, destino, Qt.LeftButton)
        raton(tl, QEvent.MouseButtonRelease, destino, Qt.NoButton)
        ts = [round(t, 1) for t, _f, _k in scenes.claves(pg.escena, act)]
        assert ts == [1.0, 2.4, 3.0], ts
        print("✓ rombo arrastrado en el tiempo (2,0 s → 2,4 s)")

        # curva lineal → a un cuarto, un cuarto del camino
        _t1, f1, k1 = scenes.claves(pg.escena, act)[0]
        pg._curva(k1, "linear")
        assert k1["i"] == "linear"
        c1, c2 = scenes.caja_en(pg.escena, act, 1.0), scenes.caja_en(pg.escena, act, 2.4)
        q = scenes.caja_en(pg.escena, act, 1.35)
        assert abs(q["x"] - (c1["x"] + (c2["x"] - c1["x"]) * 0.25)) < 2e-3, (q, c1, c2)
        pg._curva(k1, "hold")
        assert abs(scenes.caja_en(pg.escena, act, 2.3)["x"] - c1["x"]) < 1e-6, "mantener: no se mueve hasta la otra"
        pg._curva(k1, "smooth")
        print("✓ curvas: lineal y mantener se notan en la interpolación")

        # borrar una clave y Ctrl+Z
        pump(app, 0.45)                                  # (cada cambio ya asentado en el historial de la escena)
        pg._saltar_a(3.0)
        pg._quitar_clave_aqui()
        assert len(scenes.claves(pg.escena, act)) == 2
        pg.deshacer()
        act = pg.escena["actores"][0]
        assert len(scenes.claves(pg.escena, act)) == 3, "Ctrl+Z de la escena devuelve la clave"
        print("✓ ◇ quitar clave y Ctrl+Z")

        # aplicar → las posiciones de la línea de tiempo coinciden con la vista previa
        assert pg.aplicar()
        escena = ctrl.project.scenes[pg.escena["id"]]
        act = escena["actores"][0]
        fase = next(f for f in act["fases"] if f.get("mano"))
        a0 = float(escena["a"]) + scenes.inicio_de(act, fase)
        clip = next(cc for cc in ctrl.scene_clips(ctrl.project, escena["id"]) if abs(cc.start - a0) < 1e-3)
        for t in (1.0, 1.7, 2.4, 2.9):
            box = transform.layout_value_at(clip.layout_kf, float(escena["a"]) + t - clip.start)
            esp = scenes.caja_en(escena, act, t)
            assert all(abs(box[k] - esp[k]) < 1e-3 for k in ("x", "y", "w", "h")), (t, box, esp)
        despues = scenes.caja_en(escena, act, 3.6)       # (después de la última clave se queda ahí)
        assert abs(despues["x"] - scenes.caja_en(escena, act, 3.0)["x"]) < 1e-3
        scenes.guardar_movimiento(fase, "Mi animación a mano")
        mv = next(m for m in scenes.movimientos() if m["nombre"] == "Mi animación a mano")
        assert mv.get("mano") and scenes.fase_de_movimiento(mv).get("mano")
        print("✓ aplicada: la línea de tiempo coincide con la vista previa; se guarda en 📚 mis movimientos")
        pg.b_auto.setChecked(False)
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        pg = getattr(win, "_scenes_widget", None)
        if pg is not None:
            pg.sucia = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
