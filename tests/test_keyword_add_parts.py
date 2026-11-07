"""
Prueba de «🔑 Palabras clave»: «Añadir en todas las palabra» (Por partes / Entero / un trozo) y enlazar ARCHIVOS.
Sin ventanas (offscreen), sin Papelera real y sin preguntas bloqueantes (se parchean).
  · «en todas» + «Por partes» → un trozo distinto y consecutivo del video en cada marca (source_in crecientes,
    sin tramos repetidos), duración 2–6 s, en UNA pista de video (encima de la principal), sin sonido, sin
    clips de audio nuevos y un solo Ctrl+Z;
  · «Entero» → cada clip acaba como mucho en la siguiente marca (sin solaparse), en una sola pista;
  · «aquí» + «Un trozo» → 1 clip de 2–6 s; «Cancelar» no pone nada; una imagen dura la frase (no infinita);
  · soltar un medio de la BIBLIOTECA (mime interno) sobre «GTA 6» lo ENLAZA: sale con 🔗, no se copia;
    «Desvincular este archivo» y «Quitar palabra clave» no borran el archivo;
  · soltar un archivo suelto del Explorador: enlazar (según la elección) y no copiar;
  · soltar sobre la cabecera «🔑 Palabras clave» pide el nombre.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_keyword_add_parts.py _pruebas_tmp/test_keyword_add_parts
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core import media as MEDIA  # noqa: E402
from editoria.core.model import (KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip,  # noqa: E402
                                 MediaItem, Project)
from editoria.ui import clips_panel as CP  # noqa: E402
from editoria.ui import common as COM  # noqa: E402
from editoria.ui import library as LIB  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
BASE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_keyword_add_parts")
RAIZ = os.path.join(BASE, "Reclaimer - Clips por palabra")
PC = os.path.join(BASE, "Mi PC")
DUR_VIDEO = 60.0
DUR_NAR = 80.0
MARCAS = [10.0, 25.0, 45.0]
EPS = 1e-3

app = None


def _ok(msg: str):
    print("✓", msg)


def _video_prueba() -> str:
    ruta = os.path.join(PC, "video_largo.mp4")
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=25:duration={DUR_VIDEO}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={DUR_VIDEO}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", ruta], check=True, timeout=300, creationflags=0x08000000)
    return ruta


def _imagen_prueba() -> str:
    ruta = os.path.join(PC, "foto.png")
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor(200, 120, 40))
    assert img.save(ruta, "PNG"), "no pude crear la imagen de prueba"
    return ruta


def _proyecto(video: str, imagen: str) -> Project:
    """Una narración (con su transcripción) en A1 y un video de 60 s y una imagen sin usar, en Medios."""
    p = Project.new()
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=DUR_NAR, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    a1 = p.tracks[-1]
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=DUR_NAR)
    p.media["vid"] = MediaItem(id="vid", path=video, kind=KIND_VIDEO, name="video_largo.mp4",
                               duration=DUR_VIDEO, probed=True, width=320, height=180)
    p.media["img"] = MediaItem(id="img", path=imagen, kind=KIND_IMAGE, name="foto.png", duration=0.0,
                               probed=True, width=320, height=180)
    return p


def _mid_de(ctrl, ruta: str) -> str:
    norm = os.path.normcase(os.path.abspath(ruta))
    return next(m.id for m in ctrl.project.media.values() if os.path.normcase(os.path.abspath(m.path)) == norm)


def _nuevos(ctrl, antes: set) -> list:
    return sorted((c for cid, c in ctrl.project.clips.items() if cid not in antes), key=lambda c: c.start)


def _nodo(lib, term: str):
    for i in range(lib.tree.topLevelItemCount()):
        sec = lib.tree.topLevelItem(i)
        if sec.data(0, LIB.ROLE_CATEGORY) != LIB.KW_SECTION:
            continue
        for j in range(sec.childCount()):
            n = sec.child(j)
            if n.data(0, LIB.ROLE_KW_KIND) == "term" and n.data(0, LIB.ROLE_KW_TERM) == term:
                return n
    return None


def _archivos(nodo) -> list:
    return [nodo.child(k) for k in range(nodo.childCount()) if nodo.child(k).data(0, LIB.ROLE_KW_KIND) == "file"]


def _accion(lib, item, inicio: str):
    capturado = {}
    original = LIB.help_ui.exec_menu
    LIB.help_ui.exec_menu = lambda m, pos: capturado.setdefault("menu", m)
    try:
        lib._kw_menu(item, QPoint(5, 5))
    finally:
        LIB.help_ui.exec_menu = original
    menu: QMenu = capturado["menu"]
    return next(a for a in menu.actions() if a.text().startswith(inicio))


def _comprobar_pista_unica(ctrl, clips_nuevos: list, antes_audio: int):
    """Todos en UNA pista de video, encima de la principal; ninguno con sonido; ningún clip de audio nuevo."""
    pistas = {c.track_id for c in clips_nuevos}
    assert len(pistas) == 1, f"deben ir en UNA pista, van en {len(pistas)}"
    tr = ctrl.project.track(next(iter(pistas)))
    assert tr.kind == TRACK_VIDEO, tr.kind
    principal = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    assert ctrl.project.track_index(tr.id) < ctrl.project.track_index(principal.id), "debe ir encima de la principal"
    assert all(c.volume == 0.0 for c in clips_nuevos), [c.volume for c in clips_nuevos]
    audio_ahora = sum(1 for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_AUDIO)
    assert audio_ahora == antes_audio, "no debe crear clips de audio nuevos"


def _sin_solapes(clips_nuevos: list):
    for a, b in zip(clips_nuevos, clips_nuevos[1:]):
        assert a.end <= b.start + EPS, f"se solapan: {a.start:.2f}-{a.end:.2f} con {b.start:.2f}"


# ------------------------------------------------------------------------ pruebas de «Añadir en todas»
def prueba_partes(win, preguntas: list):
    ctrl = win.ctrl
    antes = set(ctrl.project.clips)
    antes_audio = sum(1 for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_AUDIO)
    pila = ctrl.undo_stack.index()
    win._pregunta_modo_palabra = lambda una: (preguntas.append(una) or "partes")
    win._add_at_times(["vid"], list(MARCAS), "Añadir en todas las «GTA 6» (3)")
    assert preguntas == [False], f"debe preguntar (3 marcas): {preguntas}"
    assert ctrl.undo_stack.index() == pila + 1, "debe ser UN solo paso de deshacer"
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 3, [(c.start, c.duration) for c in nuevos]
    _comprobar_pista_unica(ctrl, nuevos, antes_audio)
    _sin_solapes(nuevos)
    for c in nuevos:
        assert 2.0 - EPS <= c.duration <= 6.0 + EPS, c.duration
    assert abs(nuevos[0].source_in - 3.0) < EPS, "el 1.º trozo empieza tras los logos (3 s)"
    for a, b in zip(nuevos, nuevos[1:]):
        assert abs(b.source_in - (a.source_in + a.duration)) < EPS, \
            f"cada trozo continúa donde acabó el anterior: {a.source_in + a.duration} vs {b.source_in}"
    assert [round(c.start, 2) for c in nuevos] == [round(t, 2) for t in MARCAS], [c.start for c in nuevos]
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes, "el Ctrl+Z los quita todos de una vez"
    _ok("«en todas» + Por partes: 3 trozos seguidos del video (sin repetir), 2–6 s, sin sonido, en UNA pista "
        f"encima de la principal; un solo Ctrl+Z ({[round(c.duration, 2) for c in nuevos]} s)")


def prueba_entero(win):
    ctrl = win.ctrl
    antes = set(ctrl.project.clips)
    antes_audio = sum(1 for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_AUDIO)
    fin = ctrl.project.duration()
    win._pregunta_modo_palabra = lambda una: "entero"
    win._add_at_times(["vid"], list(MARCAS), "Añadir en todas las «GTA 6» (3)")
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 3, [(c.start, c.duration) for c in nuevos]
    _comprobar_pista_unica(ctrl, nuevos, antes_audio)
    _sin_solapes(nuevos)
    for c in nuevos:
        assert abs(c.source_in - 3.0) < EPS, "entero: desde el principio del video (tras logos)"
    for i, c in enumerate(nuevos[:-1]):
        assert abs(c.end - nuevos[i + 1].start) < EPS, f"cada uno acaba en la siguiente marca: {c.end}"
    ultimo = nuevos[-1]
    assert abs(ultimo.end - min(fin, ultimo.start + DUR_VIDEO - 3.0)) < EPS, (ultimo.end, fin)
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes
    _ok("«en todas» + Entero: cada clip acaba en la siguiente marca (último: hasta el final de la línea "
        "de tiempo); sin solaparse, en una pista; un Ctrl+Z")


def prueba_aqui(win, preguntas: list):
    ctrl = win.ctrl
    preguntas.clear()
    antes = set(ctrl.project.clips)
    pila = ctrl.undo_stack.index()
    win._pregunta_modo_palabra = lambda una: (preguntas.append(una) or None)
    win._add_at_times(["vid"], [30.0], "Añadir en «GTA 6»")
    assert preguntas == [True], "una sola marca: la pregunta es la de «Un trozo / Entero»"
    assert set(ctrl.project.clips) == antes and ctrl.undo_stack.index() == pila, "Cancelar no pone nada"
    win._pregunta_modo_palabra = lambda una: "partes"
    win._add_at_times(["vid"], [30.0], "Añadir en «GTA 6»")
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 1, len(nuevos)
    assert 2.0 - EPS <= nuevos[0].duration <= 6.0 + EPS, nuevos[0].duration
    assert abs(nuevos[0].start - 30.0) < EPS
    ctrl.undo_stack.undo()
    _ok(f"«aquí» + Un trozo: 1 clip de {nuevos[0].duration:.2f} s; Cancelar no pone nada")


def prueba_imagen(win):
    ctrl = win.ctrl
    antes = set(ctrl.project.clips)
    win._pregunta_modo_palabra = lambda una: (_ for _ in ()).throw(AssertionError("una imagen no pregunta"))
    win._add_at_times(["img"], [50.0], "Añadir en «GTA 6»")
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 1 and 2.0 - EPS <= nuevos[0].duration <= 6.0 + EPS, \
        [c.duration for c in nuevos]
    ctrl.undo_stack.undo()
    _ok(f"imagen en una marca: dura la frase ({nuevos[0].duration:.2f} s), no la duración infinita")


# ------------------------------------------------------------------------ pruebas de enlazar archivos
class _Evento:
    """Un QDropEvent mínimo para llamar a MediaTree.dropEvent sin ventana."""

    def __init__(self, origen, mime, pos):
        self._origen, self._mime, self._pos = origen, mime, pos
        self.aceptado = None

    def position(self):
        return QPointF(self._pos)

    def source(self):
        return self._origen

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.aceptado = True

    def ignore(self):
        self.aceptado = False


def prueba_soltar_medio(win, video: str):
    lib = win.library
    ctrl = win.ctrl
    lib._kw_create("GTA 6")
    nodo = _nodo(lib, "GTA 6")
    assert nodo is not None
    mime = QMimeData()
    mime.setData(LIB.MEDIA_MIME, QByteArray(b"vid"))
    centro = lib.tree.visualItemRect(nodo).center()
    if centro.x() == 0 and centro.y() == 0:
        raise AssertionError("el árbol no ha calculado la posición de «GTA 6»")
    ev = _Evento(lib.tree, mime, centro)
    lib.tree.dropEvent(ev)
    assert ev.aceptado, "soltar un medio sobre la palabra debe aceptarse"
    enlazados = KF.linked_files(RAIZ, "GTA 6")
    assert [os.path.normcase(p) for p in enlazados] == [os.path.normcase(os.path.abspath(video))], enlazados
    assert not os.path.exists(os.path.join(RAIZ, "GTA 6", "video_largo.mp4")), "el archivo NO se copia"
    nodo = _nodo(lib, "GTA 6")
    arch = _archivos(nodo)
    assert len(arch) == 1 and arch[0].text(0).startswith("🔗 "), [a.text(0) for a in arch]
    assert nodo.text(0).startswith("GTA 6  (1)"), nodo.text(0)
    _ok("soltar un medio de la biblioteca sobre «GTA 6» lo ENLAZA: sale con 🔗, no se copia (carpeta propia vacía)")

    # «Desvincular este archivo» no borra nada
    _accion(lib, arch[0], "Desvincular este archivo").trigger()
    assert KF.linked_files(RAIZ, "GTA 6") == [] and os.path.isfile(video), "desvincular no borra el archivo"
    lib._kw_link_files("GTA 6", [video])
    assert KF.linked_files(RAIZ, "GTA 6"), "vuelve a enlazarse"

    # 🎬 Quitar palabra: solo desvincula el archivo enlazado (nunca lo borra) y manda a la Papelera solo la propia
    enviados: list = []
    papelera_dir = os.path.join(BASE, "_papelera_falsa")

    def papelera_falsa(ruta: str) -> bool:
        enviados.append(os.path.normcase(os.path.abspath(ruta)))
        os.makedirs(papelera_dir, exist_ok=True)
        shutil.move(ruta, os.path.join(papelera_dir, os.path.basename(ruta)))
        return True

    class _Caja:
        Yes, No = 0x4000, 0x10000

        @staticmethod
        def question(*_a, **_k):
            return _Caja.Yes

        @staticmethod
        def warning(*_a, **_k):
            return None

        @staticmethod
        def information(*_a, **_k):
            return None

    orig_trash, orig_caja = LIB._to_trash, LIB.QMessageBox
    LIB._to_trash = papelera_falsa
    LIB.QMessageBox = _Caja
    try:
        _accion(lib, _nodo(lib, "GTA 6"), "🗑 Quitar palabra clave").trigger()
    finally:
        LIB._to_trash, LIB.QMessageBox = orig_trash, orig_caja
    assert enviados == [os.path.normcase(os.path.abspath(os.path.join(RAIZ, "GTA 6")))], enviados
    assert os.path.isfile(video), "quitar la palabra NO borra el archivo enlazado"
    assert KF.linked_files(RAIZ, "GTA 6") == [], "el enlace se quita"
    assert _nodo(lib, "GTA 6") is None
    _ok("«Desvincular este archivo» y «Quitar palabra clave» no borran el archivo enlazado")


def prueba_soltar_archivo_explorador(win, suelto: str):
    lib = win.library
    original = LIB.modo_archivo_suelto
    LIB.modo_archivo_suelto = lambda parent: "enlazar"
    try:
        lib._kw_drop([suelto], "Minecraft")
    finally:
        LIB.modo_archivo_suelto = original
    assert [os.path.normcase(p) for p in KF.linked_files(RAIZ, "Minecraft")] == \
        [os.path.normcase(os.path.abspath(suelto))]
    assert not os.path.exists(os.path.join(RAIZ, "Minecraft", os.path.basename(suelto))), "no se copia"
    _ok("archivo suelto del Explorador, elegido «Enlazar»: se enlaza y no se copia")


def prueba_cabecera(win, video: str):
    lib = win.library
    original = LIB.QInputDialog

    class _Pregunta:
        @staticmethod
        def getText(*_a, **_k):
            return "Roblox", True

    LIB.QInputDialog = _Pregunta
    try:
        lib.tree.kw_header_dropped.emit([ "vid"], True)
    finally:
        LIB.QInputDialog = original
    assert [os.path.normcase(p) for p in KF.linked_files(RAIZ, "Roblox")] == \
        [os.path.normcase(os.path.abspath(video))], "soltar en la cabecera pide el nombre y enlaza"
    _ok("soltar un medio sobre la cabecera «🔑 Palabras clave» pide el nombre y lo enlaza")


def main():
    global app
    app = QApplication.instance() or QApplication(sys.argv)
    ajustes = QSettings("EditorIA", "EditorIA")
    CP.ClipsPanel._buscar = lambda self, *_a, **_k: None        # sin red
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(PC, exist_ok=True)
    os.makedirs(RAIZ, exist_ok=True)
    ajustes.setValue(CP.RAIZ_CLAVE, RAIZ)                       # la raíz de la prueba, antes de abrir la ventana
    ajustes.remove("palabras_clave/soltar_archivo")
    win = None
    try:
        video = _video_prueba()
        imagen = _imagen_prueba()
        suelto = os.path.join(PC, "foto_suelta.png")
        shutil.copy(imagen, suelto)
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.ctrl.project = _proyecto(video, imagen)
        win.library._rebuild()
        win.timeline.set_hint_marks([(t, "GTA 6") for t in MARCAS])
        assert CP._raiz_guardada() == RAIZ
        preguntas: list = []

        prueba_partes(win, preguntas)
        prueba_entero(win)
        prueba_aqui(win, preguntas)
        prueba_imagen(win)
        prueba_soltar_medio(win, video)
        prueba_soltar_archivo_explorador(win, suelto)
        prueba_cabecera(win, video)
    finally:
        ajustes.remove(CP.RAIZ_CLAVE)
        ajustes.remove("palabras_clave/soltar_archivo")
        if win is not None:
            win.ctrl._media_dirty = False
            win.ctrl.undo_stack.setClean()
            win.close()
            app.processEvents()
    print("TODO OK")


if __name__ == "__main__":
    main()
