"""
🎨 Prueba de la «profundidad sutil» (ui/diseno.py, theme.py, timeline.py):
  1) las fichas existen y forman capas (campo < fondo < bloque < menú/controles), calculadas desde el tema activo;
  2) la hoja general lleva el bloque de profundidad y el botón principal sigue el acento (también «#primary»);
  3) el clip que se arrastra se pinta 4 px más arriba y con sombra (y sin profundidad, en su sitio);
  4) pintar la línea de tiempo con muchos clips no tarda más de un 10 % más (con y sin profundidad);
  5) cambiar el acento no tarda más de un 10 % más (se mide e informa);
  6) las cabeceras plegables llevan su degradado y su bisel.
Ejecutar:  .venv/Scripts/python.exe tests/test_profundidad.py <carpeta_salida>
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="reclaimer_profundidad_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, TMP, True)
os.environ["LOCALAPPDATA"] = TMP
os.environ["EDITORIA_DATOS"] = os.path.join(TMP, "EditorIA")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (ajustes de prueba: nunca los tuyos)

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def lum(h) -> float:
    c = QColor(h)
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def dist(a: QColor, b) -> int:
    b = QColor(b)
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_profundidad")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui import diseno as D
    from editoria.ui import theme as T
    T.apply_dark_theme(app)
    acento_antes = T.ACENTO

    # ---- 1) fichas
    f = D.fichas()
    for k in ("fondo", "bloque", "bloque_borde", "bloque_luz", "control_arriba", "control_abajo", "control_borde",
              "control_luz", "menu", "menu_borde", "cab_arriba", "cab_abajo", "bisel_luz", "bisel_sombra", "campo",
              "campo_borde", "campo_borde_inf", "campo_sombra"):
        assert k in f, k
    assert f["fondo"] == T.BG
    assert lum(f["campo"]) < lum(f["fondo"]) < lum(f["bloque"]) < lum(f["menu"]), f
    assert lum(f["control_abajo"]) < lum(f["control_arriba"]) and lum(f["cab_abajo"]) < lum(f["cab_arriba"])
    assert lum(f["campo_sombra"]) < lum(f["campo"]) < lum(f["campo_borde_inf"])
    a = D.degradado_acento("#97a3b3")                   # (Acero: lo de la maqueta aprobada)
    for k, esperado in (("arriba", "#dfe5ec"), ("abajo", "#a7b2bf"), ("borde", "#6f7a88")):
        assert dist(QColor(a[k]), esperado) <= 18, (k, a[k], esperado)
    assert T.ACENTO_POR_DEFECTO == "acero"
    print(f"✓ fichas en capas desde el tema activo (fondo {f['fondo']} · bloque {f['bloque']} · menú {f['menu']} · "
          f"campo {f['campo']}); con Acero el botón principal es {a['arriba']} → {a['abajo']}")

    # ---- 2) la hoja general y el botón principal siguen el acento
    assert D.MARCA_QSS in T.STYLE and D.MARCA_QSS in app.styleSheet()
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    pump(app, 0.5)
    vp = win.voice
    btn = vp.btn_auto_clean
    try:
        for clave in ("naranja", "cromo", "acero"):
            T.poner_acento(clave, app, guardar=False)
            app.processEvents()
            g = D.degradado_acento()
            assert btn.degradado_ahora()["abajo"] == g["abajo"] == D.degradado_acento(T.ACCENT)["abajo"]
            assert g["abajo"] in app.styleSheet() and g["borde"] in app.styleSheet(), clave
            img = btn.grab().toImage()
            px_ = QColor(img.pixel(img.width() // 2 + 30, img.height() - 4))
            assert dist(px_, g["abajo"]) < 40, (clave, px_.name(), g["abajo"])
    finally:
        T.poner_acento(acento_antes, app, guardar=False)
    print("✓ «Limpiar» y «#primary» sacan su degradado del acento elegido (naranja, cromo, acero)")

    # ---- 6) cabeceras con bisel
    from PySide6.QtWidgets import QToolButton
    heads = [w for w in win.findChildren(QToolButton) if w.objectName() == "sectionhead"]
    assert heads and all("qlineargradient" in w.styleSheet() and "border-top" in w.styleSheet() for w in heads[:20])
    acordeon = win.audio_panel
    cab = next(iter(acordeon._cab.values()))
    assert "qlineargradient" in cab.styleSheet() and "border-bottom" in cab.styleSheet()
    print(f"✓ cabeceras plegables con degradado y bisel ({len(heads)} secciones y el acordeón)")
    # (en los temas grises theme aclara los colores de las hojas propias: se mira que el color fijo ya no está)
    assert all("#d8dbe2" not in w.styleSheet() and "color:" in w.styleSheet() for w in heads[:20])
    h = heads[0]
    alto = h.sizeHint().height()
    h.setDown(True)
    app.processEvents()
    assert h.sizeHint().height() == alto, "al pulsar, la cabecera no cambia de alto"
    h.setDown(False)
    css_antes, css_cab = h.styleSheet(), cab.styleSheet()
    D.fichas_original = D.fichas
    try:                                               # (un tema distinto en vivo: las cabeceras se rehacen)
        D.fichas = lambda: dict(D.fichas_original(), cab_arriba="#505050")
        T.poner_acento("naranja", app, guardar=False)
        assert h.styleSheet() != css_antes and cab.styleSheet() != css_cab, "cabeceras rehechas en vivo"
    finally:
        D.fichas = D.fichas_original
        T.poner_acento(acento_antes, app, guardar=False)
    assert h.styleSheet() == css_antes
    print("✓ cabeceras: texto con el color del tema, mismo alto al pulsar y rehechas al cambiar tema o acento")

    # ---- 2b) botón marcado con el ratón encima, foco de los desplegables y alto del título de panel
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QComboBox, QDockWidget, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

    def pix(w, fx=0.06, fy=0.5):
        img = w.grab().toImage()
        return QColor(img.pixel(int(img.width() * fx), int(img.height() * fy)))

    def borde_arriba(w):
        img = w.grab().toImage()
        return QColor(img.pixel(img.width() // 2, 0))

    def encima(w, on):
        from PySide6.QtTest import QTest              # (ratón de verdad: Qt pone «:hover» como con el usuario)
        if on:
            QTest.mouseMove(w, w.rect().center())
        else:
            QTest.mouseMove(w.window(), w.window().rect().bottomRight())
        app.processEvents()

    def sondas(prof: bool):
        D.PROFUNDIDAD = prof
        T.STYLE = T._estilo()
        app.setStyleSheet(T.STYLE)
        caja = QWidget()
        lay = QVBoxLayout(caja)
        marcado, normal = QPushButton("Marcado"), QPushButton("Normal")
        marcado.setCheckable(True)
        marcado.setChecked(True)
        combo, combo_ed, otro = QComboBox(), QComboBox(), QPushButton("otro")
        combo.addItems(["uno", "dos"])
        combo_ed.setEditable(True)
        combo_ed.addItems(["uno", "dos"])
        for w in (marcado, normal, combo, combo_ed, otro):
            lay.addWidget(w)
        caja.resize(260, 220)
        caja.show()
        caja.activateWindow()
        app.processEvents()
        r = {"marcado": pix(marcado), "normal": pix(normal)}
        encima(marcado, True)
        r["marcado_encima"] = pix(marcado)
        encima(marcado, False)
        encima(normal, True)
        r["normal_encima"] = pix(normal)
        encima(normal, False)
        otro.setFocus()
        app.processEvents()
        r["combo_sin_foco"], r["combo_ed_sin_foco"] = borde_arriba(combo), borde_arriba(combo_ed)
        combo.setFocus()
        app.processEvents()
        r["combo_foco"] = borde_arriba(combo)
        combo_ed.setFocus()
        app.processEvents()
        r["combo_ed_foco"] = borde_arriba(combo_ed)
        caja.close()
        mw = QMainWindow()
        dk = QDockWidget("Panel")
        dk.setWidget(QLabel("x"))
        mw.addDockWidget(_Qt.LeftDockWidgetArea, dk)
        mw.resize(300, 200)
        mw.show()
        app.processEvents()
        r["titulo_panel"] = dk.widget().geometry().top()
        mw.close()
        return r
    win.hide()                                         # (que el ratón de prueba no caiga en la ventana principal)
    try:
        plano, hondo = sondas(False), sondas(True)
    finally:
        win.show()
        D.PROFUNDIDAD = True
        T.STYLE = T._estilo()
        app.setStyleSheet(T.STYLE)
    print("  sondas (sin → con):", {k: (v.name() if isinstance(v, QColor) else v,
                                         hondo[k].name() if isinstance(hondo[k], QColor) else hondo[k])
                                     for k, v in plano.items()})
    assert dist(hondo["normal_encima"], hondo["normal"].name()) > 8, "la sonda de «ratón encima» funciona"
    assert dist(hondo["marcado_encima"], hondo["normal_encima"].name()) > 25, "marcado + encima ≠ sin marcar + encima"
    assert dist(hondo["marcado_encima"], hondo["marcado"].name()) < 45, "marcado + encima sigue siendo «marcado»"
    for k in ("combo", "combo_ed"):
        assert dist(hondo[f"{k}_foco"], hondo[f"{k}_sin_foco"].name()) > 20, (k, "el foco cambia el borde")
        assert dist(hondo[f"{k}_foco"], plano[f"{k}_foco"].name()) < 40, (k, "el borde de foco es el de siempre")
    assert hondo["titulo_panel"] == plano["titulo_panel"], ("el título de panel mide lo mismo", plano, hondo)
    print("✓ marcado + ratón encima sigue marcado; los desplegables enseñan su borde de foco; títulos de panel igual "
          "de altos")

    # ---- reservas de la fase A: flechas del deslizador y tamaño de letra al momento
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    vs = vp.min_sil
    vs.setValue(1.2)

    def tecla(w, k, mod=Qt.NoModifier):
        over = QKeyEvent(QEvent.ShortcutOverride, k, mod)
        over.ignore()
        QApplication.sendEvent(w, over)
        assert over.isAccepted(), "con el foco en el deslizador, la flecha no es un atajo"
        QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, k, mod))
    tecla(vs.deslizador, Qt.Key_Right)
    assert abs(vs.value() - 1.3) < 1e-6, vs.value()
    tecla(vs.deslizador, Qt.Key_Left, Qt.ShiftModifier)
    assert abs(vs.value() - 1.29) < 1e-6, vs.value()
    vs.setValue(1.2)
    vp.auto_chk["filler"].setChecked(True)
    vp.chk_fill.setChecked(False)
    assert not vp.auto_chk["filler"].isChecked()
    vp.chk_fill.setChecked(True)
    assert vp.auto_chk["filler"].isChecked(), "al volver a marcar «Marcar», «Quitar» vuelve como estaba"
    letra = app.font()
    alto = btn.maximumHeight()
    try:
        grande = app.font()
        grande.setPointSizeF(letra.pointSizeF() * 1.5)
        app.setFont(grande)
        D.refrescar_escala()
        assert btn.maximumHeight() == D.px(D.ALTO_PRINCIPAL) and btn.maximumHeight() >= int(alto * 1.4), \
            (alto, btn.maximumHeight())
        assert vp.tabla.etiqueta("silence").font().pixelSize() == D.px(D.LETRA_M)
    finally:
        app.setFont(letra)
        D.refrescar_escala()
    assert btn.maximumHeight() == alto, (alto, btn.maximumHeight())
    print("✓ flechas del deslizador (Mayús = fino) y Ventana → Tamaño de letra rehace «Limpiar» al momento")

    # ---- 3) el clip que se arrastra, levantado y con sombra
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    vid = os.path.join(TMP, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", vid], check=True)
    c = win.ctrl
    tl = win.timeline
    (mid,) = c.import_now([vid])
    while c.analyzing:
        pump(app, 0.1)
    v1 = [t for t in c.project.tracks if t.kind == TRACK_VIDEO][-1]
    n = 600
    c.insert_ranges([{"media_id": mid, "start": i * 1.0, "duration": 1.0, "source_in": (i % 18) * 1.0}
                     for i in range(n)], v1.id, "muchos")
    pump(app, 0.8)
    tl.pps = 60.0
    tl.scroll = 2.0
    tl._update_scrollbar()
    pump(app, 0.3)
    clip = min(c.project.clips_on(v1.id), key=lambda x: abs(x.start - 6.0))
    rc = tl.clip_rect(clip)
    dt = 3.0
    destino = tl.clip_rect(clip, clip.start + dt)
    x = int(destino.center().x())
    y_arriba = int(destino.top()) - 2                  # (por encima de donde iría sin levantar)

    def con_arrastre(prof: bool):
        D.PROFUNDIDAD = prof
        tl._drag = {"type": "move", "active": True, "ids": [clip.id], "dt": dt, "anchor": clip.id, "x0": 0, "y0": 0}
        img = tl.grab().toImage()
        tl._drag = None
        return img
    try:
        plano = con_arrastre(False)
        hondo = con_arrastre(True)
    finally:
        D.PROFUNDIDAD = True
    fondo_pista = QColor(plano.pixel(x, y_arriba))
    levantado = QColor(hondo.pixel(x, y_arriba))
    assert dist(levantado, fondo_pista.name()) > 30, (levantado.name(), fondo_pista.name())
    y_sombra = int(destino.bottom()) + 4
    if y_sombra < tl.height():
        assert lum(QColor(hondo.pixel(x, y_sombra)).name()) < lum(QColor(plano.pixel(x, y_sombra)).name()), \
            "la sombra oscurece debajo del clip levantado"
    hondo.save(os.path.join(out, "clip_arrastrado.png"))
    print(f"✓ el clip arrastrado se pinta {tl.LEVANTAR} px más arriba con su sombra (sin profundidad, en su sitio)")

    # ---- 4) tiempo de pintado con muchos clips
    def medir(prof: bool, reps=12):
        D.PROFUNDIDAD = prof
        ts = []
        for _ in range(reps):
            t0 = time.perf_counter()
            tl.repaint()
            ts.append(time.perf_counter() - t0)
        return statistics.median(ts) * 1000
    try:
        for pps in (60.0, 14.0):                       # (clips anchos con título · clips de 7–40 px)
            tl.pps = pps
            tl._update_scrollbar()
            pump(app, 0.2)
            medir(True, 3)
            medir(False, 3)
            a_, b_ = [], []
            for _ in range(5):                         # (intercalado: el ruido del PC afecta a los dos igual)
                a_.append(medir(False))
                b_.append(medir(True))
            plano_ms, hondo_ms = statistics.median(a_), statistics.median(b_)
            print(f"  {len(c.project.clips)} clips a {pps:g} px/s: sin profundidad {plano_ms:.2f} ms · "
                  f"con profundidad {hondo_ms:.2f} ms ({(hondo_ms / plano_ms - 1) * 100:+.1f} %)")
            assert hondo_ms <= plano_ms * 1.10 + 0.3, (pps, plano_ms, hondo_ms)
    finally:
        D.PROFUNDIDAD = True
    print("✓ pintar la línea de tiempo no tarda más de un 10 % más")

    # ---- 5) el cambio de acento
    def cambio_acento():
        t0 = time.perf_counter()
        T.poner_acento("naranja", app, guardar=False)
        T.poner_acento(acento_antes if acento_antes != "naranja" else "acero", app, guardar=False)
        return (time.perf_counter() - t0) / 2

    def con(prof: bool):
        D.PROFUNDIDAD = prof
        T.STYLE = T._estilo()
        T.apply_fonts(app)
        app.processEvents()
        return cambio_acento()
    try:
        con(True)
        sin_t, con_t = [], []
        for _ in range(2):
            sin_t.append(con(False))
            con_t.append(con(True))
    finally:
        D.PROFUNDIDAD = True
        T.poner_acento(acento_antes, app, guardar=False)
    s_, c_ = min(sin_t), min(con_t)
    print(f"  cambiar el acento: sin profundidad {s_:.2f} s · con profundidad {c_:.2f} s "
          f"({(c_ / s_ - 1) * 100:+.1f} %)")
    assert c_ <= s_ * 1.10 + 0.05, (s_, c_)
    print("✓ cambiar el acento no tarda más de un 10 % más")

    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    # (sin hilos vivos al salir —«🎯 Afinar palabras» y compañía—: si no, Python sale con código 127)
    from editoria.ui.jobs import live_jobs
    from editoria.ui.task_window import stop_all
    stop_all(15000)
    win.analyzer.shutdown()
    win.ctrl.shutdown(15000)
    t_fin = time.time() + 60
    while time.time() < t_fin and any(j.isRunning() for j in live_jobs()):
        pump(app, 0.05)
    print("TODO OK")


if __name__ == "__main__":
    main()
