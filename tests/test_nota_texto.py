"""
Prueba de la 📝 Nota de texto (Efectos → «📝 Nota de texto»):
  · el panel la tiene (texto de varias líneas, fuentes de Reclaimer, tamaño, color, fondo borroso con sus barritas y su
    miniatura) y «Añadir en el cabezal» crea un texto PROPIO en la pista de textos (sin tocar subtítulos ni
    transcripción), de 4 s, con un Ctrl+Z; soltarla en la línea de tiempo la pone en ese segundo;
  · la barrita «Tamaño del borroso» va de ajustado al texto a TODA la pantalla, de forma continua (y se deshace);
  · en el visor: se elige con un clic, se mueve arrastrando y se escala con las esquinas (un Ctrl+Z por arrastre), y
    el borroso la sigue; las capas de video desenfocan el recuadro (más borroso dentro que fuera);
  · el Inspector deja cambiar el borroso (casilla y barritas);
  · al EXPORTAR: dentro del recuadro la imagen es más lisa que fuera, y al 100 % todo el fotograma sale desenfocado
    (salvo el texto); visor y exportación usan el mismo recuadro;
  · se guarda y se abre con el proyecto; un proyecto viejo (sin esas claves) se abre igual, sin borroso.
Usa una carpeta de datos TEMPORAL.
Ejecutar:  .venv/Scripts/python.exe tests/test_nota_texto.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def detalle(img: np.ndarray) -> float:
    """Cuánto detalle tiene (varianza del laplaciano): una imagen desenfocada da poco."""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def grab_rgb(widget) -> np.ndarray:
    img = widget.grab().toImage().convertToFormat(widget.grab().toImage().Format.Format_RGB888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return a[:, :w * 3].reshape(h, w, 3).copy()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    import cv2
    from editoria.core import media as M
    from editoria.core import nota_texto as NT
    from editoria.core.model import TRACK_TEXT, TRACK_VIDEO, Project
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui import preview as PV
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", vid], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height = 640, 360
    win.preview.canvas.set_canvas_size(640, 360)
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([mid], v1.id, 0.0)
    subs_before = json.dumps(p.subtitles.__dict__, default=str, sort_keys=True)
    trans_before = json.dumps(p.transcripts, sort_keys=True)

    # --- Panel Efectos → 📝 Nota de texto
    ep = win.effects
    assert ep.tabs_fx.tabText(1) == "📝 Nota de texto", [ep.tabs_fx.tabText(i) for i in range(ep.tabs_fx.count())]
    assert not ep.b_note_add.icon().isNull(), "con su miniatura, como los demás efectos"
    favs = NT.fuentes()
    assert "Arial" in favs and len(favs) >= 3, favs
    assert ep.note_font.itemData(0) == favs[0] and ep.note_font.count() > len(favs) + 5, "Reclaimer arriba y todas"
    ep.note_text.setPlainText("Ojo aquí\nsegunda línea")
    ep.note_font.setCurrentIndex(ep.note_font.findData("Arial"))
    ep.note_size.setValue(70)                    # 7 %
    ep.set_note_color("#FFD400")
    ep.note_blur.setChecked(True)
    ep.note_zsize.setValue(0)
    ep.note_zstr.setValue(80)
    ep.note_zdark.setValue(20)
    win.engine.seek(2.0)
    pump(app, 0.2)
    n_clips = len(p.clips)
    nid = ep.add_note_at(None)
    c = p.clips[nid]
    assert p.track(c.track_id).kind == TRACK_TEXT and abs(c.start - 2.0) < 1e-6 and abs(c.duration - 4.0) < 1e-6
    t = c.text
    assert t["content"] == "Ojo aquí\nsegunda línea" and t["font"] == "Arial" and t["size"] == 7.0
    assert t["color"] == "#FFD400" and t["zone_blur"] is True and t["zone_size"] == 0.0
    assert t["zone_strength"] == 0.8 and t["zone_dark"] == 0.2 and not t.get("blur_under") and not t["box"]
    assert json.dumps(p.subtitles.__dict__, default=str, sort_keys=True) == subs_before
    assert json.dumps(p.transcripts, sort_keys=True) == trans_before
    assert win.timeline.selected == {nid} or list(win.timeline.selected) == [nid]
    ctrl.undo_stack.undo()
    assert nid not in p.clips and len(p.clips) == n_clips
    ctrl.undo_stack.redo()
    assert nid in p.clips
    print("✓ Efectos → 📝 Nota de texto: texto propio en la pista de textos (4 s, fuente, tamaño, color, borroso), sin "
          "tocar subtítulos ni transcripción; Ctrl+Z")
    win.timeline.note_dropped.emit(6.5)
    pump(app, 0.1)
    dropped = [x for x in p.clips.values() if x.text and abs(x.start - 6.5) < 1e-6]
    assert len(dropped) == 1 and dropped[0].text.get("zone_blur")
    ctrl.undo_stack.undo()
    print("✓ arrastrada a la línea de tiempo: en ese segundo")

    # --- La barrita: de ajustado a toda la pantalla, continuo
    W, H = 640, 360
    win.timeline.set_selection([nid])
    pump(app, 0.2)
    assert ep.note_zsize.value() == 0 and ep.note_zstr.value() == 80, "carga los valores del texto elegido"
    areas = []
    for v in range(0, 101, 10):
        r = NT.zone_rect(dict(p.clips[nid].text, zone_size=v / 100), W, H)
        areas.append((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]))
    assert all(b >= a for a, b in zip(areas, areas[1:])) and areas[0] < 0.25 * W * H and areas[-1] == W * H, areas
    ink = NT.ink_rect(p.clips[nid].text, W, H)
    r0 = NT.zone_rect(p.clips[nid].text, W, H)
    assert r0["x0"] <= ink[0] and r0["x1"] >= ink[0] + ink[2] and r0["r"] > 0, (r0, ink)
    ep.note_zsize.setValue(40)
    pump(app, 0.1)
    assert p.clips[nid].text["zone_size"] == 0.4
    ep.note_zsize.setValue(55)
    assert p.clips[nid].text["zone_size"] == 0.55
    ctrl.undo_stack.undo()                       # (un arrastre de la barrita = un paso)
    assert p.clips[nid].text["zone_size"] == 0.0, p.clips[nid].text["zone_size"]
    print(f"✓ «Tamaño del borroso»: de un recuadro ajustado ({areas[0] * 100 // (W * H)} % de la pantalla) a toda "
          "la pantalla, creciendo de forma continua; Ctrl+Z")

    # --- Inspector
    insp = win.inspector
    pump(app, 0.2)
    s_w, _put = insp.tw["zone_size"]
    g = insp.secciones["texto_borroso"].boton        # (el ● de su sección en el Inspector)
    assert g.isChecked() and s_w.value() == 0
    s_w.setValue(30)
    assert p.clips[nid].text["zone_size"] == 0.3
    insp.tw["zone_strength"][0].setValue(50)
    assert p.clips[nid].text["zone_strength"] == 0.5
    ctrl.undo_stack.undo()
    ep.note_zsize.setValue(0)
    ep.note_zstr.setValue(80)
    assert p.clips[nid].text["zone_size"] == 0.0 and p.clips[nid].text["zone_strength"] == 0.8
    print("✓ Inspector ▸ Texto ▸ «Fondo borroso alrededor»: casilla y barritas")

    # --- Visor: el recuadro se desenfoca en las capas de video
    eng = win.engine
    canvas = win.preview.canvas
    eng.seek(3.0)
    pump(app, 0.6)
    layer = canvas.layer(v1.id)
    eff = layer.box.graphicsEffect()
    assert isinstance(eff, PV.LookEffect) and eff.note_zones, eff
    z = eff.note_zones[0]
    assert (z["x0"], z["y0"], z["x1"], z["y1"]) == (r0["x0"], r0["y0"], r0["x1"], r0["y1"]), (z, r0)
    vp = canvas.viewport()

    def vista(rect):
        poly = canvas.mapFromScene(QRectF(*rect))
        b = poly.boundingRect()
        img = grab_rgb(vp)
        dpr = img.shape[1] / max(1, vp.width())
        x0, y0 = int(b.left() * dpr), int(b.top() * dpr)
        return img[y0:int(b.bottom() * dpr), x0:int(b.right() * dpr)]

    # franja del recuadro por ENCIMA del texto (sin letras): con borroso vs. sin borroso (mismo fotograma); con el
    # recuadro algo más grande (el visor de la prueba es pequeño) y sin la caja de mover encima (nada elegido)
    win.timeline.set_selection([])
    ctrl.set_text_props(nid, zone_size=0.35)
    pump(app, 0.5)
    rv = NT.zone_rect(p.clips[nid].text, W, H)
    ins = int(rv["r"] + rv["f"]) + 2                     # (sin las esquinas redondeadas)
    band = (rv["x0"] + ins, rv["y0"] + 2, rv["x1"] - rv["x0"] - 2 * ins, max(4, int(ink[1]) - rv["y0"] - 10))
    blurred_v = detalle(vista(band))
    cv2.imwrite(os.path.join(out, "visor_borroso.png"), cv2.cvtColor(grab_rgb(vp), cv2.COLOR_RGB2BGR))
    ctrl.set_text_props(nid, zone_blur=False)
    pump(app, 0.5)
    assert not getattr(layer.box.graphicsEffect(), "note_zones", None)
    sharp_v = detalle(vista(band))
    cv2.imwrite(os.path.join(out, "visor_sin.png"), cv2.cvtColor(grab_rgb(vp), cv2.COLOR_RGB2BGR))
    ctrl.undo_stack.undo()
    pump(app, 0.5)
    assert p.clips[nid].text["zone_blur"] is True and p.clips[nid].text["zone_size"] == 0.0
    assert blurred_v < 0.5 * sharp_v, (blurred_v, sharp_v)
    print(f"✓ visor: dentro del recuadro, detalle {sharp_v:.0f} → {blurred_v:.0f} (desenfoca el video de verdad)")

    # --- Visor: elegir con un clic, mover arrastrando y escalar con las esquinas
    win.timeline.set_selection([])
    pump(app, 0.2)
    cx = (ink[0] + ink[2] / 2) / W
    cy = (ink[1] + ink[3] / 2) / H
    assert win._text_at_now(cx, cy) == nid and win._text_at_now(0.02, 0.98) is None
    win.timeline.set_selection([nid])
    pump(app, 0.3)
    tf = canvas._tf
    assert tf and tf["clip"] == nid and tf["box"].get("_text"), tf
    x_before, y_before, size_before = (p.clips[nid].text[k] for k in ("x", "y", "size"))
    b = dict(tf["box"])
    canvas._tf_drag = {"mode": "move"}           # (como si se arrastrara con el ratón)
    canvas._tf_set(dict(b, x=b["x"] - 0.2, y=b["y"] + 0.1))
    pump(app, 0.1)
    assert abs(p.clips[nid].text["x"] - (x_before - 0.2)) < 0.002, "se ve al momento mientras arrastras"
    canvas._tf_drag = None
    canvas._tf_commit()
    pump(app, 0.3)
    t1 = p.clips[nid].text
    assert abs(t1["x"] - (x_before - 0.2)) < 0.002 and abs(t1["y"] - (y_before + 0.1)) < 0.002
    assert t1["size"] == size_before, "moverlo no cambia el tamaño"
    z1 = NT.zone_now(t1, 1.0, 4.0, W, H)
    assert abs((z1["x0"] - r0["x0"]) - (-0.2 * W)) <= 4 and abs((z1["y0"] - r0["y0"]) - 0.1 * H) <= 4, (z1, r0)
    eff = layer.box.graphicsEffect()
    assert eff.note_zones and eff.note_zones[0]["x0"] == z1["x0"], "el borroso sigue al texto"
    # esquina: más grande sin deformar
    b = dict(canvas._tf["box"])
    canvas._tf_drag = {"mode": "size"}
    canvas._tf_set(dict(b, w=b["w"] * 1.5, h=b["h"] * 1.5))
    canvas._tf_drag = None
    canvas._tf_commit()
    pump(app, 0.3)
    assert abs(p.clips[nid].text["size"] - size_before * 1.5) < 0.05, p.clips[nid].text["size"]
    ctrl.undo_stack.undo()
    assert p.clips[nid].text["size"] == size_before and abs(p.clips[nid].text["x"] - (x_before - 0.2)) < 0.002
    ctrl.undo_stack.undo()
    assert abs(p.clips[nid].text["x"] - x_before) < 1e-6, "cada arrastre, un Ctrl+Z"
    print("✓ visor: clic = elegir la nota; arrastrar = moverla (el borroso la sigue); esquina = tamaño; Ctrl+Z")

    # --- Con el RATÓN de verdad (QTest), en un visor pequeño, con la nota por defecto («Nota», 5 %)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    vp = canvas.viewport()

    def centro(cid):
        tb = NT.text_box(p.clips[cid].text, eng.time - p.clips[cid].start, canvas.W, canvas.H)
        return canvas.mapFromScene(QPointF((tb["x"] + tb["w"] / 2) * canvas.W, (tb["y"] + tb["h"] / 2) * canvas.H)), tb

    def arrastrar(c0, d, pasos=4):
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, c0)
        for k in range(1, pasos + 1):
            QTest.mouseMove(vp, c0 + QPoint(int(d.x() * k / pasos), int(d.y() * k / pasos)))
            pump(app, 0.02)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, c0 + d)
        pump(app, 0.3)

    def raton_desde_el_centro(etiqueta):
        win.timeline.set_selection([])
        pump(app, 0.2)
        ep.note_text.setPlainText("Nota")
        ep.note_size.setValue(50)
        did = ep.add_note_at(4.0)
        eng.seek(4.5)
        pump(app, 0.4)
        c0, tb = centro(did)
        k = canvas.transform().m11()             # (px de pantalla por px del lienzo)
        print(f"   ({etiqueta}: caja de {tb['w'] * canvas.W * k:.0f}×{tb['h'] * canvas.H * k:.0f} px en un visor de "
              f"{vp.width()} px)")
        assert canvas._tf and canvas._tf["clip"] == did
        assert canvas._tf_hit(canvas.mapToScene(c0))[0] == "move", canvas._tf_hit(canvas.mapToScene(c0))
        t0 = dict(p.clips[did].text)
        n0 = ctrl.undo_stack.index()
        arrastrar(c0, QPoint(40, 25))
        t1 = p.clips[did].text
        assert t1["size"] == t0["size"] and t1.get("zoom_x", 1.0) == t0.get("zoom_x", 1.0), "desde el centro: MOVER"
        assert abs((t1["x"] - t0["x"]) * canvas.W * k - 40) < 4 and abs((t1["y"] - t0["y"]) * canvas.H * k - 25) < 4, \
            (t0["x"], t1["x"], t0["y"], t1["y"])
        assert ctrl.undo_stack.index() == n0 + 1, "un arrastre = un paso"
        ctrl.undo_stack.undo()
        assert p.clips[did].text["x"] == t0["x"]
        ctrl.undo_stack.undo()                   # (fuera la nota de prueba)
        assert did not in p.clips

    raton_desde_el_centro("horizontal")
    p.width, p.height = 360, 640                 # 📱 en vertical
    canvas.set_canvas_size(360, 640)
    eng._sync()
    raton_desde_el_centro("vertical")
    p.width, p.height = 640, 360
    canvas.set_canvas_size(640, 360)
    eng._sync()
    print("✓ ratón real: arrastrar desde el centro de una nota pequeña la MUEVE (horizontal y vertical)")

    # clic con temblor: ningún paso de deshacer; y volver al punto de partida no deja la copia vieja
    win.timeline.set_selection([nid])
    eng.seek(3.0)
    pump(app, 0.4)
    c0, _tb = centro(nid)
    n0 = ctrl.undo_stack.index()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, c0)
    QTest.mouseMove(vp, c0 + QPoint(1, 1))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, c0 + QPoint(1, 1))
    pump(app, 0.2)
    arrastrar(c0, QPoint(0, 0) + QPoint(12, 8), 2)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, c0 + QPoint(12, 8))
    QTest.mouseMove(vp, c0 + QPoint(30, 20))
    pump(app, 0.05)
    QTest.mouseMove(vp, c0 + QPoint(12, 8))
    pump(app, 0.05)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, c0 + QPoint(12, 8))       # (vuelve a donde empezó)
    pump(app, 0.3)
    assert ctrl.undo_stack.index() == n0 + 1, ("solo el arrastre de verdad deja paso", ctrl.undo_stack.index() - n0)
    assert not getattr(win, "_tf_text0", {}), "ninguna copia pendiente"
    ctrl.set_text_props(nid, color="#FF0000", zone_size=0.3)
    pump(app, 0.4)
    c1, _tb = centro(nid)
    arrastrar(c1, QPoint(20, 10))
    assert p.clips[nid].text["color"] == "#FF0000" and p.clips[nid].text["zone_size"] == 0.3, \
        "arrastrar no devuelve el color ni el borroso de antes"
    for _ in range(3):
        ctrl.undo_stack.undo()
    assert p.clips[nid].text["color"] == "#FFD400" and p.clips[nid].text["zone_size"] == 0.0
    assert abs(p.clips[nid].text["x"] - x_before) < 1e-6
    print("✓ clic con temblor: sin paso de deshacer; arrastrar después de cambiar color/borroso no los pierde")

    # modo Recortar con la nota elegida: sin errores
    errores = []
    viejo = sys.excepthook
    sys.excepthook = lambda *a: errores.append(a)
    canvas.set_mode("crop")
    pump(app, 0.1)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, c0)
    pump(app, 0.2)
    canvas.set_mode("transform")
    sys.excepthook = viejo
    assert not errores, errores
    # con el video (pantalla completa) elegido, un clic sobre la nota la elige y arrastrar no mueve el video
    win.timeline.set_selection([vc.id for vc in p.clips.values() if vc.text is None and vc.track_id == v1.id][:1])
    pump(app, 0.3)
    vclip = p.clips[list(win.timeline.selected)[0]]
    lay0 = vclip.layout
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, c0)
    pump(app, 0.3)
    assert list(win.timeline.selected) == [nid] and p.clips[vclip.id].layout == lay0
    print("✓ modo Recortar con la nota elegida: sin errores; con el video elegido, un clic en la nota la elige")

    # --- Exportación: dentro del recuadro más liso que fuera; al 100 %, todo desenfocado salvo el texto
    def exportar(nombre):
        mp4 = os.path.join(out, nombre)
        script = os.path.join(out, nombre + ".txt")
        args, _tot = build_command(p, ExportOptions(path=mp4, width=W, height=H, fps=30, encoder="cpu",
                                                    loudnorm=False, video_only=True), M.ffmpeg(), script)
        txt = open(script, encoding="utf-8").read()
        r = subprocess.run(args, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-1500:]
        return mp4, txt

    mp4, txt = exportar("nota.mp4")
    assert "alphamerge" in txt and "gblur" in txt and "enable='between(t,2.000,6.000)'" in txt, txt[-800:]
    assert "trim=start" not in txt, "sin trim: no guarda en memoria los fotogramas de antes de la nota"
    f_in = M.frame_rgb(mp4, 3.5, W)
    f_out = M.frame_rgb(mp4, 1.5, W)                         # (antes de la nota: el mismo sitio, nítido)
    rz = NT.zone_rect(p.clips[nid].text, W, H)
    ins = int(rz["r"] + rz["f"]) + 2
    zb = (rz["x0"] + ins, rz["y0"] + 2, rz["x1"] - ins, max(rz["y0"] + 5, int(ink[1]) - 2))   # franja sin letras
    inside = f_in[zb[1]:zb[3], zb[0]:zb[2]]
    inside_before = f_out[zb[1]:zb[3], zb[0]:zb[2]]
    outside = f_in[:, :max(8, rz["x0"] - 8)]
    var_in, var_before, var_outside = detalle(inside), detalle(inside_before), detalle(outside)
    assert var_in < 0.35 * var_before and var_in < 0.35 * var_outside, (var_in, var_before, var_outside)
    # mismo recuadro que el visor: justo fuera del recuadro, nítido como antes
    edge = f_in[rz["y0"]:rz["y1"], max(0, rz["x0"] - 26):max(1, rz["x0"] - 4)]
    edge_before = f_out[rz["y0"]:rz["y1"], max(0, rz["x0"] - 26):max(1, rz["x0"] - 4)]
    assert detalle(edge) > 0.7 * detalle(edge_before), (detalle(edge), detalle(edge_before))
    print(f"✓ exportado: detalle dentro del recuadro {var_in:.0f} (antes {var_before:.0f}, fuera {var_outside:.0f})")
    ctrl.set_text_props(nid, zone_size=1.0)
    mp4b, txtb = exportar("nota_100.mp4")
    assert "alphamerge" not in txtb, "toda la pantalla: sin máscara"
    full_in, full_before = M.frame_rgb(mp4b, 3.5, W), M.frame_rgb(mp4b, 1.5, W)
    top = slice(0, max(8, int(ink[1]) - 6))                  # todo lo de encima del texto
    bot = slice(min(H - 8, int(ink[1] + ink[3]) + 6), H)     # y lo de debajo
    for part in (top, bot):
        a, bf = detalle(full_in[part]), detalle(full_before[part])
        assert a < 0.35 * bf, (a, bf)
    letters = full_in[int(ink[1]):int(ink[1] + ink[3]), int(ink[0]):int(ink[0] + ink[2])]
    assert detalle(letters) > 3 * detalle(full_in[top]), "el texto sigue nítido"
    print("✓ exportado al 100 %: todo el fotograma desenfocado salvo el texto")
    ctrl.undo_stack.undo()

    # --- Memoria: el borroso (y una capa de ajuste) tarde en el video NO guarda en memoria los fotogramas de antes
    def pico_mb(args) -> float:
        """Pico de memoria (MB) del ffmpeg de la exportación (Windows: PeakWorkingSetSize)."""
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        log = os.path.join(out, "mem_ffmpeg.log")
        flog = open(log, "wb")          # (a un archivo: con PIPE, ffmpeg se quedaba esperando a que se leyera)
        pr = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=flog, stdin=subprocess.DEVNULL)
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        pico = 0
        get = ctypes.windll.psapi.GetProcessMemoryInfo
        while pr.poll() is None:
            if get(wintypes.HANDLE(int(pr._handle)), ctypes.byref(pmc), pmc.cb):
                pico = max(pico, pmc.PeakWorkingSetSize, pmc.PeakPagefileUsage)
            time.sleep(0.03)
        flog.close()
        err = open(log, "rb").read().decode("utf-8", "replace")
        assert pr.returncode == 0, err[-1500:]
        return pico / 1e6

    vid2 = os.path.join(out, "largo.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=640x360:r=30:d=24", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    vid2], check=True)

    def proyecto_largo(t_nota: float, que: str) -> Project:
        q = Project.from_dict(json.loads(json.dumps(p.to_dict())))
        for cid in [k for k, x in q.clips.items()]:
            del q.clips[cid]
        mi = next(k for k, m in q.media.items() if m.kind == "video")
        q.media[mi].path, q.media[mi].duration = vid2, 24.0
        from editoria.core.model import Clip, new_id
        cv = Clip(new_id(), mi, v1.id, 0.0, 0.0, 24.0)
        q.clips[cv.id] = cv
        ttr = next(x for x in q.tracks if x.kind == TRACK_TEXT)
        if que == "nota":
            tn = Clip(new_id(), "", ttr.id, t_nota, 0.0, 3.0, text=dict(p.clips[nid].text))
            q.clips[tn.id] = tn
        return q

    adj_mid = ctrl.generator_media({"kind": "adjust"})
    picos = {}
    for t_nota in (1.0, 20.0):
        q = proyecto_largo(t_nota, "nota")
        sc = os.path.join(out, f"mem_{int(t_nota)}.txt")
        args_m, _ = build_command(q, ExportOptions(path=os.path.join(out, f"mem_{int(t_nota)}.mp4"), width=W, height=H,
                                                   fps=30, encoder="cpu", loudnorm=False, video_only=True),
                                  M.ffmpeg(), sc)
        g_txt = open(sc, encoding="utf-8").read()
        assert "nzm" in g_txt and "trim=start" not in g_txt, "sin trim antes del overlay"
        picos[t_nota] = pico_mb(args_m)
    assert picos[20.0] < picos[1.0] + 60, picos
    print(f"✓ memoria del ffmpeg con la nota en el segundo 1 / 20: {picos[1.0]:.0f} / {picos[20.0]:.0f} MB (no crece)")
    # 🎨 capa de ajuste a los 20 s: igual
    picos_aj = {}
    for t_aj in (1.0, 20.0):
        q = proyecto_largo(t_aj, "ajuste")
        from editoria.core.model import Clip, Track, new_id
        ta = Track(new_id(), TRACK_VIDEO, "V9")
        q.tracks.insert(0, ta)
        ca = Clip(new_id(), adj_mid, ta.id, t_aj, 0.0, 3.0, fx={"bw": 1.0})
        q.clips[ca.id] = ca
        sc = os.path.join(out, f"aj_{int(t_aj)}.txt")
        args_a, _ = build_command(q, ExportOptions(path=os.path.join(out, f"aj_{int(t_aj)}.mp4"), width=W, height=H,
                                                   fps=30, encoder="cpu", loudnorm=False, video_only=True),
                                  M.ffmpeg(), sc)
        picos_aj[t_aj] = pico_mb(args_a)
        if t_aj == 20.0:      # en blanco y negro justo desde su fotograma (20 s) y no antes
            mp = os.path.join(out, "aj_20.mp4")
            sat = lambda f: float(cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 1].mean())    # noqa: E731
            assert sat(M.frame_rgb(mp, 19.9, W)) > 40 and sat(M.frame_rgb(mp, 20.1, W)) < 5 \
                and sat(M.frame_rgb(mp, 23.2, W)) > 40, (sat(M.frame_rgb(mp, 19.9, W)), sat(M.frame_rgb(mp, 20.1, W)))
    assert picos_aj[20.0] < picos_aj[1.0] + 60, picos_aj
    print(f"✓ capa de ajuste en el segundo 1 / 20: {picos_aj[1.0]:.0f} / {picos_aj[20.0]:.0f} MB; entra en su fotograma")

    # --- 🎨 Capa de ajuste: entra y sale en SU fotograma (base cuyo brillo sube con el n.º de fotograma; negativo)
    from types import SimpleNamespace
    from editoria.export.ffmpeg_export import adjust_filters
    import math as _m
    sw, sh = 64, 36

    def gris(g, last, n):
        r = subprocess.run([M.ffmpeg(), "-v", "error", "-filter_complex", g, "-map", f"[{last}]", "-frames:v", str(n),
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-600:]
        fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, sh, sw)
        return fr.reshape(len(fr), -1).mean(1)

    casos = [(fps, k / fps) for fps in (30.0, 60.0) for k in range(1, 6)] + [(30.0, 1.01), (60.0, 1.2345)]
    for fps, a in casos:
        b = a + 0.4
        n = int(b * fps) + 10
        base = (f"color=c=black:s={sw}x{sh}:r={fps:g}:d={n / fps:.3f},format=yuv420p,"
                f"geq=lum='40+1.5*N':cb=128:cr=128[base]")
        ca = SimpleNamespace(start=a, end=b, duration=b - a, fx={"invert": 100.0}, color=None, opacity=1.0, op_kf=None)
        fl, lab = adjust_filters(0, ca, "base", sw, sh, fps)
        res, ref = gris(";".join([base] + fl), lab, n), gris(base, "base", n)
        k0, k1 = _m.ceil(a * fps - 0.01), _m.ceil(b * fps - 0.01)
        for f in range(min(len(res), len(ref))):
            # dentro: el negativo de ESE fotograma (negate da 255-Y en rango limitado: en gris completo, 259,7 - x)
            want = min(255.0, 255 * 223 / 219 - ref[f]) if k0 <= f < k1 else ref[f]
            assert abs(res[f] - want) < 0.8, (fps, a, f, k0, k1, float(res[f]), float(want))
    print(f"✓ capa de ajuste: {len(casos)} inicios (k = 1…5 a 30 y 60 fps y no alineados) entran y salen en su "
          "fotograma, con el contenido de ese fotograma")

    # --- Guardar y abrir; proyecto viejo sin las claves
    d = json.loads(json.dumps(p.to_dict()))
    p2 = Project.from_dict(d)
    t2 = p2.clips[nid].text
    assert t2["zone_blur"] is True and t2["zone_strength"] == 0.8 and t2["content"] == "Ojo aquí\nsegunda línea"
    for cd in d["clips"]:
        if cd.get("text"):
            for k in NT.ZONE_KEYS:
                cd["text"].pop(k, None)
    p3 = Project.from_dict(d)
    assert NT.zone_of(p3.clips[nid].text) is None
    args3, _ = build_command(p3, ExportOptions(path=os.path.join(out, "viejo.mp4"), width=W, height=H, fps=30,
                                               encoder="cpu", loudnorm=False, video_only=True),
                             M.ffmpeg(), os.path.join(out, "viejo.txt"))
    assert "nzo" not in open(os.path.join(out, "viejo.txt"), encoding="utf-8").read()
    print("✓ se guarda y se abre con el proyecto; un proyecto viejo (sin esas claves) se abre igual, sin borroso")

    cv2.imwrite(os.path.join(out, "exportado.png"), cv2.cvtColor(f_in, cv2.COLOR_RGB2BGR))
    ctrl.undo_stack.setClean()
    win._media_dirty = False
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
