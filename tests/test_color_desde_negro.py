"""
🎨 Elegir color partiendo de negro: el diálogo se abre con el brillo arriba (si no, el cuadro de colores seguía dando
negro: «quiero cambiar el color y no se cambia»); si aceptas sin tocar, se queda el negro.
Ejecutar:  .venv/Scripts/python.exe tests/test_color_desde_negro.py
"""
from __future__ import annotations

import os
import sys

# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog  # noqa: E402


def main():
    QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.common import pick_color
    vistos, devolver = [], []
    QColorDialog.getColor = staticmethod(lambda ini, *a, **k: (vistos.append(QColor(ini)), devolver.pop(0))[1])
    devolver.append(QColor.fromHsv(0, 0, 255))                # aceptar sin tocar
    c = pick_color("#000000", None, "Color", alpha=True)
    assert vistos[-1].value() == 255, vistos[-1].name()
    assert c.name() == "#000000", c.name()
    devolver.append(QColor("#ff2020"))                        # elegir rojo en el cuadro
    assert pick_color("#000000").name() == "#ff2020"
    devolver.append(QColor("#123456"))                        # desde un color normal: se abre con ese color
    pick_color("#3080ff")
    assert vistos[-1].name() == "#3080ff", vistos[-1].name()
    print("✓ desde negro se abre con brillo; aceptar sin tocar deja el negro; elegir otro color funciona")
    print("TODO OK")


if __name__ == "__main__":
    main()
