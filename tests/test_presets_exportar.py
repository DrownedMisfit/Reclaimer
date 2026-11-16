"""
★ Tus presets de exportación (como Shotcut), sin ventanas visibles: guardar con nombre, aparecen en «Preset» con ★,
elegirlos pone todos sus ajustes (resolución, FPS, códec, codificador, calidad, subtítulos…), y se pueden borrar.
Ejecutar:  .venv/Scripts/python.exe tests/test_presets_exportar.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_presets_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    from editoria.ui.main_window import MainWindow
    from editoria.ui.export_dialog import ExportDialog
    win = MainWindow()
    d = ExportDialog(win.ctrl, win)
    d._apply_target("custom")
    d.width_box.setValue(2560)
    d.height_box.setValue(1440)
    d.fps.setCurrentText("60")
    d.codec.setCurrentIndex(d.codec.findData("hevc"))
    d.encoder.setCurrentIndex(d.encoder.findData("cpu"))
    d.bitrate.setValue(37)
    d.subs.setChecked(True)
    assert d.save_preset("Mis reseñas 1440p")
    items = [d.preset.itemText(i) for i in range(d.preset.count())]
    assert "★ Mis reseñas 1440p" in items and d.preset.currentText() == "★ Mis reseñas 1440p", items
    print("✓ guardar un preset con nombre: sale en «Preset» con ★")
    d.preset.setCurrentText("YouTube 1080p")
    d.codec.setCurrentIndex(d.codec.findData("h264"))
    d.subs.setChecked(False)
    d2 = ExportDialog(win.ctrl, win)               # (se recuerda al volver a abrir)
    d2._apply_target("custom")
    d2.preset.setCurrentText("★ Mis reseñas 1440p")
    assert (d2.width_box.value(), d2.height_box.value(), d2.fps.currentText(), d2.codec.currentData(),
            d2.encoder.currentData(), d2.bitrate.value()) == \
        (2560, 1440, "60", "hevc", "cpu", 37), "elegirlo pone todos sus ajustes"
    assert "subs" not in d2._user_presets()["Mis reseñas 1440p"] or d.subs.isEnabled(), \
        "sin subtítulos en el proyecto, el preset no guarda «apagados»"
    print("✓ elegirlo (también al volver a abrir Exportar) pone resolución, FPS, códec, codificador y calidad")
    assert d2.btn_del_preset.isEnabled() and d2.delete_preset()
    assert "★ Mis reseñas 1440p" not in [d2.preset.itemText(i) for i in range(d2.preset.count())]
    print("✓ 🗑 lo borra")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
