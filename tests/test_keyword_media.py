"""
Prueba de «🔑 Palabras clave» en Medios y de sus enlaces en 🎬 Clips (sin ventanas, sin Papelera real):
  · crear una palabra (su subcarpeta propia) → aparece en Medios con su nº de archivos;
  · 📂 Añadir carpeta de mi PC = ENLACE: sus archivos salen en la palabra (y en 🎬 Clips, con 🔗) sin copiarse;
    la carpeta original y la subcarpeta propia quedan igual; «Desvincular» no borra nada;
  · soltar una CARPETA sobre una palabra = enlace; soltar un ARCHIVO = copia a su subcarpeta propia;
  · «✨ Crear de lo que dices» crea las carpetas de las menciones que faltan (pregunta antes, sustituido);
  · seleccionar 2 archivos y «📍 Poner donde lo dices» los coloca en los momentos de la palabra (un solo Ctrl+Z);
  · «Quitar palabra clave» con la Papelera FALSA: solo se manda la subcarpeta propia; la carpeta enlazada
    sigue intacta en disco y el JSON ya no la tiene.
Las pruebas de Papelera y preguntas usan sustitutos: no se borra nada real.
Ejecutar:  .venv/Scripts/python.exe tests/test_keyword_media.py _pruebas_tmp/test_keyword_media
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

from PySide6.QtCore import QPoint, QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core import media as MEDIA  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import clips_panel as CP  # noqa: E402
from editoria.ui import library as LIB  # noqa: E402
from editoria.ui.clips_panel import ClipsPanel  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
BASE = os.path.join(_TMPROOT, "test_keyword_media")       # carpetas de la prueba (se rehacen)
RAIZ = os.path.join(BASE, "Reclaimer - Clips por palabra")  # la raíz de las palabras clave (en _pruebas_tmp)
PC = os.path.join(BASE, "Mi PC")                          # «tu ordenador» de la prueba (no es de Reclaimer)
DUR_VIDEO = 12.0

app = None
papelera_llamadas: list = []


def _ok(msg: str):
    print("✓", msg)


def _esperar(panel, segundos: float = 15.0):
    import time
    t0 = time.time()
    while time.time() - t0 < segundos and panel._job_carpeta is not None and panel._job_carpeta.isRunning():
        app.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)


def _video_prueba() -> str:
    ruta = os.path.join(_TMP, "gen.mp4")
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-t", str(DUR_VIDEO), "-pix_fmt", "yuv420p", ruta], check=True, timeout=180,
                   creationflags=0x08000000)
    return ruta


def _imagen_prueba(nombre: str = "imagen.png", color=(200, 120, 40)) -> str:
    ruta = os.path.join(_TMP, nombre)
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor(*color))
    assert img.save(ruta, "PNG"), "no pude crear la imagen de prueba"
    return ruta


def _preparar(video: str, imagen: str):
    """Raíz de palabras: «Fortnite» con su carpeta propia (video + imagen). «Mi PC»: carpetas y archivos sueltos."""
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(os.path.join(RAIZ, "Fortnite"))
    shutil.copy(video, os.path.join(RAIZ, "Fortnite", "gen.mp4"))
    shutil.copy(imagen, os.path.join(RAIZ, "Fortnite", "imagen.png"))
    fort_pc = os.path.join(PC, "Gameplay Fortnite")
    os.makedirs(fort_pc)
    shutil.copy(video, os.path.join(fort_pc, "clip_pc.mp4"))
    shutil.copy(imagen, os.path.join(fort_pc, "foto_pc.png"))
    with open(os.path.join(fort_pc, "nota.txt"), "w", encoding="utf-8") as f:
        f.write("no es material")
    soltada = os.path.join(PC, "Carpeta soltada")
    os.makedirs(soltada)
    shutil.copy(imagen, os.path.join(soltada, "suelta.png"))
    archivo_suelto = os.path.join(PC, "foto_suelta.png")
    shutil.copy(imagen, archivo_suelto)
    return fort_pc, soltada, archivo_suelto


def _listado(carpeta: str) -> list:
    out = []
    for dirpath, _d, names in os.walk(carpeta):
        for n in names:
            full = os.path.join(dirpath, n)
            st = os.stat(full)
            out.append((os.path.relpath(full, carpeta), st.st_size, st.st_mtime_ns))
    return sorted(out)


def _palabras() -> list:
    """Transcripción real de la narración (copia en memoria): «Fortnite» ×2, «Minecraft» ×1, «Roblox» ×1."""
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    for i in (12, 20):
        words[i][2] = "Fortnite"
    words[30][2] = "Minecraft"
    words[40][2] = "Roblox"
    return words


def _proyecto() -> Project:
    p = Project.new()
    words = _palabras()
    dur_nar = float(words[-1][1]) + 1.0
    v2, v1, a1 = p.tracks
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)
    return p


# ------------------------------------------------------------ ayudas para mirar el árbol de Medios
def _nodo(lib, term: str):
    """El nodo de la palabra dentro de «🔑 Palabras clave» (None si no está)."""
    for i in range(lib.tree.topLevelItemCount()):
        sec = lib.tree.topLevelItem(i)
        if sec.data(0, LIB.ROLE_CATEGORY) != LIB.KW_SECTION:
            continue
        for j in range(sec.childCount()):
            n = sec.child(j)
            if n.data(0, LIB.ROLE_KW_KIND) == "term" and n.data(0, LIB.ROLE_KW_TERM) == term:
                return n
    return None


def _hijos(nodo, kind: str) -> list:
    return [nodo.child(k) for k in range(nodo.childCount()) if nodo.child(k).data(0, LIB.ROLE_KW_KIND) == kind]


def _archivos(nodo) -> list:
    return _hijos(nodo, "file")


def _accion(lib, item, inicio: str):
    """Abre el menú de un nodo de palabra (sin ventana) y devuelve la acción cuyo texto empieza así."""
    capturado = {}
    original = LIB.help_ui.exec_menu
    LIB.help_ui.exec_menu = lambda m, pos: capturado.setdefault("menu", m)
    try:
        lib._kw_menu(item, QPoint(5, 5))
    finally:
        LIB.help_ui.exec_menu = original
    menu: QMenu = capturado["menu"]
    return next(a for a in menu.actions() if a.text().startswith(inicio))


def _mid_de(ctrl, ruta: str) -> str:
    norm = os.path.normcase(os.path.abspath(ruta))
    return next(m.id for m in ctrl.project.media.values() if os.path.normcase(os.path.abspath(m.path)) == norm)


def _nuevos(ctrl, antes: set) -> list:
    return [c for cid, c in ctrl.project.clips.items() if cid not in antes]


def _fila(panel, term: str) -> int:
    return next(i for i in range(panel.lista_menciones.count())
                if panel.lista_menciones.item(i).text().startswith(term + " ·"))


def _elegir(panel, term: str):
    panel.lista_menciones.setCurrentRow(-1)
    panel.lista_menciones.setCurrentRow(_fila(panel, term))
    _esperar(panel)


# ------------------------------------------------------------------------ pruebas
def prueba_crear(win):
    lib = win.library
    assert lib._kw_create("Minecraft"), "debe crearse"
    assert os.path.isdir(os.path.join(RAIZ, "Minecraft")), "la subcarpeta propia debe existir"
    nodo = _nodo(lib, "Minecraft")
    assert nodo is not None and nodo.text(0).startswith("Minecraft  (0)"), nodo and nodo.text(0)
    fort = _nodo(lib, "Fortnite")
    assert fort is not None and fort.text(0).startswith("Fortnite  (2)"), fort and fort.text(0)
    assert sorted(a.text(0) for a in _archivos(fort)) == ["gen.mp4", "imagen.png"], [a.text(0) for a in _archivos(fort)]
    _ok("Medios ▸ 🔑 Palabras clave: «Minecraft» creada (0 archivos); «Fortnite» con sus 2 archivos propios")


def prueba_enlazar(win, raiz_fort_pc: str, clips: ClipsPanel):
    lib = win.library
    antes_pc = _listado(raiz_fort_pc)
    antes_propia = _listado(os.path.join(RAIZ, "Fortnite"))
    assert lib._kw_link("Fortnite", raiz_fort_pc), "debe enlazarse"
    assert any(os.path.normcase(p) == os.path.normcase(raiz_fort_pc) for p in KF.linked(RAIZ, "Fortnite"))

    fort = _nodo(lib, "Fortnite")
    assert fort.text(0).startswith("Fortnite  (4)"), fort.text(0)            # 2 propios + 2 del PC
    nombres = sorted(a.text(0) for a in _archivos(fort))
    assert nombres == sorted(["🔗 clip_pc.mp4", "🔗 foto_pc.png", "gen.mp4", "imagen.png"]), nombres
    enlazados = [a for a in _archivos(fort) if a.data(0, LIB.ROLE_KW_LINKED)]
    assert len(enlazados) == 2 and all(raiz_fort_pc in a.toolTip(0) for a in enlazados), enlazados
    enlace = _hijos(fort, "link")
    assert len(enlace) == 1 and enlace[0].data(0, LIB.ROLE_PATH) == os.path.abspath(raiz_fort_pc), enlace
    assert not os.path.exists(os.path.join(RAIZ, "Fortnite", "clip_pc.mp4")), "el archivo del PC NO se copia"
    assert _listado(raiz_fort_pc) == antes_pc, "la carpeta del PC debe quedar igual"
    assert _listado(os.path.join(RAIZ, "Fortnite")) == antes_propia, "la subcarpeta propia no cambia"
    _ok("📂 Añadir carpeta de mi PC: «Fortnite» muestra 🔗 clip_pc.mp4 y 🔗 foto_pc.png sin copiarlos; "
        "la carpeta del PC y la propia quedan iguales")

    # 🎬 Clips: los mismos archivos (con 🔗) en la cuadrícula de la palabra
    clips.recalcular()
    _elegir(clips, "Fortnite")
    en_clips = [clips.lista_carpeta.item(i).text() for i in range(clips.lista_carpeta.count())]
    assert sorted(en_clips) == sorted(nombres), en_clips
    assert clips.lista_menciones.item(_fila(clips, "Fortnite")).text().endswith("📁 4"), "el distintivo cuenta los enlaces"
    _ok("🎬 Clips: «Fortnite» 📁 4 con 🔗 en sus archivos enlazados")


def prueba_soltar(win, soltada: str, archivo_suelto: str, clips: ClipsPanel):
    lib = win.library
    antes = _listado(soltada)
    lib._kw_drop([soltada], "Minecraft")                                   # carpeta soltada = enlace
    assert any(os.path.normcase(p) == os.path.normcase(soltada) for p in KF.linked(RAIZ, "Minecraft"))
    assert not os.path.exists(os.path.join(RAIZ, "Minecraft", "suelta.png")), "la carpeta soltada NO se copia"
    assert _listado(soltada) == antes
    _ok("soltar una CARPETA sobre «Minecraft» = enlace (no copia)")

    # archivo soltado = copia. (Desde el cambio «enlazar o copiar» Reclaimer pregunta una vez; aquí se responde
    # «copiar» para comprobar lo de siempre.)
    original_modo = LIB.modo_archivo_suelto
    LIB.modo_archivo_suelto = lambda parent: "copiar"
    try:
        lib._kw_drop([archivo_suelto], "Minecraft")
    finally:
        LIB.modo_archivo_suelto = original_modo
    copia = os.path.join(RAIZ, "Minecraft", "foto_suelta.png")
    assert os.path.isfile(copia), "el archivo soltado debe copiarse a la carpeta propia"
    assert os.path.isfile(archivo_suelto), "el original no se mueve"
    assert not any(os.path.normcase(p) == os.path.normcase(archivo_suelto) for p in KF.linked(RAIZ, "Minecraft"))
    _ok("soltar un ARCHIVO sobre «Minecraft» = copia a su subcarpeta propia")

    # desvincular (menú del enlace): quita el enlace y no borra nada
    mine = _nodo(lib, "Minecraft")
    enlace = _hijos(mine, "link")[0]
    _accion(lib, enlace, "Desvincular").trigger()
    assert KF.linked(RAIZ, "Minecraft") == [], "el enlace se quita del JSON"
    assert _listado(soltada) == antes and os.path.isdir(soltada), "desvincular no borra la carpeta del PC"
    _ok("«Desvincular esta carpeta» quita el enlace y no borra nada")

    # soltar carpeta sobre la fila de «Minecraft» en 🎬 Clips = enlace también
    clips.recalcular()
    _elegir(clips, "Minecraft")
    clips._soltar_archivos([soltada], _fila(clips, "Minecraft"))
    _esperar(clips)
    assert any(os.path.normcase(p) == os.path.normcase(soltada) for p in KF.linked(RAIZ, "Minecraft")), \
        "en 🎬 Clips soltar una carpeta también la enlaza"
    _ok("🎬 Clips: soltar una carpeta sobre una palabra = enlace")


def prueba_crear_de_lo_que_dices(win):
    lib = win.library
    preguntadas: list = []
    original = LIB._pick_terms
    LIB._pick_terms = lambda parent, opciones: (preguntadas.append(list(opciones)) or
                                                [op[0] for op in opciones])
    try:
        lib._kw_auto()
    finally:
        LIB._pick_terms = original
    assert preguntadas, "debe preguntar antes de crear"
    terminos = [op[0] for op in preguntadas[0]]
    assert "Roblox" in terminos, terminos
    assert "Fortnite" not in terminos and "Minecraft" not in terminos, "las que ya tienen carpeta no se preguntan"
    assert os.path.isdir(os.path.join(RAIZ, "Roblox")), "debe crear la carpeta de Roblox"
    assert _nodo(lib, "Roblox") is not None
    _ok(f"✨ Crear de lo que dices: pregunta {terminos} y crea «Roblox» (las que ya tenían carpeta no)")


def prueba_poner_donde_lo_dices(win):
    lib, ctrl = win.library, win.ctrl
    fort = _nodo(lib, "Fortnite")
    hits = [h for h in lib._kw_hits("Fortnite") if h.get("tl") is not None]
    assert len(hits) == 2, [h.get("tl") for h in hits]
    # seleccionar 2 archivos propios de la palabra
    lib.tree.clearSelection()
    for a in _archivos(fort):
        if a.text(0) in ("gen.mp4", "imagen.png"):
            a.setSelected(True)
    antes = set(ctrl.project.clips)
    pila = ctrl.undo_stack.index()
    accion = _accion(lib, fort, "📍 Poner donde lo dices")
    assert accion.text().endswith("(2)"), accion.text()                    # solo los 2 seleccionados
    accion.trigger()
    assert ctrl.undo_stack.index() == pila + 1, "debe ser UN solo paso de deshacer"
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 2, [(c.media_id, c.start) for c in nuevos]
    por_archivo = {c.media_id for c in nuevos}
    assert por_archivo == {_mid_de(ctrl, os.path.join(RAIZ, "Fortnite", "gen.mp4")),
                           _mid_de(ctrl, os.path.join(RAIZ, "Fortnite", "imagen.png"))}, por_archivo
    tiempos = sorted(float(h["tl"]) for h in hits)
    assert sorted(round(c.start, 1) for c in nuevos) == sorted(round(t, 1) for t in tiempos), \
        ([c.start for c in nuevos], tiempos)
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes, "el Ctrl+Z quita todo de una vez"
    _ok(f"📍 Poner donde lo dices: 2 archivos seleccionados repartidos en {[round(t, 1) for t in tiempos]} s; "
        "un solo Ctrl+Z")


def prueba_quitar(win, raiz_fort_pc: str, clips: ClipsPanel):
    lib = win.library
    antes_pc = _listado(raiz_fort_pc)
    propia = os.path.join(RAIZ, "Fortnite")
    enviados: list = []

    def papelera_falsa(ruta: str) -> bool:                              # NUNCA la Papelera real
        enviados.append(os.path.normcase(os.path.abspath(ruta)))
        os.makedirs(papelera_falsa_dir, exist_ok=True)
        shutil.move(ruta, os.path.join(papelera_falsa_dir, os.path.basename(ruta)))
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

    papelera_falsa_dir = os.path.join(BASE, "_papelera_falsa")
    orig_trash, orig_caja, orig_papelera_clips = LIB._to_trash, LIB.QMessageBox, CP._a_papelera
    LIB._to_trash = papelera_falsa
    CP._a_papelera = papelera_falsa
    LIB.QMessageBox = _Caja
    try:
        _accion(lib, _nodo(lib, "Fortnite"), "🗑 Quitar palabra clave").trigger()
    finally:
        LIB._to_trash, LIB.QMessageBox, CP._a_papelera = orig_trash, orig_caja, orig_papelera_clips
    assert enviados == [os.path.normcase(os.path.abspath(propia))], enviados
    assert not os.path.isdir(propia), "la subcarpeta propia fue a la Papelera (falsa)"
    assert os.path.isdir(raiz_fort_pc) and _listado(raiz_fort_pc) == antes_pc, \
        "la carpeta del PC enlazada sigue intacta en disco"
    assert KF.linked(RAIZ, "Fortnite") == [], "el JSON ya no tiene el enlace"
    assert _nodo(lib, "Fortnite") is None, "sin carpeta propia ni enlaces, la palabra desaparece"
    _ok("🗑 Quitar palabra clave: solo se manda a la Papelera (falsa) la carpeta propia; la carpeta del PC "
        "queda intacta y el enlace se quita")


def main():
    global app
    app = QApplication.instance() or QApplication(sys.argv)
    ajustes = QSettings("EditorIA", "EditorIA")
    ClipsPanel._buscar = lambda self, *_a, **_k: None         # sin red
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)
    try:
        video = _video_prueba()
        imagen = _imagen_prueba()
        fort_pc, soltada, archivo_suelto = _preparar(video, imagen)
        ajustes.setValue(CP.RAIZ_CLAVE, RAIZ)                  # la raíz de la prueba, antes de abrir la ventana
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.ctrl.project = _proyecto()
        win.library._rebuild()
        clips = win.clips
        assert CP._raiz_guardada() == RAIZ
        clips.recalcular()

        prueba_crear(win)
        prueba_enlazar(win, fort_pc, clips)
        prueba_soltar(win, soltada, archivo_suelto, clips)
        prueba_crear_de_lo_que_dices(win)
        prueba_poner_donde_lo_dices(win)
        prueba_quitar(win, fort_pc, clips)
        win.deleteLater()
        app.processEvents()
    finally:
        ajustes.remove(CP.RAIZ_CLAVE)
    print("TODO OK")


if __name__ == "__main__":
    main()
