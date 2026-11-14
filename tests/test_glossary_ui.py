"""
Prueba del glosario de «Dijiste…» (🎬 Clips) y de «✨ Crear de lo que dices» (Medios), sin red y sin ventanas:
  · el panel Clips muestra «GTA 6»; tras la consulta (segundo plano) «Ruinas Eternas» sale como conocida con ✓ y
    «Vive Coding» (según internet no es juego) va al final, atenuada;
  · clic derecho «✕ No es palabra clave» sobre «Vive Coding» la quita y queda en el glosario «no»;
  · clic derecho «✓ Es palabra clave» sobre «Pradera Lunar» la guarda en «sí» y ya sale como conocida;
  · el diálogo 📖 Glosario lista las dos listas y «Quitar seleccionadas» funciona (al cerrar se guarda);
  · en Medios, «✨ Crear de lo que dices» no ofrece las de «no» y deja sin marcar lo que internet descarta.
La consulta a internet está sustituida por respuestas fijas. Los diálogos modales se sustituyen (no se abren).
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_glossary_ui.py _pruebas_tmp/test_glossary_ui
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_glos_", dir=_TMPROOT)
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from editoria.ai import game_lookup  # noqa: E402
from editoria.ai import keyword_glossary as KG  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import clips_panel as CP  # noqa: E402
from editoria.ui import help as AYUDA  # noqa: E402
from editoria.ui import library as LIB  # noqa: E402
from editoria.ui.glossary_dialog import GlosarioDialog  # noqa: E402
from editoria.ui.main_window import MainWindow  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
RAIZ_CARPETAS = os.path.join(_TMPROOT, "test_glossary_ui_carpetas")
FRASE = ("hoy vamos a jugar GTA 6 con mis amigos y despues probamos Ruinas Eternas que es muy bueno "
         "pero Vive Coding es otra cosa y tambien Pradera Lunar y Mesa Redonda")

# respuestas fijas de «internet» (lo que no esté aquí, «ninguno»)
RESPUESTAS = {"gta 6": "juego", "ruinas eternas": "juego"}
LLAMADAS: list[str] = []
app = None
win = None
GLOSARIO_ACCION = None      # qué hace el diálogo 📖 Glosario al «abrirse» (en la prueba no se abre de verdad)


def _classify_falso(term, timeout=4):
    LLAMADAS.append(term)
    tipo = RESPUESTAS.get(KG.clave(term), "ninguno")
    return {"tipo": tipo, "titulo": term if tipo != "ninguno" else None, "fuente": "prueba"}


game_lookup.classify = _classify_falso


def _no_modal(self, *_a, **_k):
    """QDialog.exec sustituido: el 📖 Glosario ejecuta la acción de la prueba; el resto, «Cerrar»."""
    if isinstance(self, GlosarioDialog) and GLOSARIO_ACCION is not None:
        GLOSARIO_ACCION(self)
    return 0


QDialog.exec = _no_modal
QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *_a, **_k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *_a, **_k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *_a, **_k: QMessageBox.Ok)


def _proyecto() -> Project:
    p = Project.new()
    frase = FRASE.split()
    words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(frase)]
    dur = float(words[-1][1]) + 1.0
    v2, v1, a1 = p.tracks
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur)
    return p


def _esperar_web(panel, segundos: float = 60.0):
    """Deja terminar la consulta a internet (segundo plano) y procesa su respuesta."""
    t0 = time.time()
    while time.time() - t0 < segundos:
        app.processEvents()
        job = panel._job_web
        if job is None or not job.isRunning():
            break
        time.sleep(0.02)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)


def _textos(panel) -> list[str]:
    return [panel.lista_menciones.item(i).text() for i in range(panel.lista_menciones.count())]


def _fila(panel, term: str) -> int:
    return next(i for i, t in enumerate(_textos(panel)) if t.startswith(term + " ·"))


def _color_gris(item) -> bool:
    return item.foreground().color().name().lower() == "#6b6f78"


def _clic_derecho(panel, term: str, texto_accion: str):
    """Clic derecho real sobre la fila de «term» y pulsa la opción del menú que empieza por «texto_accion»."""
    lista = panel.lista_menciones
    it = lista.item(_fila(panel, term))
    capturado = {}
    original = AYUDA.exec_menu
    AYUDA.exec_menu = lambda menu, pos: capturado.setdefault("menu", menu)
    try:
        panel._clic_derecho(lista, lista.visualItemRect(it).center())
    finally:
        AYUDA.exec_menu = original
    menu = capturado.get("menu")
    assert menu is not None, f"no salió el menú de «{term}»"
    acciones = [a for a in menu.actions() if a.text().startswith(texto_accion)]
    assert acciones, (term, [a.text() for a in menu.actions()])
    acciones[0].trigger()
    app.processEvents()


def prueba_panel_y_verificacion(panel):
    textos = _textos(panel)
    assert any(t.startswith("GTA 6 ·") for t in textos), textos       # antes de consultar
    _esperar_web(panel)
    textos = _textos(panel)
    ruinas = next(t for t in textos if t.startswith("Ruinas Eternas ·"))
    assert ruinas.endswith("✓ juego"), ruinas
    assert "Según internet: juego" in panel.lista_menciones.item(_fila(panel, "Ruinas Eternas")).toolTip()
    vive = _fila(panel, "Vive Coding")
    assert vive >= len(textos) - 3, (vive, textos)                      # las que internet descarta, al final
    assert textos.index(ruinas) < vive
    assert _color_gris(panel.lista_menciones.item(vive)), "«Vive Coding» atenuada"
    assert "no es un juego" in panel.lista_menciones.item(vive).toolTip()
    assert "Ruinas Eternas" in LLAMADAS and "Vive Coding" in LLAMADAS, LLAMADAS
    g = KG.load()
    assert g["web"].get("ruinas eternas", {}).get("tipo") == "juego", g["web"]
    print("✓ panel: «GTA 6» sale; tras internet, «Ruinas Eternas» con ✓ juego y «Vive Coding» al final, atenuada")


def prueba_clic_no(panel):
    _clic_derecho(panel, "Vive Coding", "👎 No es palabra clave")
    assert not any(t.startswith("Vive Coding ·") for t in _textos(panel)), _textos(panel)
    g = KG.load()
    assert "vive coding" in g["no"], g
    assert "vive coding" not in g["si"], g
    print("✓ clic derecho «✕ No es palabra clave» sobre «Vive Coding»: desaparece y queda en el glosario «no»")


def prueba_clic_si(panel):
    _clic_derecho(panel, "Pradera Lunar", "👍 Es palabra clave")
    g = KG.load()
    assert "pradera lunar" in g["si"], g["si"]
    fila = _fila(panel, "Pradera Lunar")
    assert panel.menciones[fila]["known"] is True, panel.menciones[fila]
    print("✓ clic derecho «✓ Es palabra clave» sobre «Pradera Lunar»: queda en el glosario «sí» y sale conocida")


def prueba_dialogo():
    global GLOSARIO_ACCION
    visto = {}

    def accion(dlg):
        si = [dlg.lista_si.item(i).text() for i in range(dlg.lista_si.count())]
        no = [dlg.lista_no.item(i).text() for i in range(dlg.lista_no.count())]
        assert any(t.startswith("Pradera Lunar") for t in si), si
        assert "vive coding" in no, no
        dlg.agregar("Otra Cosa", "si", "juego")
        for i in range(dlg.lista_si.count()):
            if dlg.lista_si.item(i).text().startswith("Pradera Lunar"):
                dlg.lista_si.item(i).setSelected(True)
        assert dlg.quitar_seleccion() == 1
        visto["ok"] = True
        dlg.done(0)                      # al cerrar se guarda

    GLOSARIO_ACCION = accion
    try:
        win.clips._abrir_glosario()
    finally:
        GLOSARIO_ACCION = None
    assert visto.get("ok"), "el diálogo no se abrió"
    g = KG.load()
    assert "pradera lunar" not in g["si"], g["si"]
    assert g["si"]["otra cosa"].get("tipo") == "juego", g["si"]
    assert "vive coding" in g["no"], g["no"]
    print("✓ 📖 Glosario: listas «sí» y «no»; añadir con tipo; quitar una; al cerrar se guarda")


def prueba_medios():
    capturadas: list = []

    def elegir_falso(parent, opciones):
        capturadas.append(list(opciones))
        return []

    original = LIB._pick_terms
    LIB._pick_terms = elegir_falso
    try:
        win.library._kw_auto()
    finally:
        LIB._pick_terms = original
    assert capturadas, "«Crear de lo que dices» no llegó a preguntar"
    ops = {op[0]: op for op in capturadas[0]}
    assert "Vive Coding" not in ops, ops                              # las de «no» no se ofrecen
    assert "Ruinas Eternas" in ops and ops["Ruinas Eternas"][2] is True, ops
    assert "Otra Cosa" in ops and ops["Otra Cosa"][2] is True, ops          # añadida por ti a «sí»: marcada
    assert "Pradera Lunar" in ops and ops["Pradera Lunar"][2] is False, ops  # quitada del «sí»: internet dice ninguno
    assert "Mesa Redonda" in ops and ops["Mesa Redonda"][2] is False, ops    # internet: ninguno, sin marcar
    print("✓ Medios «✨ Crear de lo que dices»: no ofrece «Vive Coding»; «Mesa Redonda» sale sin marcar")


def main():
    global app, win
    app = QApplication.instance() or QApplication(sys.argv)
    ajustes = QSettings("EditorIA", "EditorIA")
    shutil.rmtree(RAIZ_CARPETAS, ignore_errors=True)
    os.makedirs(RAIZ_CARPETAS)
    ajustes.setValue(CP.RAIZ_CLAVE, RAIZ_CARPETAS)
    try:
        win = MainWindow()
        win.ctrl.project = _proyecto()
        win.clips._buscar = lambda *_a, **_k: None          # sin búsqueda en internet de clips
        win.show()
        win.show_panel(win.clips)
        app.processEvents()
        panel = win.clips
        panel.recalcular()
        prueba_panel_y_verificacion(panel)
        prueba_clic_no(panel)
        prueba_clic_si(panel)
        prueba_dialogo()
        panel.recalcular()
        prueba_medios()
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        app.processEvents()
    finally:
        ajustes.remove(CP.RAIZ_CLAVE)
    print("TODO OK")


if __name__ == "__main__":
    main()
