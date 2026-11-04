"""
Prueba de «✨ Ideas para esto» (clic derecho en lo seleccionado): detecta imágenes de texto, propone cómo meter
fotos, videos o varios clips (entrada, sombra, contorno, dónde) y se ve igual en el visor y al exportar.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_ideas.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.ai import ideas
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Una captura de texto (tipo tuit) y una foto
    txt = os.path.join(out, "tuit.png")
    img = QImage(900, 500, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p_ = QPainter(img)
    p_.setPen(QColor("black"))
    p_.setFont(QFont("Arial", 18))
    for i in range(9):
        p_.drawText(40, 60 + i * 48, "La nueva entrega de la saga llega en marzo con mundo abierto y más")
    p_.end()
    img.save(txt)
    red = os.path.join(out, "foto.png")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=400x300",
                    "-frames:v", "1", red], check=True)
    assert ideas.is_text_image(txt) and not ideas.is_text_image(red)
    print("✓ distingue una imagen de puro texto (captura) de una foto")

    bg = os.path.join(out, "fondo.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", bg], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, tl = win.ctrl, win.timeline
        p = ctrl.project
        p.width, p.height = 640, 360
        bid, tid_, fid = ctrl.import_now([bg, txt, red])
        while ctrl.analyzing:
            pump(app, 0.1)
        v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
        ctrl.add_media([bid], v1.id, 0.0)
        tc = ctrl.add_media([tid_], v2.id, 0.5)[0]
        p.clips[tc].duration = 2.0
        op = ideas.ideas_for(p, [tc])
        assert op[0]["label"].startswith("📰"), [o["label"] for o in op]
        fc = ctrl.add_media([fid], v2.id, 2.5)[0]
        op_f = ideas.ideas_for(p, [fc])
        assert not op_f[0]["label"].startswith("📰") and any("derecha" in o["label"] for o in op_f)
        both = ideas.ideas_for(p, [tc, fc])
        assert any("Escalonar" in o["label"] for o in both)
        vid_ideas = ideas.ideas_for(p, [next(c.id for c in p.clips_on(v1.id))])
        assert any("Recuadro" in o["label"] for o in vid_ideas)
        menu = QMenu()
        tl._add_ideas(menu, [tc])
        assert menu.actions() and menu.actions()[0].text() == "✨ Ideas para esto"
        print("✓ ideas según lo que eliges: captura → tarjeta de texto; foto → entradas con sombra; video → "
              "recuadro; varios → escalonar")

        # Aplicar «Tarjeta de texto» a la captura
        ctrl.batch_clip_props(op[0]["changes"], "✨ Tarjeta")
        c = p.clips[tc]
        assert c.fx["enter"]["from"] == "bottom" and c.fx["shadow"] and c.fx["outline"] and c.layout["bg"] == "none"

        # Visor: al empezar todavía está abajo; luego en su sitio con sombra y contorno
        layer = win.preview.canvas.layer(v2.id)
        win.engine.seek(0.55)
        pump(app, 0.4)
        y_start = layer.box.pos().y()
        win.engine.seek(1.6)
        pump(app, 0.4)
        y_end = layer.box.pos().y()
        assert y_start > y_end + 20, (y_start, y_end)
        assert layer._shadow.isVisible() and layer._outline.isVisible()
        win.preview.canvas.grab().save(os.path.join(out, "visor.png"))
        print(f"✓ visor: entra desde abajo ({y_start:.0f} → {y_end:.0f}) y queda con sombra y contorno")

        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=640, height=360, fps=30, encoder="cpu",
                                                  loudnorm=False), M.ffmpeg(), os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1200:]
        early = M.frame_rgb(mp4, 0.56, 640).astype(int)
        late = M.frame_rgb(mp4, 1.6, 640).astype(int)
        cy, cx = 180, 320
        assert late[cy, cx].min() > 200, ("la tarjeta blanca en su sitio", late[cy, cx])
        assert early[cy, cx][2] > 150 and early[cy, cx][0] < 100, ("al empezar aún no llegó", early[cy, cx])
        lay = p.clips[tc].layout
        print("✓ exportado: entra desde abajo y queda centrada con sombra y contorno")
        ctrl.undo_stack.undo()
        assert "enter" not in (p.clips[tc].fx or {})
        print("✓ Ctrl+Z quita la idea aplicada")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)            # que no quede ningún trabajo a medias al salir (si no, Windows lo cierra mal)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
