"""
Prueba de las pistas: proyecto nuevo con UNA sola pista de audio (sin nombres como «Música»), «➕ Pista» y
«↕ Tamaño» en la esquina encima de los nombres, renombrar a tu gusto con sugerencias (que dan su papel a la
pista) y que la música/efectos de la IA nunca caigan encima de tu voz.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_tracks.py <carpeta_salida>
"""
from __future__ import annotations

import os
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keys = ("ventana/paneles", "geometry", "timeline/alto_audio", "timeline/alto_video")
    keep = {k: st.value(k) for k in keys}
    app = QApplication(sys.argv)
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        w = MainWindow()
        w.resize(1920, 1040)
        w.show()
        pump(app, 0.8)
        ctrl, tl = w.ctrl, w.timeline
        p = ctrl.project
        audio = [t for t in p.tracks if t.kind == TRACK_AUDIO]
        assert [t.name for t in audio] == ["A1"] and not audio[0].role and audio[0].duck_db is None
        assert tl.track_badge(p.tracks.index(audio[0])) == ("A1", "Audio")
        print("✓ proyecto nuevo: una sola pista de audio «A1 · Audio» (sin Música/Narración por defecto)")

        add, bv, ba = tl._corner
        assert add.isVisible() and bv.isVisible() and ba.isVisible()
        assert "🎞" in bv.text() and "🔊" in ba.text(), "dos botones de tamaño separados"
        for b in (add, bv, ba):
            g = b.geometry()
            assert g.right() <= tl.HEADER_W and g.bottom() <= tl.RULER_H, ("fuera de la esquina", g)
        n0 = len(p.tracks)
        tl._add_track(TRACK_AUDIO)
        tl._add_track(TRACK_VIDEO)
        assert len(ctrl.project.tracks) == n0 + 2
        ctrl.undo_stack.undo()
        ctrl.undo_stack.undo()
        assert len(ctrl.project.tracks) == n0
        print("✓ «➕ Pista» (video/audio) encima de los nombres; se deshace")

        a0, v0 = tl.audio_h, tl.video_h
        tl._set_track_size("audio_h", 110)
        assert tl.audio_h == 110 and tl.video_h == v0
        tl._set_track_size("video_h", tl.video_h + 12)
        assert tl.video_h == v0 + 12
        tl._set_track_size("audio_h", 5)
        assert tl.audio_h == 28, "con límite"
        # Los dos botones: cada uno con su barrita (cualquier alto) y la rueda del ratón
        ba.slider.setValue(97)
        assert tl.audio_h == 97 and tl.video_h == v0 + 12, "la barrita de audio solo cambia el audio"
        assert "97 px" in ba.label.text()
        bv.slider.setValue(70)
        assert tl.video_h == 70 and tl.audio_h == 97
        from PySide6.QtCore import QPoint, QPointF, Qt as _Qt
        from PySide6.QtGui import QWheelEvent
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), _Qt.NoButton,
                         _Qt.NoModifier, _Qt.NoScrollPhase, False)
        ba.wheelEvent(ev)
        assert tl.audio_h == 103 and ba.slider.value() == 103, "rueda encima = más grande"
        pump(app, 0.5)
        h_sh = w.docks["timeline"].height()
        tl._set_track_size("audio_h", a0)
        tl._set_track_size("video_h", v0)
        print(f"✓ «🎞 ↕» y «🔊 ↕»: cada uno deja sus pistas del alto que quieras (barrita, tamaños, rueda) "
              f"(timeline {h_sh}px)")

        # Soltar un archivo DEBAJO de la última pista → pista nueva automática
        import subprocess
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDragMoveEvent, QDropEvent
        from editoria.core import media as media_tools
        from editoria.ui.common import MEDIA_MIME
        wav = os.path.join(out, "tono.wav")
        if not os.path.exists(wav):
            subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=f=440:d=3", wav], check=True)
        (mid,) = ctrl.import_now([wav])
        t0 = time.time()
        while ctrl.project.media[mid].duration <= 0 and time.time() - t0 < 20:
            pump(app, 0.1)
        n_a = sum(1 for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
        md = QMimeData()
        md.setData(MEDIA_MIME, mid.encode())
        y = tl.track_y(len(ctrl.project.tracks)) + tl.NEW_ZONE / 2
        x = tl.x_for(1.0)
        tl.dragMoveEvent(QDragMoveEvent(QPoint(int(x), int(y)), _Qt.CopyAction, md, _Qt.LeftButton, _Qt.NoModifier))
        assert tl._drop and tl._drop[0] == "new", tl._drop
        pump(app, 0.1)
        tl.grab().save(os.path.join(out, "franja_nueva.png"))
        tl.dropEvent(QDropEvent(QPointF(x, y), _Qt.CopyAction, md, _Qt.LeftButton, _Qt.NoModifier))
        audio_now = [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO]
        assert len(audio_now) == n_a + 1, "se creó una pista nueva"
        placed = ctrl.project.clips_on(audio_now[-1].id)
        assert len(placed) == 1 and placed[0].media_id == mid, "el archivo quedó en la pista nueva"
        # Soltar SOBRE una pista (vacía) no crea otra
        a_first = audio_now[0]
        y1 = tl.track_y(ctrl.project.tracks.index(a_first)) + 10
        tl.dragMoveEvent(QDragMoveEvent(QPoint(int(tl.x_for(20.0)), int(y1)), _Qt.CopyAction, md, _Qt.LeftButton,
                                        _Qt.NoModifier))
        tl.dropEvent(QDropEvent(QPointF(tl.x_for(20.0), y1), _Qt.CopyAction, md, _Qt.LeftButton, _Qt.NoModifier))
        assert len([t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO]) == n_a + 1
        ctrl.undo_stack.undo()
        ctrl.undo_stack.undo()
        assert len([t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO]) == n_a, "se deshace"
        print("✓ soltar un archivo en la franja de abajo crea una pista nueva (sobre una pista, no); se deshace")

        # La IA pide pista de música: nunca la A1 (tu voz), sino una nueva con «baja al hablar»
        a1 = audio[0]
        mt = ctrl.ensure_role_track("musica")
        assert mt != a1.id and ctrl.project.track(mt).duck_db == -12.0
        assert ctrl.ensure_role_track("musica") == mt, "reutiliza la misma"
        ft = ctrl.ensure_role_track("efectos")
        assert ft not in (a1.id, mt)
        ctrl.undo_stack.undo()
        ctrl.undo_stack.undo()
        assert [t.name for t in ctrl.project.tracks if t.kind == TRACK_AUDIO] == ["A1"]
        print("✓ música y efectos de la IA van a su propia pista (nunca encima de tu voz); se deshace")

        # Renombrar a placer: sugerencias + texto libre
        seen = {}

        def fake_item(_parent, _title, _label, items, _cur, editable):
            seen["items"], seen["editable"] = list(items), editable
            return seen["answer"], True
        orig = QInputDialog.getItem
        QInputDialog.getItem = staticmethod(fake_item)
        try:
            ctrl.add_track(TRACK_AUDIO)
            a2 = [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO][-1]
            seen["answer"] = "Música"
            tl._rename_track(a2)
            assert seen["editable"] and {"Narración", "Música", "Efectos"} <= set(seen["items"])
            a2 = ctrl.project.track(a2.id)
            assert a2.name == "Música" and a2.role == "musica" and a2.duck_db == -12.0
            assert ctrl.ensure_role_track("musica") == a2.id, "la que tú llamaste Música"
            seen["answer"] = "Mi canción favorita 🎵"
            tl._rename_track(a2)
            a2 = ctrl.project.track(a2.id)
            assert a2.name == "Mi canción favorita 🎵" and a2.role == "musica"
            assert tl.track_badge(ctrl.project.tracks.index(a2)) == ("A2", "Mi canción favorita 🎵")
            seen["answer"] = "Narración"
            tl._rename_track(ctrl.project.track(a1.id))
            a1n = ctrl.project.track(a1.id)
            assert a1n.role == "voz" and a1n.fx.get("eq")
            v = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
            seen["answer"] = "Gameplay"
            tl._rename_track(v)
            assert "Gameplay" in seen["items"] and "Música" not in seen["items"]
            assert ctrl.project.track(v.id).name == "Gameplay"
        finally:
            QInputDialog.getItem = orig
        print("✓ renombrar a tu gusto (texto libre), con sugerencias Narración/Música/Efectos… que dan su papel")
        pump(app, 0.3)
        tl.grab().save(os.path.join(out, "pistas.png"))
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        w.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK — captura en", out)


if __name__ == "__main__":
    main()
