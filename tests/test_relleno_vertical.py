"""
📱 Visor de un proyecto VERTICAL (Shorts / Edits): nada se dibuja fuera del cuadro 9:16.
  · un video horizontal con ▦ Relleno: arriba y abajo su imagen borrosa DENTRO del cuadro; fuera, solo el fondo del
    visor (antes el fondo borroso asomaba como un rectángulo horizontal más ancho que el lienzo);
  · un fotograma que llega tarde a una capa oculta (precarga, otro proyecto) no vuelve a enseñar su relleno;
  · un clip escalado o movido que se sale del cuadro: lo de fuera no se ve (como al exportar);
  · al exportar en vertical sale del tamaño del proyecto con el fondo borroso arriba y abajo;
  · en YouTube (16:9) el relleno se sigue viendo dentro del cuadro;
  · de horizontal a vertical (y un proyecto vertical guardado y vuelto a abrir): el visor coincide con la exportación;
  · 🧲 al mover una capa en el visor se pega al centro y a los bordes de lo que se ve (línea guía; Ctrl = sin imán);
  · ⊕ Centrar / ↔ Centro horizontal / ↕ Centro vertical en el Inspector, un Ctrl+Z cada uno.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles ni sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_relleno_vertical.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
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
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_relleno_vertical")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import fill as FILL
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    ff = M.ffmpeg()
    vid = os.path.join(out, "horizontal.mp4")     # barras de colores 16:9: el borroso se distingue del fondo
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1280x720:d=4:r=30",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True,
                   creationflags=M.NO_WINDOW)
    from PySide6.QtCore import QSettings as _QS
    _QS("EditorIA", "EditorIA").setValue("shorts/encuadre_auto", True)   # (el de la prueba, no el tuyo)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.3)
    ctrl, canvas = win.ctrl, win.preview.canvas
    bg = canvas.backgroundBrush().color()

    def es_fondo(c: QColor) -> bool:
        return abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) <= 6

    def con_imagen(c: QColor) -> bool:            # ni fondo del visor ni negro: hay imagen (nítida o borrosa)
        return not es_fondo(c) and max(c.red(), c.green(), c.blue()) > 40

    def grab(nombre) -> QImage:
        img = canvas.viewport().grab().toImage()
        img.save(os.path.join(out, nombre))
        return img

    def px(img: QImage, sx: float, sy: float) -> QColor | None:
        """Color del visor en el punto (sx, sy) de la escena (None si cae fuera de lo que se ve)."""
        v = canvas.mapFromScene(QPointF(sx, sy))
        if not (0 <= v.x() < img.width() and 0 <= v.y() < img.height()):
            return None
        return img.pixelColor(v.x(), v.y())

    def lados(img, W, H, ys, margen=None):
        """Colores fuera del cuadro, a izquierda y derecha (los que se vean en el visor)."""
        m = margen if margen is not None else 0.25 * W
        res = []
        for y in ys:
            for x in (-m, -0.04 * W, W * 1.04, W + m):
                c = px(img, x, y)
                if c is not None:
                    res.append(((round(x), round(y)), c))
        return res

    def visor_rgb(nombre):
        """El cuadro del proyecto tal como se ve en el visor, a 270×480 (RGB)."""
        img = canvas.viewport().grab().toImage()
        r = canvas.mapFromScene(canvas.frame.rect()).boundingRect()
        im = img.copy(r).scaled(270, 480, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        im = im.convertToFormat(QImage.Format_RGB888)
        im.save(os.path.join(out, nombre))
        bpl = im.bytesPerLine()
        return np.frombuffer(im.constBits(), np.uint8, bpl * 480).reshape(480, bpl)[:, :270 * 3]             .reshape(480, 270, 3).astype(int)

    def exportar(p, t, nombre):
        mp4 = os.path.join(out, nombre)
        args, _t = build_command(p, ExportOptions(path=mp4, width=270, height=480, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        res = subprocess.run(args, capture_output=True, creationflags=M.NO_WINDOW)
        assert res.returncode == 0, res.stderr.decode(errors="replace")[-1500:]
        return M.frame_rgb(mp4, t, 270).astype(int)

    def comparar_con_exportacion(p, track_id, cid, t, tag):
        """El video del visor está donde lo pone la exportación (a todo el ancho de su caja, centrado en ella) y la
        franja del video se ve igual que en el archivo exportado."""
        win.engine.seek(t)
        pump(app, 1.2)
        W, H = p.width, p.height
        c, m = p.clips[cid], p.media_of(p.clips[cid])
        layer = canvas.layers[track_id]
        vids = [v for v in layer.videos if v.isVisible()]
        assert layer.box.isVisible() and vids, f"{tag}: el clip se ve en el visor"
        box = c.layout or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        bw, bh = box["w"] * W, box["h"] * H
        s = min(bw / m.width, bh / m.height)                     # «encajar» (contain)
        ew, eh = m.width * s, m.height * s
        ex, ey = box["x"] * W + (bw - ew) / 2, box["y"] * H + (bh - eh) / 2
        r = vids[0].sceneBoundingRect()
        assert abs(r.left() - ex) < 2 and abs(r.top() - ey) < 2 and abs(r.width() - ew) < 2 and             abs(r.height() - eh) < 2, (f"{tag}: el video del visor, como al exportar", r, (ex, ey, ew, eh))
        vis = visor_rgb(f"visor_{tag}.png")
        exp = exportar(p, t, f"export_{tag}.mp4")
        y0, y1 = int(ey / H * 480) + 6, int((ey + eh) / H * 480) - 6
        x0, x1 = max(0, int(ex / W * 270)) + 4, min(270, int((ex + ew) / W * 270)) - 4
        diff = float(np.abs(vis[y0:y1, x0:x1] - exp[y0:y1, x0:x1]).mean())
        assert diff < 30, (f"{tag}: la franja del video del visor se parece a la exportada", round(diff, 1))
        return diff

    try:
        win.workspaces.switch("short")
        pump(app, 0.4)
        p = ctrl.project
        W, H = p.width, p.height
        assert H > W, (W, H)
        (vid_id,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
        cid = ctrl.add_media([vid_id], v1.id, 0.0)[0]
        assert FILL.of(p.clips[cid].fx), "un video horizontal en Shorts entra con ▦ Relleno"
        win.engine.seek(1.0)
        pump(app, 1.2)
        layer = canvas.layers[v1.id]
        assert layer.fill.isVisible(), "el visor enseña el relleno"
        img = grab("vertical_relleno.png")
        fuera = lados(img, W, H, (0.08 * H, 0.25 * H, 0.5 * H, 0.75 * H, 0.92 * H))
        assert len(fuera) >= 4, f"el visor deja ver lo de fuera del cuadro ({img.width()}×{img.height()})"
        malos = [(pt, c.name()) for pt, c in fuera if not es_fondo(c)]
        assert not malos, ("fuera del cuadro 9:16 no hay imagen del fondo", malos)
        dentro = [px(img, x * W, y * H) for x in (0.1, 0.5, 0.9) for y in (0.08, 0.92)]
        assert all(c is not None and con_imagen(c) for c in dentro), \
            ("arriba y abajo, dentro del cuadro, la imagen borrosa", [c.name() if c else None for c in dentro])
        assert con_imagen(px(img, 0.5 * W, 0.5 * H)), "en el centro, el video"
        print(f"✓ Short con ▦ Relleno: borroso arriba y abajo dentro del cuadro; fuera, solo el fondo "
              f"({len(fuera)} puntos fuera comprobados)")

        # Un fotograma que llega tarde a una capa oculta (con el tamaño de lienzo de otro proyecto)
        layer.hide()
        layer._W, layer._H = 1920.0, 1080.0
        layer._set_bg_source(img.copy(0, 0, 320, 180))
        assert not layer.fill.isVisible(), "una capa oculta no vuelve a enseñar su relleno al llegarle un fotograma"
        win.engine.seek(1.1)
        pump(app, 0.8)
        assert layer.fill.isVisible() and abs(layer.fill.sceneBoundingRect().width() - W) < 2 and \
            abs(layer.fill.sceneBoundingRect().height() - H) < 2, layer.fill.sceneBoundingRect()
        print("✓ capa oculta: un fotograma tardío no enseña el relleno; al volver a verse, del tamaño del lienzo")

        # Un clip escalado / movido a mano que se sale del cuadro por los lados
        ctrl.set_clip_layout(cid, {"x": -0.6, "y": 0.3, "w": 2.2, "h": 0.4, "fit": "contain", "bg": "none"})
        win.engine.seek(1.2)
        pump(app, 1.0)
        img = grab("vertical_escalado.png")
        r = layer.box.sceneBoundingRect()
        assert r.left() < -0.1 * W and r.right() > 1.1 * W, ("la caja del clip se sale del cuadro", r)
        fuera = lados(img, W, H, (0.4 * H, 0.5 * H, 0.6 * H), margen=0.05 * W)
        assert len(fuera) >= 2, "el visor deja ver lo de fuera del cuadro"
        malos = [(pt, c.name()) for pt, c in fuera if not es_fondo(c)]
        assert not malos, ("lo que se sale del cuadro no se ve", malos)
        for x in (0.03, 0.97):                       # (las barras de prueba tienen zonas negras: basta una fila)
            assert any(con_imagen(px(img, x * W, y * H)) for y in (0.33, 0.4, 0.45, 0.5, 0.55, 0.6, 0.67)), \
                ("dentro del cuadro, el clip llega hasta el borde", x)
        print("✓ clip escalado que se sale por los lados: lo de fuera no se ve, dentro sí")
        ctrl.undo_stack.undo()
        assert (p.clips[cid].layout or {}).get("x", 0.0) == 0.0, p.clips[cid].layout

        # Exportación vertical: del tamaño del proyecto y con el borroso arriba y abajo
        fr = exportar(p, 1.0, "vertical.mp4")
        assert fr.shape[0] == 480 and fr.shape[1] == 270, fr.shape
        assert fr[20, 135].max() > 40 and fr[460, 135].max() > 40, ("al exportar, borroso arriba y abajo",
                                                                    fr[20, 135], fr[460, 135])
        print(f"✓ exportación vertical: {fr.shape[1]}×{fr.shape[0]} (9:16) con el fondo borroso arriba y abajo")

        # YouTube (16:9): el relleno sigue dentro del cuadro
        win.workspaces.switch("youtube")
        pump(app, 0.4)
        p = ctrl.project
        W, H = p.width, p.height
        assert W > H, (W, H)
        (vid_id,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
        cid = ctrl.add_media([vid_id], v1.id, 0.0)[0]
        ctrl.set_fill([cid], dict(FILL.DEFAULT))
        ctrl.set_clip_layout(cid, {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5, "fit": "contain", "bg": "none"})
        win.engine.seek(1.0)
        pump(app, 1.2)
        img = grab("youtube_relleno.png")
        assert canvas.layers[v1.id].fill.isVisible(), "en YouTube el visor enseña el relleno"
        esquinas = [px(img, x * W, y * H) for x in (0.4, 0.6) for y in (0.08, 0.92)]   # (arriba y abajo del clip)
        assert all(c is not None and con_imagen(c) for c in esquinas), \
            ("YouTube: alrededor del clip pequeño, la imagen borrosa", [c.name() if c else None for c in esquinas])
        fuera = [c for _pt, c in lados(img, W, H, (0.5 * H,), margen=0.02 * W)]
        for y in (-0.02 * H, 1.02 * H):
            c = px(img, 0.5 * W, y)
            if c is not None:
                fuera.append(c)
        assert all(es_fondo(c) for c in fuera), ("YouTube: fuera del cuadro, solo el fondo", [c.name() for c in fuera])
        print(f"✓ YouTube 16:9: el relleno se ve dentro del cuadro y nada fuera ({len(fuera)} puntos fuera)")

        # 📱 Proyecto horizontal → «Vertical» (set_project_format): el visor coincide con la exportación
        ctrl.delete_clips([cid])                     # (un clip nuevo, tal cual entra en un proyecto horizontal)
        cid = ctrl.add_media([vid_id], v1.id, 0.0)[0]
        assert not FILL.of(p.clips[cid].fx)
        ctrl.set_project_format("short")
        pump(app, 0.4)
        assert (p.width, p.height) == (1080, 1920) and FILL.of(p.clips[cid].fx), (p.width, p.height)
        comparar_con_exportacion(p, v1.id, cid, 1.0, "formato")
        print("✓ de horizontal a vertical: el visor coincide con la exportación (video a todo el ancho, centrado)")

        # Un proyecto vertical guardado (como el tuyo: la caja algo más grande que el cuadro) y vuelto a abrir
        ctrl.set_clip_layout(cid, {"x": -0.0122, "y": -0.0142, "w": 1.0219, "h": 1.0219, "fit": "contain",
                                   "bg": "none"})
        eia = os.path.join(out, "vertical_guardado.eia")
        assert ctrl.save(eia, backup=False)
        win.workspaces.switch("youtube")
        pump(app, 0.4)
        win.workspaces.switch("short")
        pump(app, 0.4)
        ctrl.load(eia)
        pump(app, 0.6)
        p = ctrl.project
        assert (p.width, p.height) == (1080, 1920), (p.width, p.height)
        v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
        cid = next(c.id for c in p.clips.values() if c.track_id == v1.id)
        comparar_con_exportacion(p, v1.id, cid, 1.5, "cargado")
        # el fondo borroso, igual de borroso que en el archivo (a tamaño real: el desenfoque depende de la resolución)
        from editoria.core import still
        png = os.path.join(out, "export_cargado_real.png")
        still.render_frame(p, 1.5, png, ff)
        real = QImage(png).scaled(270, 480, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
            .convertToFormat(QImage.Format_RGB888)
        bpl = real.bytesPerLine()
        real = np.frombuffer(real.constBits(), np.uint8, bpl * 480).reshape(480, bpl)[:, :810] \
            .reshape(480, 270, 3).astype(int)
        vis = visor_rgb("visor_cargado_real.png")
        arriba = float(np.abs(vis[10:140] - real[10:140]).mean())
        abajo = float(np.abs(vis[340:470] - real[340:470]).mean())
        assert arriba < 25 and abajo < 25, ("el relleno del visor, como el exportado", round(arriba, 1),
                                            round(abajo, 1))
        print(f"✓ proyecto vertical guardado y abierto: el visor coincide con la exportación "
              f"(relleno: diferencia {arriba:.0f}/{abajo:.0f} de 255)")

        # 🧲 Imán al mover en el visor: centro y bordes del cuadro, con línea guía; Ctrl = sin imán
        ctrl.set_clip_layout(cid, None)
        win.timeline.set_selection([cid])
        (win.preview.set_mode if hasattr(win.preview, "set_mode") else canvas.set_mode)("transform")
        win.engine.seek(1.0)
        pump(app, 0.8)
        assert canvas._tf and canvas._tf.get("clip") == cid, canvas._tf
        k = canvas.transform().m11()
        W, H = p.width, p.height

        def arrastrar(desde, hasta, mods=Qt.NoModifier):
            vp = canvas.viewport()
            lineas = []
            for kind, sp in ((QEvent.MouseButtonPress, desde), (QEvent.MouseMove, QPointF(
                    (desde.x() + hasta.x()) / 2, (desde.y() + hasta.y()) / 2)), (QEvent.MouseMove, hasta),
                             (QEvent.MouseButtonRelease, hasta)):
                pos = QPointF(canvas.mapFromScene(sp))
                ev = QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos)),
                                 Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton,
                                 Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton,
                                 mods if kind == QEvent.MouseMove else Qt.NoModifier)
                QApplication.sendEvent(vp, ev)
                if kind == QEvent.MouseMove:
                    lineas = list(canvas.snap_guides.lines)
                app.processEvents()
            pump(app, 0.2)
            return lineas

        centro = QPointF(W / 2, H / 2)
        arrastrar(centro, QPointF(W / 2 + 45 / k, H / 2))            # 45 px de pantalla: lejos del imán
        lay = p.clips[cid].layout
        assert lay and abs(lay["x"] - 45 / k / W) < 0.02, ("se movió sin pegarse", lay)
        cx_box = (lay["x"] + lay["w"] / 2) * W
        lineas = arrastrar(QPointF(cx_box, H / 2), QPointF(W / 2 + 4 / k, H / 2))   # a 4 px del centro
        lay = p.clips[cid].layout
        assert abs(lay["x"] + lay["w"] / 2 - 0.5) < 1e-3, ("se pega al centro del cuadro", lay)
        assert ("v", W / 2) in [(a, round(b, 3)) for a, b in lineas] or any(
            a == "v" and abs(b - W / 2) < 0.5 for a, b in lineas), ("línea guía en el centro", lineas)
        assert not canvas.snap_guides.lines, "al soltar, la línea guía desaparece"
        arrastrar(centro, QPointF(W / 2 + 4 / k, H / 2), Qt.ControlModifier)
        lay = p.clips[cid].layout
        assert abs((lay["x"] + lay["w"] / 2 - 0.5) * W - 4 / k) < 3 / k, ("con Ctrl, sin imán", lay)
        print(f"✓ imán al mover: a 4 px se pega al centro (línea guía {len(lineas)}), lejos no; con Ctrl no se pega")
        # el borde de lo que SE VE (no la caja) se pega al borde de arriba
        ctrl.set_clip_layout(cid, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "contain", "bg": "none"})
        pump(app, 0.3)
        rel = canvas._tf_content_rel()
        assert 0.3 < rel[1] < 0.36 and rel[3] < 0.35, ("lo que se ve es la franja del medio", rel)
        top_px = rel[1] * H
        arrastrar(centro, QPointF(W / 2, H / 2 - top_px + 5 / k))
        lay = p.clips[cid].layout
        assert abs(lay["y"] + rel[1]) < 1e-3, ("el borde de arriba del video se pega al borde del cuadro", lay)
        print("✓ imán en los bordes de lo que se ve: el video se pega arriba del cuadro (no su caja)")

        # ⊕ Centrar en el Inspector (un solo Ctrl+Z cada uno)
        ctrl.set_clip_layout(cid, {"x": 0.1, "y": -0.1, "w": 0.6, "h": 0.6, "fit": "contain", "bg": "none"})
        win.timeline.set_selection([])
        pump(app, 0.1)
        win.timeline.set_selection([cid])
        pump(app, 0.3)
        tb = win.inspector.transform_box
        tb.refresh()
        botones = {b.text(): b for b in tb.findChildren(QPushButton)}
        nombres = ("⊕ Centrar", "↔ Centro horizontal", "↕ Centro vertical")
        assert set(nombres) <= set(botones), sorted(botones)
        assert all(botones[t].toolTip() for t in nombres), "la explicación va en el tooltip"
        botones["↕ Centro vertical"].click()
        lay = p.clips[cid].layout
        assert abs(lay["y"] - 0.2) < 1e-3 and abs(lay["x"] - 0.1) < 1e-3, ("solo en vertical", lay)
        n0 = ctrl.undo_stack.count()
        botones["⊕ Centrar"].click()
        lay = p.clips[cid].layout
        assert abs(lay["x"] - 0.2) < 1e-3 and abs(lay["y"] - 0.2) < 1e-3, ("centrado en los dos ejes", lay)
        assert ctrl.undo_stack.count() == n0 + 1, "centrar = un paso de Ctrl+Z"
        ctrl.set_clip_layout(cid, {"x": 0.0, "y": 0.3, "w": 0.6, "h": 0.6, "fit": "contain", "bg": "none"})
        n0 = ctrl.undo_stack.count()
        botones["↔ Centro horizontal"].click()
        lay = p.clips[cid].layout
        assert abs(lay["x"] - 0.2) < 1e-3 and abs(lay["y"] - 0.3) < 1e-3, ("solo en horizontal", lay)
        assert ctrl.undo_stack.count() == n0 + 1
        ctrl.undo_stack.undo()
        assert abs(p.clips[cid].layout["x"]) < 1e-3, "un Ctrl+Z lo devuelve"
        print("✓ ⊕ Centrar · ↔ Centro horizontal · ↕ Centro vertical en el Inspector, un Ctrl+Z cada uno")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
