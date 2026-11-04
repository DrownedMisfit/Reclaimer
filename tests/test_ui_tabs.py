"""
Prueba de la interfaz limpia (como Resolve: todo en pestañas, sin explicaciones largas a la vista):
  · Efectos, Limpieza, Subtítulos e IA ✨ tienen sus subpestañas; las tarjetas de la IA abren su pestaña;
  · ⚡ Subtítulos para Short: con la narración ya transcrita, un clic los activa con el estilo «Mis Shorts»;
    sin transcribir, pide la transcripción y al terminar los pone solos.
Ejecutar:  .venv/Scripts/python.exe tests/test_ui_tabs.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import shutil
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


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
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        names = lambda tw: [tw.tabText(i) for i in range(tw.count())]   # noqa: E731
        assert names(win.effects.tabs) == ["Imagen", "Transiciones", "Sonidos", "⭐ Para la IA"]
        assert names(win.voice.tabs) == ["Transcribir", "Limpiar", "Sugerencias"]
        assert names(win.subtitles.tabs) == ["Letra", "Colores", "Posición", "Animación"]
        assert names(win.ai_panel.tabs)[0] == "Inicio" and "B-roll" in names(win.ai_panel.tabs)
        win.ai_panel._card("broll")
        assert win.ai_panel.tabs.tabText(win.ai_panel.tabs.currentIndex()) == "B-roll"
        print("✓ Efectos, Limpieza, Subtítulos e IA ✨ en subpestañas; las tarjetas de la IA abren la suya")

        ctrl = win.ctrl
        wav = os.path.join(out, "narracion.wav")
        shutil.copy(os.path.join(ASSETS, "narracion_prueba.wav"), wav)
        (mid,) = ctrl.import_now([wav])
        while ctrl.analyzing:
            pump(app, 0.1)
        win.voice._refresh_media()
        i = win.voice.media_combo.findData(mid)
        win.voice.media_combo.setCurrentIndex(i)
        asked = []
        win.subtitles.transcribe_requested.disconnect()
        win.subtitles.transcribe_requested.connect(lambda: asked.append(True))
        win.subtitles.quick_short()
        assert asked and win.subtitles._pending == mid
        tr = json.load(open(os.path.join(ASSETS, "narracion_prueba.transcripcion.json"), encoding="utf-8"))
        ctrl.set_transcript(mid, tr)            # como si la transcripción acabara de terminar
        pump(app, 0.2)
        s = ctrl.project.subtitles
        from editoria.core.subtitles import SHORTS
        assert s.enabled and s.media_id == mid and s.preset == SHORTS, (s.enabled, s.media_id, s.preset)
        print(f"✓ ⚡ Subtítulos para Short: transcribe si hace falta y los pone con el estilo «{SHORTS}»")
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
