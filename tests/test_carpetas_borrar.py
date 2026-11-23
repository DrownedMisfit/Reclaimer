"""
🗑 Palabras clave → Carpetas: borrar de verdad (22/11, el usuario: «Borrar todo lo descargado no borra nada», «no deja
borrar la carpeta elegida ni un video suelto» y «las miniaturas salen en negro»). Sin red, offscreen y con la Papelera
SUSTITUIDA (nada real va a la Papelera; todo en una carpeta de prueba con la estructura de «Clips por palabra»):
  · miniatura de un video que empieza en negro (fundido): ya no es negra (fotograma a ~10 %);
  · «Todo lo descargado»: Quitar un archivo suelto de la rejilla y luego la carpeta elegida entera, con sus créditos;
    lo tuyo (sin créditos) no se toca y la vista se pone al día sola;
  · «Borrar todo lo descargado…»: lo que queda, y los «.creditos.json» sueltos; «Todo lo descargado» se pone al día;
  · cabecera de Carpetas en UNA fila (selector + iconos) y «Sin audio» entero a la vista en Buscar material.
Ejecutar (con el turno):  turno.py tests/test_carpetas_borrar.py
"""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_carpetas_borrar_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import faulthandler  # noqa: E402
faulthandler.enable()
faulthandler.dump_traceback_later(300, exit=True)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editoria.ui import clips_panel as CP  # noqa: E402

QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.Yes)
PAPELERA = os.path.join(_TMP, "papelera_falsa")
os.makedirs(PAPELERA, exist_ok=True)
FALLOS = []


def _papelera_falsa(ruta: str) -> bool:
    if not os.path.exists(ruta):
        return False
    shutil.move(ruta, os.path.join(PAPELERA, f"{len(os.listdir(PAPELERA))}_{os.path.basename(ruta)}"))
    return True


CP._a_papelera = _papelera_falsa


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=20):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        pump(app, 0.05)
    return cond()


