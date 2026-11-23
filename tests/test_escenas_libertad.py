"""
🎬 Escenas con libertad, como las capas y el lienzo de 🖼 Miniatura.
  · Línea de la escena: la fila de arriba = delante; arrastrar el NOMBRE de una fila cambia el orden de capas; los
    bloques se estiran o encogen por el borde IZQUIERDO (el final se queda) y por el derecho; arrastrar el centro de
    una fase del medio la mueve en el tiempo; arrastrada a otra fila pasa a ese personaje (el de origen se queda con
    lo demás) y debajo de todo crea un personaje nuevo con la misma imagen; soltar una imagen (de Medios) sobre un
    bloque cambia la imagen y en un hueco crea un personaje; un clic simple no cambia nada. Ctrl+Z en cada paso.
  · Visor: clic elige la imagen de más arriba; 8 tiradores (esquina = sin deformar, lado = estirar), recortar desde
    cada lado (✂ o Alt); con ◆ Auto clave va a una clave; Ctrl+Z; al aplicar, la línea de tiempo y la exportación
    llevan el estirado y el recorte. Zoom con Ctrl + rueda (10 %–800 %), etiqueta «🔍 N %», ⤢ / doble clic = ajustar.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_libertad.py <carpeta_salida>   (sin ventanas, sin sonido)
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

sys.stdout.reconfigure(line_buffering=True)

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def png(nombre, color, w=200, h=320):
    from PIL import Image, ImageDraw
    ruta = os.path.join(_TMP, nombre)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((10, 10, w - 10, h - 10), radius=30, fill=color + (255,))
    im.save(ruta)
    return ruta


def raton(widget, tipo, pos, botones, mods=Qt.NoModifier):
    pos = QPointF(pos)
    boton = Qt.LeftButton if tipo != QEvent.MouseMove else Qt.NoButton
    ev = QMouseEvent(tipo, pos, QPointF(widget.mapToGlobal(pos.toPoint())), boton, botones, mods)
    QApplication.sendEvent(widget, ev)


def arrastrar(app, w, p0, p1, pasos=6, mods=Qt.NoModifier):
    raton(w, QEvent.MouseButtonPress, p0, Qt.LeftButton, mods)
    for k in range(1, pasos + 1):
        raton(w, QEvent.MouseMove, QPointF(p0) + (QPointF(p1) - QPointF(p0)) * (k / pasos), Qt.LeftButton, mods)
    raton(w, QEvent.MouseButtonRelease, p1, Qt.NoButton, mods)
    app.processEvents()


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.core import scenes
    from editoria.ui.common import MEDIA_MIME
    from editoria.ui.main_window import MainWindow
    rA, rB, rC, rD = (png("rojo.png", (220, 60, 60)), png("azul.png", (60, 90, 220)), png("verde.png", (60, 180, 90)),
                      png("amarillo.png", (230, 210, 40)))
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ctrl = win.ctrl
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        p = ctrl.project
        ids = [ctrl.media_for_path(r, "Escenas") for r in (rA, rB, rC, rD)]
        p.mark_in, p.mark_out = 2.0, 8.0
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        for mid in ids[:3]:
            pg._añadir_actor(mid)
        pg._guardar_hist()
        tl = pg.tl
        tl.iman = False                                     # (medidas exactas, sin imán)
        tl.resize(1100, 260)
        app.processEvents()
        acts = pg.escena["actores"]
        A, B, C = acts
        assert [f[1] for f in tl.filas()[:3]] == [C, B, A], "la fila de arriba es la de delante (la última)"

        def y_fila(i):
            return tl.REGLA + i * tl.FILA + tl.FILA / 2

        # ------------------------------------------------ ↕ arrastrar el nombre = orden de capas
        arrastrar(app, tl, QPointF(20, y_fila(2)), QPointF(20, tl.REGLA + 2))     # (A, la de abajo, arriba del todo)
        assert [a["id"] for a in pg.escena["actores"]] == [B["id"], C["id"], A["id"]], "A pasa delante"
        assert tl.filas()[0][1]["id"] == A["id"]
        z = {a["id"]: pg._items[a["id"]].zValue() for a in pg.escena["actores"]}
        assert z[A["id"]] > z[C["id"]] > z[B["id"]], "el visor dibuja delante la de arriba"
        pg.deshacer()
        assert [a["id"] for a in pg.escena["actores"]] == [A["id"], B["id"], C["id"]], "Ctrl+Z"
        print("✓ arrastrar el nombre de una fila cambia el orden de capas (la de arriba, delante); Ctrl+Z")

        # ------------------------------------------------ un clic simple no cambia nada
        A, B, C = pg.escena["actores"]
        antes = scenes.copia(pg.escena)
        bl = [b for b in tl.bloques() if b[2] is C]
        r_q = bl[1][0]                                      # (el «Quieto» de C, fila 0)
        pg.sucia = False
        raton(tl, QEvent.MouseButtonPress, r_q.center(), Qt.LeftButton)
        raton(tl, QEvent.MouseButtonRelease, r_q.center(), Qt.NoButton)
        assert pg.escena == antes and tl.sel == ("fase", C["fases"][1]), "elige sin cambiar nada"

        # ------------------------------------------------ ⇤ estirar/encoger desde el borde izquierdo
        ent, quieto = C["fases"][0], C["fases"][1]
        d_ent, fin_q = float(ent["dur"]), scenes.inicio_de(C, quieto) + float(quieto["dur"])
        x_izq = r_q.left() + 2
        arrastrar(app, tl, QPointF(x_izq, r_q.center().y()), QPointF(x_izq + 0.6 * tl._pps(), r_q.center().y()),
                  mods=Qt.ShiftModifier)                    # (Mayús: sin imán, para medir exacto)
        assert abs(float(ent["dur"]) - (d_ent + 0.6)) < 0.03, ("la de antes crece", ent["dur"], d_ent)
        assert abs(scenes.inicio_de(C, quieto) + float(quieto["dur"]) - fin_q) < 0.03, "el final se queda"
        pg.deshacer()
        A, B, C = pg.escena["actores"]
        assert abs(float(C["fases"][0]["dur"]) - d_ent) < 1e-6
        print("✓ un clic elige sin cambiar nada; el borde izquierdo encoge desde la izquierda (Ctrl+Z)")

        # ------------------------------------------------ ⇆ mover una fase del medio en el tiempo
        a = scenes.insertar_en(pg.escena, C, 2.0, {"tipo": "accion", "anim": "salta", "dur": 1.0})
        pg._ensuciar()
        pg._reconstruir()
        pg._guardar_hist()
        r_a = next(b[0] for b in tl.bloques() if b[3] is a)
        ini_a = scenes.inicio_de(C, a)
        arrastrar(app, tl, r_a.center(), r_a.center() + QPointF(0.5 * tl._pps(), 0), mods=Qt.ShiftModifier)
        assert abs(scenes.inicio_de(C, a) - (ini_a + 0.5)) < 0.03 and abs(float(a["dur"]) - 1.0) < 1e-6, \
            ("se mueve sin cambiar de duración", scenes.inicio_de(C, a), ini_a)
        print("✓ arrastrar el centro de una fase del medio la mueve en el tiempo (misma duración)")

        # ------------------------------------------------ ↧ a otra fila: pasa a ese personaje
        pg._guardar_hist()
        r_a = next(b[0] for b in tl.bloques() if b[3] is a)
        ini_a = scenes.inicio_de(C, a)
        fases_c = len(C["fases"])
        arrastrar(app, tl, r_a.center(), QPointF(r_a.center().x(), y_fila(1)), mods=Qt.ShiftModifier)
        assert not any(f is a for f in C["fases"]) and len(C["fases"]) == fases_c, "en su sitio queda un «Quieto»"
        assert any(f["anim"] == "salta" for f in B["fases"]), "B tiene la fase"
        f_b = next(f for f in B["fases"] if f["anim"] == "salta")
        assert abs(scenes.inicio_de(B, f_b) - ini_a) < 0.05, ("en el mismo segundo", scenes.inicio_de(B, f_b), ini_a)
        n_act = len(pg.escena["actores"])
        pg._guardar_hist()
        # … y debajo de todo: personaje nuevo con la misma imagen (detrás de todos)
        r_b = next(b[0] for b in tl.bloques() if b[3] is f_b)
        abajo = tl.REGLA + len(tl.filas()) * tl.FILA + tl.FILA / 2
        arrastrar(app, tl, r_b.center(), QPointF(r_b.center().x(), abajo), mods=Qt.ShiftModifier)
        assert len(pg.escena["actores"]) == n_act + 1
        nuevo = pg.escena["actores"][0]
        assert nuevo["media_id"] == B["media_id"] and nuevo["fases"][0]["anim"] == "salta"
        assert tl.filas()[len(pg.escena["actores"]) - 1][1] is nuevo, "su fila, la última (detrás)"
        pg.deshacer()
        pg.deshacer()
        assert len(pg.escena["actores"]) == n_act and not any(f["anim"] == "salta" for f in pg.escena["actores"][1]
                                                               ["fases"])
        print("✓ un bloque a otra fila pasa a ese personaje; debajo de todo, personaje nuevo con su imagen; Ctrl+Z")

        # ------------------------------------------------ 🖼 soltar una imagen: en un bloque la cambia, en un hueco crea
        A, B, C = pg.escena["actores"][:3]
        r_bb = next(b[0] for b in tl.bloques() if b[2] is B and b[3] is B["fases"][-1])
        md = QMimeData()
        md.setData(MEDIA_MIME, QByteArray(ids[3].encode()))
        ev = QDropEvent(r_bb.center(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        assert tl._imagen_de(ev) == ("medio", ids[3])
        tl.dropEvent(ev)
        assert B["media_id"] == ids[3], "la imagen soltada en un bloque es la de ese personaje"
        pg._guardar_hist()
        n_act = len(pg.escena["actores"])
        abajo = QPointF(tl.x_de(1.0), tl.REGLA + len(tl.filas()) * tl.FILA + tl.FILA / 2)
        tl.dropEvent(QDropEvent(abajo, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        assert len(pg.escena["actores"]) == n_act + 1 and pg.escena["actores"][0]["media_id"] == ids[3]
        assert abs(float(pg.escena["actores"][0]["inicio"]) - 1.0) < 0.05, "aparece donde la sueltas"
        pg.deshacer()
        pg.deshacer()
        assert len(pg.escena["actores"]) == n_act and pg.escena["actores"][1]["media_id"] == ids[1]
        print("✓ soltar una imagen de Medios: en un bloque cambia la imagen; en un hueco, personaje nuevo ahí")

        # ------------------------------------------------ ver más allá: lo que pasa del final, barra y rueda
        largo = scenes.largo(pg.escena)
        snd = scenes.nuevo_sonido(pg.escena, ids[0], largo - 1.0, 4.0)
        tl.zoom, tl.off = 1.0, 0.0
        tl.refrescar()
        assert abs(tl.total() - (largo + 3.0)) < 1e-6, "llega hasta el final del sonido"
        r_s = next(b[0] for b in tl.bloques() if b[2] is snd)
        assert r_s.right() <= tl.width() - tl.DER + 1, "con todo a la vista se ve su final"
        assert tl.barra.isHidden()
        tl.acercar(4.0)
        assert not tl.barra.isHidden() and tl.barra.maximum() > 0
        tl.barra.setValue(tl.barra.maximum())
        assert abs(tl.off - (tl.total() - tl._visible())) < 0.01, "la barra llega al final"
        off = tl.off
        c = QPointF(tl.IZQ + 100, 40)
        tl.wheelEvent(QWheelEvent(c, QPointF(tl.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                                  Qt.NoModifier, Qt.NoScrollPhase, False))
        assert tl.off < off and tl.barra.value() == int(round(tl.off * 1000)), "la rueda desplaza (y la barra sigue)"
        pg.escena["sonidos"].remove(snd)
        tl.zoom, tl.off = 1.0, 0.0
        tl.refrescar()
        print("✓ la línea llega hasta lo más largo (pasado el final de la escena), con barra y rueda para desplazarse")

        # ------------------------------------------------ visor: elegir, tiradores, recorte
        A, B, C = pg.escena["actores"][:3]
        pg._poner_en_reposo()
        view, vp = pg.view, pg.view.viewport()
        t = pg._split.sizes()                               # (el visor, lo más ancho posible: las demás columnas al mínimo)
        mins = [max(pg._split.widget(i).minimumSizeHint().width(), pg._split.widget(i).minimumWidth())
                for i in range(len(t))]
        pg._split.setSizes([mins[0], sum(t) - sum(mins) + mins[1]] + mins[2:])
        app.processEvents()
        view.ajustar()
        app.processEvents()
        assert pg.zoom_label.text() == "100 %"
        itC = pg._items[C["id"]]
        centro = view.mapFromScene(itC.mapToScene(itC.rect().center()))
        raton(vp, QEvent.MouseButtonPress, QPointF(centro), Qt.LeftButton)
        raton(vp, QEvent.MouseButtonRelease, QPointF(centro), Qt.NoButton)
        assert tl.sel[1] is C and itC.elegido, "clic elige la imagen (y su fila)"
        pg._guardar_hist()
        c0 = dict(C["caja"])
        br = view.mapFromScene(itC.mapToScene(itC.puntos()["br"]))
        arrastrar(app, vp, QPointF(br), QPointF(br) + QPointF(60, 10))
        c1 = dict(C["caja"])
        assert c1["w"] > c0["w"] * 1.1 and abs(c1["w"] / c1["h"] - c0["w"] / c0["h"]) < 0.02, ("esquina sin "
                                                                                               "deformar", c0, c1)
        assert abs(c1["x"] - c0["x"]) < 1e-3 and abs(c1["y"] - c0["y"]) < 1e-3, "desde la esquina contraria"
        rr = view.mapFromScene(itC.mapToScene(itC.puntos()["r"]))
        arrastrar(app, vp, QPointF(rr), QPointF(rr) + QPointF(50, 0), mods=Qt.AltModifier)   # (22/11: Alt = estirar)
        assert C["caja"]["fit"] == "stretch" and C["caja"]["w"] > c1["w"] + 0.01, "Alt + lado estira"
        w_antes = C["caja"]["w"]
        pg.a_recortar.setChecked(True)
        ll = view.mapFromScene(itC.mapToScene(itC.puntos()["l"]))
        arrastrar(app, vp, QPointF(ll), QPointF(ll) + QPointF(40, 0))
        assert C["caja"].get("crop", {}).get("l", 0) > 0.05 and abs(C["caja"]["w"] - w_antes) < 1e-3, \
            ("recorta desde la izquierda sin cambiar el tamaño", C["caja"])
        pg.a_recortar.setChecked(False)
        tt = view.mapFromScene(itC.mapToScene(itC.puntos()["b"]))
        h_antes = C["caja"]["h"]
        arrastrar(app, vp, QPointF(tt), QPointF(tt) - QPointF(0, 30))
        assert C["caja"]["crop"].get("b", 0) > 0.03 and abs(C["caja"]["h"] - h_antes) < 1e-3, \
            "el lado solo RECORTA (de abajo arriba), sin estirar"
        caja_final = dict(C["caja"], crop=dict(C["caja"]["crop"]))
        pg.deshacer()
        assert pg.escena["actores"][2]["caja"].get("crop", {}).get("b", 0) == 0, "Ctrl+Z"
        pg.rehacer()
        C = pg.escena["actores"][2]
        assert C["caja"] == caja_final
        print("✓ visor: clic elige; esquina = sin deformar, lado = recortar, Alt + lado = estirar; ✂ también las esquinas; Ctrl+Z")

        # ◆ con Auto clave: va a una clave en la línea roja
        pg.b_auto.setChecked(True)
        pg._saltar_a(1.5)
        pg._elegir_actor(C["id"])
        itC = pg._items[C["id"]]
        r0 = itC.rect().translated(itC.pos())
        itC.arrastrar_tirador("br", r0.bottomRight(), r0.bottomRight() + QPointF(-30, -30), r0)
        pg._actor_movido(C["id"])
        assert scenes.claves(pg.escena, C), "Auto clave: una clave"
        pg.b_auto.setChecked(False)

        # aplicar: la línea de tiempo y la exportación llevan el estirado y el recorte
        assert pg.aplicar()
        from editoria.core import escena_clip
        assert len(ctrl.scene_clips(p, pg.escena["id"])) == 1, "un solo clip de escena"
        q = escena_clip.expandir(p)                         # (lo que pintan el visor y la exportación)
        nota = scenes.nota(pg.escena["id"])
        lays = [c.layout for c in q.clips.values() if c.note == nota and c.layout and c.layout.get("crop")]
        assert lays and lays[0]["fit"] == "stretch" and lays[0]["crop"]["l"] > 0.05, lays
        from editoria.core import media as M
        from editoria.export.ffmpeg_export import ExportOptions, build_command
        args, _t = build_command(p, ExportOptions(path=os.path.join(_TMP, "x.mp4"), width=640, height=360, fps=30,
                                                  encoder="cpu", loudnorm=False), M.ffmpeg(),
                                 os.path.join(_TMP, "f.txt"))
        grafo = " ".join(args) + open(os.path.join(_TMP, "f.txt"), encoding="utf-8").read()
        assert "pad=" in grafo and "black@0" in grafo, "el recorte llega a la exportación"
        print("✓ ◆ Auto clave guarda una clave; al aplicar, la línea de tiempo y la exportación llevan estirado y recorte")

        # ------------------------------------------------ 🔍 zoom del visor
        c = QPointF(vp.width() / 2, vp.height() / 2)
        ev = QWheelEvent(c, QPointF(vp.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                         Qt.ControlModifier, Qt.NoScrollPhase, False)
        for _ in range(30):
            view.wheelEvent(ev)
        assert abs(view.zoom - 0.1) < 1e-6 and pg.zoom_label.text() == "10 %", (view.zoom, pg.zoom_label.text())
        assert view.mapFromScene(view.lienzo().topLeft()).x() > 20, "se ve fuera del encuadre"
        ev2 = QWheelEvent(c, QPointF(vp.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                          Qt.ControlModifier, Qt.NoScrollPhase, False)
        for _ in range(60):
            view.wheelEvent(ev2)
        assert abs(view.zoom - 8.0) < 1e-6 and pg.zoom_label.text() == "800 %"
        view.ajustar()
        assert pg.zoom_label.text() == "100 %" and view.ajustado
        print("✓ zoom del visor: Ctrl + rueda de 10 % a 800 % con «🔍 N %»; ⤢ ajustar")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        pg = getattr(win, "_scenes_widget", None)
        if pg is not None:
            pg.sucia = False
        win.close()
        pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
