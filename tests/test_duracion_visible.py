"""
⏱ La duración total se ve siempre junto al tiempo (visor, también estrecho, y línea de tiempo); 💬 Subtítulos junto a Transcribir.
Ejecutar:  .venv/Scripts/python.exe tests/test_duracion_visible.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

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
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    for _ in range(20):
        app.processEvents()
    pv = win.preview
    for ancho, compacta in ((3000, False), (420, True)):
        pv._ajustar_cabecera(ancho)
        pv._compacta = compacta                    # (la cabecera real se recalcula sola con su ancho de verdad)
        pv.set_time(7.5, 89.8)
        assert pv.total_label.isVisibleTo(pv.header), "la duración total se escondió"
        assert "01:29" in pv.total_label.text(), pv.total_label.text()
        assert pv.total_label.text().startswith("/ 00:") != compacta, pv.total_label.text()
        fm = pv.time_label.fontMetrics()
        assert pv.time_label.width() >= fm.horizontalAdvance(pv.time_label.text()), "el tiempo se corta"
        assert pv.total_label.width() >= pv.total_label.fontMetrics().horizontalAdvance(pv.total_label.text())
        print(f"✓ cabecera {'estrecha' if compacta else 'ancha'}: {pv.time_label.text()} {pv.total_label.text()}")
    win.ctrl.project.duration = lambda: 89.8
    win._poner_total_tl()
    assert win.tl_total.text() == "/ 00:01:29:" + win.tl_total.text()[-2:], win.tl_total.text()
    # («/ total» solo se esconde como último recurso, si la barra no cabe ni compacta —sin pantalla mide ~800 px—, y
    #  entonces la duración sigue en el tooltip del reloj)
    if not win.tl_total.isVisibleTo(win):
        bar = win._tl_bar
        assert bar.width() < win._tl_ancho_minimo(), ("«/ total» escondido con sitio", bar.width(),
                                                      win._tl_ancho_minimo())
        assert "00:01:29:" in win.tl_timecode.toolTip(), win.tl_timecode.toolTip()
        print("  (barra estrecha: «/ total» en el tooltip del reloj)")
    print(f"✓ línea de tiempo: {win.tl_timecode.text()} {win.tl_total.text()}")
    # (los subtítulos viven en «Voz y texto» → 3 · Subtítulos —panel agrupado de la izquierda—: se oculta ese panel
    #  y el botón lo abre con su sección a la vista)
    win.docks["voz_texto"].hide()
    app.processEvents()
    assert not win.subtitles.isVisible()
    win.voice.btn_subtitulos.click()
    app.processEvents()
    assert win.docks["voz_texto"].isVisible() and win.subtitles.isVisible(), "«💬 Subtítulos» no abrió su panel"
    print("✓ «💬 Subtítulos» al lado de «Transcribir» abre el panel de subtítulos")
    # ⚡ el modelo de voz se carga al pasar el ratón por «Transcribir» o «⚡ Subtítulos» (no al abrir el panel)
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QEnterEvent, QGuiApplication
    from editoria.ai import transcription as TR
    pedidas = []
    TR.precargar, real = (lambda k: pedidas.append(k)), TR.precargar
    QGuiApplication.platformName, plat = staticmethod(lambda: "windows"), QGuiApplication.platformName
    try:
        win.voice.hide(); win.voice.show(); app.processEvents()
        assert not pedidas, "al mostrar el panel no se carga nada"
        for b in (win.voice.btn_transcribe, win.subtitles.btn_quick):
            b.setEnabled(True)
            win.voice.eventFilter(b, QEvent(QEvent.Enter))
        assert len(pedidas) == 2, pedidas
    finally:
        TR.precargar, QGuiApplication.platformName = real, plat
    print("✓ el modelo de voz se carga al pasar el ratón por «Transcribir» / «⚡ Subtítulos», no al abrir el panel")
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