def video(ruta: str, creditos: bool = True):
    """5 s: 1,5 s en negro (fundido) y luego color."""
    from editoria.core import media as MEDIA
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    subprocess.run([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=10:d=1.5", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=3.5",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", ruta], check=True)
    if creditos:
        with open(os.path.splitext(ruta)[0] + ".creditos.json", "w", encoding="utf-8") as f:
            f.write('{"title": "x", "url": "https://ejemplo.invalid", "term": "prueba"}')


def hoja(d, nombre):
    for i in range(d.arbol.topLevelItemCount()):
        top = d.arbol.topLevelItem(i)
        for k in range(top.childCount()):
            if top.child(k).text(0).startswith(f"📁 {nombre} "):
                return top.child(k)
    return None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    raiz = os.path.join(_TMP, "Reclaimer - Clips por palabra")
    bolly = [os.path.join(raiz, "Bollywood", f"clip {i} [b{i}] (sin audio).mp4") for i in range(3)]
    gta = [os.path.join(raiz, "GTA 6", f"gta {i} [g{i}] (sin audio).mp4") for i in range(2)]
    for r in bolly + gta:
        video(r)
    mio = os.path.join(raiz, "GTA 6", "mio.mp4")
    video(mio, creditos=False)
    huerfano = os.path.join(raiz, "GTA 6", "ya no está [z9] (sin audio).creditos.json")
    with open(huerfano, "w", encoding="utf-8") as f:
        f.write("{}")
    try:                                   # (parte opcional: en la versión pública no está)
        from editoria.ai import clip_download
        clip_download.DESCARGAS_DIR = __import__("pathlib").Path(os.path.join(_TMP, "Descargas_sin_palabra"))
    except ImportError:
        pass

    # 1) miniatura de un video que empieza en negro
    png = os.path.join(_TMP, "mini.png")
    ok = CP._hacer_miniatura(bolly[0], png)
    chk(ok and CP._brillo(QImage(png)) > CP.NEGRO, f"miniatura de un video que empieza en negro: no es negra "
        f"(brillo {CP._brillo(QImage(png)):.0f})")

    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    pump(app, 0.4)
    win.clips.raiz = raiz
    win.clips.recalcular()
    kw = win.kw_folders
    win.show_panel(kw)
    pump(app, 0.4)

    # 5) cabecera en una fila (con sitio), nada cortado
    cab = [kw.btn_vista_palabra, kw.btn_vista_todo, kw.btn_abrir, kw.btn_recargar, kw.btn_limpiar]

    def cabecera_bien(una_fila: bool) -> bool:
        ys = {b.mapTo(kw, b.rect().center()).y() // 8 for b in cab}
        dentro = all(0 <= b.mapTo(kw, b.rect().topLeft()).x() and
                     b.mapTo(kw, b.rect().bottomRight()).x() <= kw.width() for b in cab)
        return all(b.isVisibleTo(kw) for b in cab) and dentro and (len(ys) == 1 or not una_fila)
    dock = kw.parentWidget()
    while dock is not None and not hasattr(dock, "setFloating"):
        dock = dock.parentWidget()
    if dock is not None:                       # (suelto, para darle el ancho que se quiere medir)
        dock.setFloating(True)
        dock.resize(420, 640)
        pump(app, 0.4)
    def donde():
        return [(b.mapTo(kw, b.rect().topLeft()).x(), b.mapTo(kw, b.rect().topLeft()).y(), b.width()) for b in cab]
    chk(cabecera_bien(True), f"Carpetas ({kw.width()} px): selector y botones de icono en UNA fila, a la vista "
        f"{donde()}")
    if dock is not None:
        dock.resize(dock.minimumSizeHint().width(), 640)
        pump(app, 0.4)
        chk(cabecera_bien(False), f"y estrecho ({kw.width()} px): nada cortado (los iconos siguen abajo si no caben)")
        dock.resize(420, 640)
        pump(app, 0.3)

    # 2) «Todo lo descargado»: quitar un archivo suelto de la rejilla
    kw.btn_vista_todo.setChecked(True)
    d = kw.descargado
    chk(d is not None and not d._cab.isVisible(), "«Todo lo descargado» sin su fila de cabecera propia")
    chk(esperar(app, lambda: d._job is None and hoja(d, "Bollywood") is not None),
        f"se lee la carpeta de prueba ({d.estado.text()} · "
        f"{[d.arbol.topLevelItem(i).text(0) for i in range(d.arbol.topLevelItemCount())]})")
    d.arbol.setCurrentItem(hoja(d, "Bollywood"))
    pump(app, 0.2)
    it = next(d.lista.item(i) for i in range(d.lista.count()) if d.lista.item(i).data(Qt.UserRole) == bolly[1])
    chk(esperar(app, lambda: not it.icon().isNull()), "las miniaturas llegan")
    img = it.icon().pixmap(128, 72).toImage()
    chk(CP._brillo(img) > CP.NEGRO, f"y no son negras en la rejilla (brillo {CP._brillo(img):.0f})")
    d.lista.clearSelection()
    it.setSelected(True)
    chk(d.btn_quitar.isVisibleTo(kw) and d.btn_medios.isVisibleTo(kw),
        "«Quitar» a la vista abajo, con «A Medios» y «Poner en el cabezal»")
    d.btn_quitar.click()
    chk(not os.path.exists(bolly[1]) and not os.path.exists(os.path.splitext(bolly[1])[0] + ".creditos.json") and
        os.path.exists(bolly[0]), "Quitar un video suelto: él y sus créditos a la Papelera, los demás no")
    chk(esperar(app, lambda: d._job is None and hoja(d, "Bollywood") is not None and
                "(2)" in hoja(d, "Bollywood").text(0)), "la vista se pone al día sola: «Bollywood (2)»")

    # 3) quitar la carpeta elegida entera (sin nada elegido en la rejilla)
    d.arbol.setCurrentItem(hoja(d, "GTA 6"))
    pump(app, 0.2)
    d.lista.clearSelection()
    n = d.quitar()
    chk(n == 2 and not any(os.path.exists(r) for r in gta) and os.path.isfile(mio),
        "Quitar la carpeta elegida: lo bajado a la Papelera; lo tuyo (sin créditos) se queda")

    # 4) «Borrar todo lo descargado…»
    esperar(app, lambda: d._job is None)
    hechos = kw.borrar_todo_descargado(True, True)
    chk(hechos == 2 and not any(os.path.exists(r) for r in bolly) and not os.path.exists(huerfano) and
        os.path.isfile(mio), f"Borrar todo: lo que quedaba ({hechos}) y los créditos sueltos; lo tuyo no se toca "
        f"(quedan {[os.path.basename(r) for r in bolly + [huerfano] if os.path.exists(r)]} · «{kw.aviso.text()}»)")
    chk(esperar(app, lambda: d._job is None and hoja(d, "Bollywood") is None),
        "y «Todo lo descargado» ya no enseña lo borrado")

    # 6) «Sin audio» entero a la vista en Buscar material (pestaña Internet), también estrecho
    busq = win.clips._busqueda_aparte
    chk_sa = getattr(win.clips, "chk_sin_audio", None)
    if busq is not None and chk_sa is not None:
        win.show_panel(busq)
        tabs = getattr(win.clips, "pestanas", None)
        if tabs is not None and tabs.count() > 1:
            tabs.setCurrentIndex(1)
        pump(app, 0.4)
        izq = chk_sa.mapTo(busq, chk_sa.rect().topLeft()).x()
        der = chk_sa.mapTo(busq, chk_sa.rect().bottomRight()).x()
        chk(chk_sa.isVisibleTo(busq) and izq >= 0 and der <= busq.width(),
            f"Buscar material ({busq.width()} px): «Sin audio» a la vista y entero (x {izq}–{der} de {busq.width()})")
    else:
        print("  · sin la parte de internet: no hay «Sin audio» que mirar")
    win.close()
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s)")
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
