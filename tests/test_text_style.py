"""
Prueba de los TEXTOS estilo Resolve: fuente, tipo, color, tamaño, interletrado/interlineado, estilo, mayúsculas,
justificado, posición, zoom, rotación, trazo, sombra y fondo (esquinas, contorno, opacidad). Lo que se exporta
es igual que lo que se ve en el visor (mismo dibujo). Cada opción con ↺ (fábrica) y «mi estilo» recordado para
los textos nuevos. Los textos antiguos se ven igual que antes.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_text_style.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def qimg_rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return a[:, :w * 3].reshape(h, w, 3).astype(int)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("texto/mi_estilo", "texto/recordar")}
    st.remove("texto/mi_estilo")
    st.remove("texto/recordar")
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core import title_render as TR
    from editoria.core.model import TRACK_TEXT
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.subtitle_item import paint_title
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    W, H = 1280, 720

    # 1) Dibujo: fondo redondeado, sombra, trazo, rotación…
    t = dict(TR.FACTORY, content="este estilo me gusta", font="Bahnschrift", font_style="Condensed",
             color="#FFFFFF", size=8.0, tracking=4, case="upper", x=0.5, y=0.5, rotation=0,
             stroke_size=6, stroke_color="#E5413C", shadow=True, shadow_x=6, shadow_y=6, shadow_blur=20,
             box=True, box_color="#1E90FF", box_radius=30, box_opacity=0.5, box_outline_width=3,
             box_outline_color="#FFFFFF")
    img, pos = TR.render(t, W, H)
    assert img.width() > 300 and abs(pos.x() + img.width() / 2 - W / 2) < 40, (img.width(), pos)
    a = qimg_rgb(img)
    blue = ((a[..., 2] > 120) & (a[..., 0] < 120)).mean()
    white = ((a > 220).all(axis=2)).mean()
    assert blue > 0.05 and white > 0.02, (blue, white)
    t_rot = dict(t, rotation=30)
    img_r, _ = TR.render(t_rot, W, H)
    assert img_r.height() > img.height() * 1.5, "la rotación inclina el texto"
    old = {"content": "ORIGINAL", "x": 0.5, "y": 0.2, "size": 6.0, "color": "#FFFFFF", "box": False, "bold": True,
           "font": "Arial"}
    io, _ = TR.render(old, W, H)
    ao = qimg_rgb(io)
    assert (ao.sum(axis=2) < 60).mean() > 0.02, "los textos antiguos sin caja conservan su contorno negro"
    print("✓ dibujo: fondo redondeado con contorno, sombra, trazo, mayúsculas, interletrado, rotación; "
          "los textos antiguos se ven como antes")

    # 2) En la app: el Inspector cambia cada opción, ↺ vuelve a fábrica, «mi estilo» para los nuevos
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    ctrl = win.ctrl
    ctrl.set_project_format("youtube") if hasattr(ctrl, "set_project_format") else None
    cid = ctrl.add_text(0.0, 4.0, "este estilo me gusta")
    cid = cid if isinstance(cid, str) else next(c.id for c in ctrl.project.clips.values() if c.text)
    win.timeline.set_selection([cid])
    pump(app, 0.3)
    ins = win.inspector
    assert ins.text_remember.isChecked()
    ins.tw["shadow"][0].setChecked(True)
    ins.tw["shadow_blur"][0].setValue(35)
    ins.tw["size"][0].setValue(9.5)
    ins.tw["box"][0].setChecked(True)
    ins.tw["box_radius"][0].setValue(25)
    ins.tw["box_opacity"][0].setValue(40)            # %
    ins.tw["tracking"][0].setValue(5)
    ins.text_case.setCurrentIndex(ins.text_case.findData("upper"))
    ins.text_case.activated.emit(ins.text_case.currentIndex())
    ins._align_btns["left"].click()
    ins.text_x.setValue(400)                          # píxeles, como Resolve
    tx = ctrl.project.clips[cid].text
    assert tx["shadow"] and tx["shadow_blur"] == 35 and tx["size"] == 9.5 and tx["box_radius"] == 25
    assert abs(tx["box_opacity"] - 0.4) < 1e-6 and tx["case"] == "upper" and tx["align"] == "left"
    assert abs(tx["x"] - 400 / ctrl.project.width) < 1e-3, tx["x"]
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "inspector_texto.png"))
    # ↺ de una opción: vuelve a fábrica
    holder = ins.tw["shadow_blur"][0].parentWidget()
    from PySide6.QtWidgets import QToolButton
    holder.findChild(QToolButton).click()
    assert ctrl.project.clips[cid].text["shadow_blur"] == TR.FACTORY["shadow_blur"]
    # Memoria: el texto nuevo nace con mis valores
    mine = TR.my_style()
    assert mine.get("size") == 9.5 and mine.get("shadow") is True and mine.get("box_radius") == 25, mine
    c2 = ctrl.add_text(5.0, 3.0, "otro")
    c2 = c2 if isinstance(c2, str) else None
    t2 = next(c.text for c in ctrl.project.clips.values() if c.text and c.text.get("content") == "otro")
    assert t2["size"] == 9.5 and t2["shadow"] and t2["box_radius"] == 25 and t2["case"] == "upper", t2
    ins.text_remember.setChecked(False)
    ctrl.add_text(9.0, 2.0, "de fábrica")
    t3 = next(c.text for c in ctrl.project.clips.values() if c.text and c.text.get("content") == "de fábrica")
    assert t3.get("size") != 9.5 and not t3.get("shadow"), t3
    ins.text_remember.setChecked(True)
    print("✓ Inspector: cada opción cambia el texto, ↺ vuelve a fábrica y los textos nuevos nacen con «mi estilo»")

    # 3) Exportar = lo que se ve en el visor (mismo dibujo, en su sitio)
    p = ctrl.project
    for c in [c for c in p.clips.values() if c.text and c.id != cid]:
        ctrl.delete_clips([c.id])
    mp4 = os.path.join(out, "texto.mp4")
    args, _tot = build_command(p, ExportOptions(path=mp4, width=p.width, height=p.height, fps=30, encoder="cpu",
                                                bitrate_mbps=8), media_tools.ffmpeg(), os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]
    f = media_tools.frame_rgb(mp4, 2.0, p.width).astype(int)
    ref = QImage(p.width, p.height, QImage.Format_RGB888)
    ref.fill(0)
    from PySide6.QtGui import QPainter
    pa = QPainter(ref)
    paint_title(pa, p.clips[cid].text, 2.0, 4.0, p.width, p.height)
    pa.end()
    rr = qimg_rgb(ref)
    diff = np.abs(f - rr).mean()
    assert diff < 6.0, f"lo exportado no coincide con el visor (diferencia media {diff:.1f})"
    print(f"✓ exportado igual que en el visor (diferencia media {diff:.1f} sobre 255)")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    for k in ("ventana/paneles", "guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
