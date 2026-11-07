"""
Prueba de la DESCRIPCIÓN para YouTube (📝 Descripción para YouTube). Sin ventanas (offscreen), sin red:
  · la descripción contiene capítulos con 0:00, créditos de un clip bajado, el pie guardado, el párrafo y hashtags;
  · las secciones se quitan con su casilla y los hashtags se activan uno a uno;
  · renombrar un capítulo lo cambia en su marcador; el párrafo se recuerda por proyecto;
  · guardar .txt escribe la misma descripción;
  · al terminar una exportación (ExportDialog._finished con código 0) aparece «<video>.descripcion.txt».
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_description.py _pruebas_tmp/test_description
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from editoria.core import description as DS  # noqa: E402
from editoria.core.model import Clip, Marker, MediaItem, Project  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions  # noqa: E402
from editoria.ui.description_dialog import DescriptionDialog  # noqa: E402

TEXTO = ("Hoy hablamos de Fortnite y de Epic Games. Bueno, pues estaba looteando en Fortnite "
         "mientras disparaba a los rivales.")


class _Ctrl:
    """Lo mínimo que usan los diálogos: proyecto, ruta y cambiar un marcador."""

    def __init__(self, p, path=None):
        self.project, self.path = p, path
        self.missing, self.peaks, self.clip_vecs = set(), {}, {}

    def update_marker(self, mid, **props):
        for m in self.project.markers:
            if m.id == mid:
                for k, v in props.items():
                    setattr(m, k, v)


class _Win(QWidget):
    """Hace de ventana principal: es un QWidget (padre de los diálogos) con ctrl y la carpeta de exportación."""

    def __init__(self, ctrl, carpeta):
        super().__init__()
        self.ctrl, self._carpeta = ctrl, carpeta

    def default_export_path(self):
        return os.path.join(self._carpeta, "sin_nombre.mp4")


def _proyecto(carpeta: str) -> Project:
    p = Project.new()
    p.name = "Prueba descripción"
    video = os.path.join(carpeta, "clip_bajado.mp4")
    open(video, "wb").close()
    with open(os.path.splitext(video)[0] + ".creditos.json", "w", encoding="utf-8") as f:
        json.dump({"title": "Tráiler de prueba", "channel": "Canal Oficial",
                   "url": "https://www.youtube.com/watch?v=abc", "term": "Fortnite"}, f, ensure_ascii=False)
    p.media["v1"] = MediaItem(id="v1", path=video, kind="video", name="clip_bajado.mp4", duration=300.0)
    pista_v = next(t for t in p.tracks if t.kind == "video")
    p.clips["c1"] = Clip("c1", "v1", pista_v.id, 0.0, 0.0, 300.0)
    p.markers = [Marker("m1", 3.0, "Intro del juego"), Marker("m2", 70.0, "Jugabilidad"),
                 Marker("m3", 150.0, "Combate contra el jefe"), Marker("m4", 240.0, "Final"),
                 Marker("t1", 0.0, "COMBATE", kind="topic", end=60.0)]
    palabras = TEXTO.split()
    p.transcripts = {"n1": {"language": "es", "words": [[i * 0.5, i * 0.5 + 0.4, t, 0.9]
                                                       for i, t in enumerate(palabras)]}}
    return p


def prueba_contenido(carpeta: str):
    p = _proyecto(carpeta)
    ctrl = _Ctrl(p, path=None)
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("descripcion/pie", "☕ Apóyame en ko-fi.com/prueba")
    dlg = DescriptionDialog(_Win(ctrl, carpeta))
    dlg.par.setPlainText("Párrafo de prueba para el video.")     # se guarda por proyecto al cambiar
    txt = dlg.texto()
    assert re.search(r"^0:00 ", txt, re.M), txt
    assert "🎬 Clips usados en este video:" in txt and "Tráiler de prueba" in txt, txt
    assert "☕ Apóyame en ko-fi.com/prueba" in txt, txt
    assert "#Fortnite" in txt and "#Combate" in txt, txt
    orden = [txt.index(x) for x in ("Párrafo de prueba", "0:00 ", "🎬 Clips", "☕ Apóyame", "#Fortnite")]
    assert orden == sorted(orden), "el orden de las partes no es el de la descripción"
    print("✓ Descripción con párrafo, capítulos (0:00), créditos, pie y hashtags, en ese orden")

    # Secciones y hashtags se pueden quitar
    dlg.sec_cred.setChecked(False)
    assert "Clips usados" not in dlg.texto()
    dlg.sec_cred.setChecked(True)
    n_tags = len(dlg._tag_cbs)
    cb = next(c for c in dlg._tag_cbs if c.text() == "#Fortnite")
    cb.setChecked(False)
    assert "#Fortnite" not in dlg.texto()
    cb.setChecked(True)
    print(f"✓ Casillas: quitar créditos o un hashtag lo saca; {n_tags} hashtags sugeridos")

    # Renombrar un capítulo lo cambia en su marcador
    fila = next(i for i in range(dlg.chapters.table.rowCount())
                if dlg.chapters.table.item(i, 1).text() == "Intro del juego")
    dlg.chapters.table.item(fila, 1).setText("Introducción")
    assert next(m for m in p.markers if m.id == "m1").label == "Introducción"
    assert "0:00 Introducción" in dlg.texto(), dlg.texto()
    print("✓ Renombrar un capítulo lo cambia en su marcador")

    # Guardar .txt escribe lo mismo que la vista previa
    ruta = os.path.join(carpeta, "descripcion_prueba.txt")
    dlg.guardar_en(ruta)
    with open(ruta, encoding="utf-8") as f:
        assert f.read() == dlg.texto() + "\n"
    print("✓ Guardar .txt: mismo texto que la vista previa")

    # El párrafo se recuerda por proyecto y el pie para todos
    dlg2 = DescriptionDialog(_Win(ctrl, carpeta))
    assert dlg2.par.toPlainText() == "Párrafo de prueba para el video.", dlg2.par.toPlainText()
    assert dlg2.pie.toPlainText() == "☕ Apóyame en ko-fi.com/prueba"
    otro = DescriptionDialog(_Win(_Ctrl(Project.new(), path=None), carpeta))
    assert otro.par.toPlainText() == "", "el párrafo de un proyecto no debe salir en otro"
    print("✓ El párrafo se recuerda por proyecto y el pie para todos los videos")
    return dlg, ctrl


def prueba_exportacion(carpeta: str, ctrl: _Ctrl):
    from editoria.ui.export_dialog import ExportDialog
    dlg = ExportDialog(ctrl)
    video = os.path.join(carpeta, "Video final.mp4")
    dlg._opts = ExportOptions(path=video, width=1920, height=1080, fps=30.0, codec="h264", encoder="cpu",
                              bitrate_mbps=10)
    dlg._t0 = time.time()
    dlg._finished(0, None)                                   # como si ffmpeg hubiera terminado bien
    ruta = os.path.join(carpeta, "Video final.descripcion.txt")
    assert os.path.isfile(ruta), "no se creó <video>.descripcion.txt"
    with open(ruta, encoding="utf-8") as f:
        texto = f.read()
    assert "☕ Apóyame en ko-fi.com/prueba" in texto and "🎬 Clips usados" in texto, texto
    assert not os.path.exists(os.path.join(carpeta, "Video final.creditos.txt")), "sobra el .creditos.txt suelto"
    print("✓ Al exportar: <video>.descripcion.txt con pie y créditos (sin .creditos.txt suelto)")
    dlg.close()


def main():
    carpeta = sys.argv[1]
    os.makedirs(carpeta, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    app = QApplication(sys.argv)
    try:
        dlg, ctrl = prueba_contenido(carpeta)
        prueba_exportacion(carpeta, ctrl)
        dlg.close()
    finally:
        st.remove("descripcion")
    print("TODO OK")


if __name__ == "__main__":
    main()
