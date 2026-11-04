"""
Prueba del clic derecho «como Resolve» y de lo pedido en la misma tanda:
  · Pegar e insertar · Insertar espacio · Cambiar duración (lo de detrás se mueve) · Eliminar atributos ·
    Eliminar solo el audio / solo el video · Activar/desactivar (D) · Color de clip · Normalizar volumen;
  · el menú se abre sin errores (clip de video con sonido vinculado);
  · alargar un borde se come los clips de al lado; con el imán se queda pegado al chocar;
  · un archivo que faltaba se reconecta al volver a añadirlo (misma ruta o mismo archivo en otra carpeta);
  · 👍 cocina el edit en un ⧉ clip compuesto · 🎛 Mix te lleva al principio del tramo.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_resolve_menu.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
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

from PySide6.QtCore import QPoint, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


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
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "con_sonido.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=10",
                    "-f", "lavfi", "-i", "sine=f=440:d=10", "-af", "volume=0.25", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, tl = win.ctrl, win.timeline
        p = ctrl.project
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        made = ctrl.add_media([mid], v1.id, 0.0)
        vc = next(i for i in made if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
        ac = next(i for i in ctrl.linked_ids([vc]) if i != vc)
        ctrl.split(4.0, ctrl.linked_ids([vc]))
        left = min((c for c in p.clips_on(v1.id)), key=lambda c: c.start)
        right = max((c for c in p.clips_on(v1.id)), key=lambda c: c.start)
        pump(app, 0.2)

        # el menú se abre sin errores
        tl.set_selection([left.id])
        QTimer.singleShot(250, lambda: app.activePopupWidget() and app.activePopupWidget().close())
        tl._clip_menu(left, tl.mapToGlobal(QPoint(300, 200)))
        print("✓ el clic derecho (ordenado como Resolve) se abre sin errores")

        # Insertar espacio: lo de detrás se mueve el largo de la selección
        r0 = right.start
        tl.set_selection([left.id])
        win._insert_gap()
        assert abs(p.clips[right.id].start - (r0 + left.duration)) < 1e-3, p.clips[right.id].start
        ctrl.undo_stack.undo()
        print("✓ Insertar espacio")
        # Cambiar duración: el clip dura 2 s y el de detrás se acerca
        ctrl.change_duration([left.id], 2.0)
        assert abs(p.clips[left.id].duration - 2.0) < 1e-3 and abs(p.clips[right.id].start - 2.0) < 1e-3
        ctrl.undo_stack.undo()
        print("✓ Cambiar duración (lo de detrás se mueve)")
        # Pegar e insertar
        L = p.clips[left.id]
        tl.set_selection([L.id])
        win._copy(False)
        n_before = len(p.clips)
        win.engine.seek(L.end)
        win._paste_insert()
        assert len(p.clips) > n_before and abs(p.clips[right.id].start - (L.end + L.duration)) < 1e-3,             (p.clips[right.id].start, L.end, L.duration)
        ctrl.undo_stack.undo()
        print("✓ Pegar e insertar")
        # Eliminar atributos
        ctrl.set_clip_props([left.id], "fx", fx={"glitch": 0.5}, volume=0.3)
        ctrl.remove_attributes([left.id], ["efectos", "audio"])
        assert not p.clips[left.id].fx and p.clips[left.id].volume == 1.0
        print("✓ Eliminar atributos")
        # Activar/desactivar y color de clip
        tl.set_selection([left.id])
        win._toggle_enabled()
        assert not p.clips[left.id].enabled
        win._toggle_enabled()
        win._set_label([left.id], "#3f6fb5")
        assert p.clips[left.id].label == "#3f6fb5"
        print("✓ Activar/desactivar (D) y Color de clip")
        # Normalizar volumen (pico −1 dBFS): el tono a −12 dB sube ~11 dB
        aud = next(i for i in ctrl.linked_ids([left.id]) if p.track(p.clips[i].track_id).kind == TRACK_AUDIO)
        ctrl.normalize_volume([aud], "peak", -1.0)
        v = p.clips[aud].volume
        assert 2.5 < v <= 4.0, v
        print(f"✓ Normalizar volumen (pico a −1 dBFS): volumen ×{v:.2f}")
        # Eliminar solo el audio
        tl.set_selection([left.id])
        win._delete_part("audio")
        assert left.id in p.clips and aud not in p.clips
        ctrl.undo_stack.undo()
        win._delete_part("video")
        assert left.id not in p.clips and aud in p.clips
        ctrl.undo_stack.undo()
        print("✓ Eliminar solo el audio / solo el video")

        # Recortar a lo largo: se come el de al lado; imán pegajoso
        r_start = p.clips[right.id].start
        ctrl.trim_clip(left.id, "right", r_start + 1.5, linked=False, overwrite=True)
        assert abs(p.clips[left.id].end - (r_start + 1.5)) < 1e-3
        assert abs(p.clips[right.id].start - (r_start + 1.5)) < 1e-3, "el de al lado se recorta"
        ctrl.undo_stack.undo()
        tl.snapping = True
        e = tl._sticky_edge(p.clips[left.id], r_start + 3 / tl.pps)
        assert e is not None and abs(e - r_start) < 1e-3
        print("✓ alargar se come lo de al lado · con el imán se queda pegado donde choca")

        # Archivo que falta → se reconecta al volver a añadirlo
        moved = os.path.join(out, "otra_carpeta")
        os.makedirs(moved, exist_ok=True)
        ctrl.missing.add(mid)
        p.media[mid].path = os.path.join(out, "no_existe", "con_sonido.mp4")
        ctrl.import_paths([vid])
        assert mid not in ctrl.missing and os.path.normcase(p.media[mid].path) == os.path.normcase(os.path.abspath(vid))
        shutil.copy(vid, os.path.join(moved, "con_sonido.mp4"))
        ctrl.missing.add(mid)
        p.media[mid].path = os.path.join(out, "no_existe", "con_sonido.mp4")
        new = ctrl.import_paths([os.path.join(moved, "con_sonido.mp4")])
        assert not new and mid not in ctrl.missing and "otra_carpeta" in p.media[mid].path, (new, p.media[mid].path)
        print("✓ un archivo que faltaba se reconecta al volver a añadirlo (aunque esté en otra carpeta)")

        # 👍 → clip compuesto; Mix → al principio del tramo
        ids_now = [c.id for c in p.clips_on(v1.id)]
        p.edits.append({"id": "e1", "base": 0.0, "duration": max(p.clips[i].end for i in ids_now),
                        "clip_ids": ids_now, "text_ids": [], "style": "phonk", "sources": [mid]})
        win.edit_bar._cook(p.edits[-1])
        t0 = time.time()
        while time.time() - t0 < 90 and not win.edit_bar._compounds_in(p.edits[-1]):
            pump(app, 0.2)
        assert win.edit_bar._compounds_in(p.edits[-1]), "👍 lo cocina en un clip compuesto"
        assert win.edit_bar._uncook(p.edits[-1]) and not win.edit_bar._compounds_in(p.edits[-1])
        print("✓ 👍 cocina el edit en un ⧉ clip compuesto (y se separa solo para Remix/Mix)")
        win.engine.seek(0.0)
        win.edit_bar.go_to(5.0)
        pump(app, 0.1)
        assert abs(win.engine.time - 5.0) < 1e-3 and tl.scroll <= 5.0 <= tl.t_for(tl.width())
        print("✓ 🎛 Mix: el cabezal va al principio del tramo y la línea de tiempo lo enseña")
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 30:
            pump(app, 0.2)
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
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
