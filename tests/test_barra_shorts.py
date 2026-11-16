"""
📱 Pestaña Shorts:
  · encima del visor, a la vista: 🎙 Transcribir, 💬 Subtítulos, 🔑 Palabras clave y ▦ Encuadrar (solo en Shorts);
  · un video horizontal añadido a un proyecto vertical se encaja solo: entero en el centro, arriba y abajo borroso
    (▦ Relleno); en YouTube (horizontal) no se toca; «▦ Encuadrar» lo hace con los que falten; un Ctrl+Z lo quita.
Ejecutar:  .venv/Scripts/python.exe tests/test_barra_shorts.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, MediaItem, new_id  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ctrl = win.ctrl
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        assert not win.preview.shorts_bar.isVisible(), "la barra de Shorts no sale en YouTube"
        textos = [b.text() for b in win.preview.shorts_bar.findChildren(QPushButton)]
        assert {"🎙 Transcribir", "💬 Subtítulos", "🔑 Palabras clave"} <= set(textos), textos

        def video_h(p):
            m = MediaItem(new_id(), "/falso/h.mp4", KIND_VIDEO, "h.mp4", duration=30.0, width=1920, height=1080,
                          probed=True)
            p.media[m.id] = m
            return m
        p = ctrl.project
        assert p.width > p.height
        m = video_h(p)
        v = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
        cid = ctrl.add_media([m.id], v.id, 0.0)[0]
        assert not (p.clips[cid].fx or {}).get("relleno"), "en YouTube no se encuadra"
        print("✓ YouTube: sin barra de Shorts y los videos se quedan como están")

        win.workspaces.switch("short")
        pump(app, 0.3)
        assert win.preview.shorts_bar.isVisible(), "en Shorts la barra está a la vista"
        p = ctrl.project
        assert p.height > p.width, (p.width, p.height)
        m = video_h(p)
        v = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
        cid = ctrl.add_media([m.id], v.id, 0.0)[0]
        c = p.clips[cid]
        assert (c.fx or {}).get("relleno") and c.layout and c.layout.get("fit") == "contain", (c.fx, c.layout)
        print("✓ Shorts: barra a la vista y un video horizontal entra encajado con arriba y abajo borroso")
        ctrl.undo_stack.undo()
        assert cid not in ctrl.project.clips
        ctrl.encuadre_auto_vertical = False
        cid = ctrl.add_media([m.id], v.id, 0.0)[0]
        assert not (ctrl.project.clips[cid].fx or {}).get("relleno")
        assert win._encuadrar_shorts() == 1 and (ctrl.project.clips[cid].fx or {}).get("relleno")
        ctrl.undo_stack.undo()
        assert not (ctrl.project.clips[cid].fx or {}).get("relleno")
        print("✓ apagado el automático: «▦ Encuadrar» lo hace con los que falten (y Ctrl+Z lo quita)")
        ctrl.encuadre_auto_vertical = True

        # 📱 la pestaña Shorts con un proyecto de YouTube guardado (lo que le pasaba al usuario): al entrar, vertical
        from editoria.core.controller import ProjectController
        otro = ProjectController()
        m2 = video_h(otro.project)
        v2 = next(t for t in otro.project.tracks if t.kind == TRACK_VIDEO)
        otro.add_media([m2.id], v2.id, 0.0)
        ruta = os.path.join(_TMP, "proyecto_youtube.eia")
        assert otro.project.format == "youtube" and otro.save(ruta, backup=False)
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        win.workspaces.settings.setValue(win.workspaces._key("short"), ruta)
        win.workspaces.stacks.pop("short", None)
        win.workspaces.switch("short")
        pump(app, 0.3)
        p = ctrl.project
        assert p.format == "short" and p.height > p.width, (p.format, p.width, p.height)
        c = next(iter(p.clips.values()))
        assert (c.fx or {}).get("relleno"), "y su video horizontal, con arriba y abajo borroso"
        print("✓ un proyecto de YouTube en la pestaña Shorts pasa solo a vertical 9:16 (con el fondo borroso)")
        import json
        with open(ruta, encoding="utf-8") as f:
            assert json.load(f).get("project_type") == "youtube"

        # 💬 Subtítulos automáticos: se recuerdan y, encendidos, un video con voz añadido en Shorts los pone solos
        from PySide6.QtCore import QSettings
        llamadas = []
        win.subtitles.quick_short = lambda: llamadas.append(1)
        mv = MediaItem(new_id(), "/falso/voz.mp4", KIND_VIDEO, "voz.mp4", duration=30.0, width=1920, height=1080,
                       has_audio=True, probed=True)
        ctrl.project.media[mv.id] = mv
        vt = next(t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO)
        win.btn_subs_auto.setChecked(False)
        assert QSettings("EditorIA", "EditorIA").value("shorts/subtitulos_auto", type=bool) is False
        ctrl.add_media([mv.id], vt.id, 40.0)
        pump(app, 0.7)
        assert llamadas == [], "apagado: no se ponen solos"
        win.btn_subs_auto.setChecked(True)
        assert QSettings("EditorIA", "EditorIA").value("shorts/subtitulos_auto", type=bool) is True
        ctrl.add_media([mv.id], vt.id, 80.0)
        pump(app, 0.7)
        assert llamadas == [1], "encendido: al añadir un video con voz, subtítulos solos"
        print("✓ «💬 Subtítulos auto»: se recuerda; encendido, al añadir un video con voz se ponen solos")

        # ⬆ Exportar un Short: «▯ Vertical» elegido solo (y para qué apps sirve, debajo)
        from editoria.ui.export_dialog import ExportDialog
        from PySide6.QtWidgets import QLabel
        dlg = ExportDialog(ctrl, win)
        assert dlg.target == "tiktok", dlg.target
        b_v = next(b for b in dlg.targets.buttons() if b.property("target") == "tiktok")
        assert b_v.text() == "▯ Vertical" and b_v.isChecked()
        assert any(l.text() == "TikTok · Shorts · Reels" for l in dlg.findChildren(QLabel))
        assert dlg.height_box.value() > dlg.width_box.value()
        dlg.close()
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        dlg = ExportDialog(ctrl, win)
        assert dlg.target != "tiktok", "un video horizontal no se queda en «Vertical»"
        dlg.close()
        print("✓ Exportar: en Shorts sale «▯ Vertical» elegido (TikTok · Shorts · Reels debajo); en YouTube, no")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
