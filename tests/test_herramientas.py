"""
Prueba del panel de herramientas a la derecha del visor (fase 5; editoria/ui/herramientas.py), sin ventanas visibles:
  · en el hueco del visor (proyecto vertical) y, sin sitio, como pestaña «Herramienta» junto al Inspector; nunca
    flotando;
  · como mucho 3 pestañas: la 4.ª guarda la más antigua sin fijar ni trabajando, con su estado (al reabrirla está
    como estaba); la que trabaja y la fijada no se van;
  · la activa con su nombre entero y las demás con el corto (el entero, en el tooltip);
  · doble clic, ✕ y Esc cierran; Ctrl+Tab pasa de una a otra; punto de acento en su botón;
  · el menú rápido del clip elegido va delante (sin contar) y, al quitar la selección, vuelve la herramienta;
  · Exportar, Silencios y Mezcla abren como pestaña (no como ventana); la pregunta de sobrescribir es una barra
    «Sí / No» dentro del panel;
  · «Edita desde tu voz» es una pestaña más;
  · los interruptores de la fila derecha pasan a su nombre corto antes que a solo icono.
Capturas en la carpeta de salida. Ejecutar:  .venv/Scripts/python.exe tests/test_herramientas.py <carpeta>
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# (sin ventanas, pero con una pantalla de 1920×1080 como la del usuario: la de fábrica del modo sin ventanas es de
#  800×800 y ahí el visor no deja hueco. La ruta, relativa: los «:» de la unidad cortarían la opción)
os.makedirs(os.path.join(ROOT, "_pruebas_tmp"), exist_ok=True)
with open(os.path.join(ROOT, "_pruebas_tmp", "pantalla_1080.json"), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"logicalBaseDpi": 96, "dpr": 1}]}')
os.chdir(ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=_pruebas_tmp/pantalla_1080.json"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def pump(app, s=0.2):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp", "herramientas"))
    os.makedirs(out, exist_ok=True)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
    app = QApplication.instance() or QApplication(sys.argv)
    import editoria.ui.audit_dialog as AD
    AD.revision_previa = lambda _w: True
    from editoria.ui import herramientas as H
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1900, 1040)
    win.show()
    pump(app, 1.0)
    ctrl, h = win.ctrl, win.herramientas
    ctrl.set_project_format("short")                       # (vertical: sobra hueco a los lados de la imagen)
    for k in ("media", "palabras", "audio"):               # (un visor ancho, como con la ventana a pantalla completa)
        if k in win.docks:
            win.docks[k].hide()
    pump(app, 0.6)

    # ---- herramientas sencillas para el límite
    botones, campos = {}, {}

    def abrir(k):
        b = botones.setdefault(k, QPushButton(k, win))
        if k not in campos or h.widget(k) is None:
            campos[k] = QLineEdit()
        return h.abrir(k, campos[k] if not h.guardada(k) else None, f"Herramienta {k} larga", k.upper(), "scissors",
                       boton=b)

    abrir("a")
    campos["a"].setText("lo que escribí")
    check(h.donde == "hueco" and h.marco.isVisible() and h.marco.parentWidget() is win.preview.canvas.viewport(),
          f"en el hueco a la derecha del visor ({h.donde}, hueco {h._hueco()}, necesita {h.ancho_necesario()}, vp {win.preview.canvas.viewport().size()})")
    fr = win.preview.canvas.mapFromScene(win.preview.canvas.frame.rect()).boundingRect()
    check(h.marco.geometry().left() > fr.right() and not h.panel.isWindow(), "nunca encima de la imagen ni flotando")
    abrir("b")
    abrir("c")
    check(h.claves() == ["a", "b", "c"] and h.activa == "c", f"tres pestañas ({h.claves()})")
    pa, pb, pc = (h._ts[k].pestana for k in "abc")
    check(all(x.toolButtonStyle() == Qt.ToolButtonTextBesideIcon and x.text() for x in (pa, pb, pc)),
          f"todas con icono Y nombre, nunca solo el icono ({[x.text() for x in (pa, pb, pc)]})")
    check(pc.text() in ("Herramienta c larga", "C") and pa.text() == "A" and "Herramienta a larga" in pa.toolTip(),
          f"la activa con su nombre entero si cabe; las demás, el corto y el entero en el tooltip ({pc.text()}, "
          f"{pa.text()})")
    check(all(p.width() >= p.sizeHint().width() for p in (pa, pb, pc)), "ninguna pestaña cortada")
    check(all(H._Punto in [type(x) for x in botones[k].children()] for k in "abc"),
          "punto de acento en el botón de cada herramienta abierta")

    abrir("d")
    check(h.claves() == ["b", "c", "d"] and h.guardada("a"), f"la 4.ª guarda la más antigua ({h.claves()})")
    abrir("a")
    check(campos["a"].text() == "lo que escribí" and h.widget("a") is campos["a"],
          "al reabrirla está como estaba (el mismo campo, con su texto)")
    check(h.claves() == ["c", "d", "a"], f"y entonces se guarda la siguiente más antigua ({h.claves()})")
    h._ts["c"].trabajando = lambda: True                   # (c trabaja)
    h.fijar("d", True)                                     # (d, fijada)
    abrir("b")
    check(set(h.claves()) == {"c", "d", "b"} and h.guardada("a"),
          f"la que trabaja y la fijada no se van: se guarda la otra ({h.claves()})")
    h._ts["c"].trabajando = None
    h.fijar("d", False)

    # ---- Ctrl+Tab, doble clic, ✕ y Esc
    antes = h.activa
    h._tab.activated.emit()
    check(h.activa != antes, f"Ctrl+Tab pasa a la siguiente ({antes} → {h.activa})")
    h._ts["b"].pestana.doble.emit()
    pump(app, 0.1)
    check(not h.abierta("b"), "doble clic en la pestaña la cierra")
    h.al_frente("c")
    h.panel.btn_cerrar.click()
    check(not h.abierta("c"), "la ✕ cierra la activa")
    h.al_frente("d")
    h.panel._esc.activated.emit()
    check(not h.abierta("d") and not h.claves() and not h.marco.isVisible(), "Esc cierra; sin herramientas, nada")
    check(not any(x.isVisible() for k in "bcd" for x in botones[k].children() if isinstance(x, H._Punto)),
          "sin herramienta abierta, sin punto")

    # ---- Exportar, Silencios y Mezcla: pestañas, no ventanas
    import subprocess
    from editoria.core import media as MT
    vid = os.path.join(out, "clip de prueba.mp4")
    subprocess.run([MT.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30",
                    "-t", "6", "-pix_fmt", "yuv420p", vid], check=True)
    (vmid,) = ctrl.import_now([vid])
    ctrl.add_media([vmid], None, 0.0)
    pump(app, 0.3)
    win.export()
    pump(app, 0.2)
    exp = h.widget("exportar")
    check(h.abierta("exportar") and not exp.isWindow() and h.activa == "exportar",
          "Exportar abre como pestaña delante")
    check(h.donde == "hueco" and h.marco.width() <= h._hueco().width(),
          f"Exportar cabe en su sitio, junto al visor (hueco {h._hueco().width()} px, pide {h.ancho_necesario()})")
    check(not exp.progress.isVisible(), "sin exportar, sin barra de progreso vacía")
    hv = win.preview.canvas.viewport().height()
    check(h.marco.height() <= h.alto_contenido(h.marco.width()) + 1,
          f"el panel no es más alto que su contenido ({h.marco.height()} de {hv} px)")
    win.grab().save(os.path.join(out, "2_exportar.png"))
    destino = os.path.join(out, "ya_existe.mp4")
    with open(destino, "wb") as f:
        f.write(b"x")
    exp.out.setText(destino)
    exp._start()
    pump(app, 0.1)
    check(h.panel.confirmar.abierta and "Reemplazar" in h.panel.confirmar.si.text() and exp.proc is None,
          "sobrescribir: barra «Sí / No» dentro del panel (no una ventana)")
    win.grab().save(os.path.join(out, "3_confirmar.png"))
    h.panel.confirmar.no.click()
    check(not h.panel.confirmar.abierta and exp.proc is None, "«No» no exporta")
    wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    (nid,) = ctrl.import_now([wav])
    ctrl.add_media([nid], None, 0.0)
    pump(app, 0.3)
    win.open_mix()
    pump(app, 0.2)
    mix = h.widget("mezcla")
    check(h.abierta("mezcla") and mix is not None and not mix.isWindow() and mix.isVisible(),
          "Mezcla abre como pestaña (no como ventana)")
    win.open_silence()
    pump(app, 0.3)
    sil = h.widget("silencios")
    check(h.abierta("silencios") and sil is not None and not sil.isWindow(), "Silencios abre como pestaña")
    check(len(h.claves()) == 3, f"tres a la vez ({h.claves()})")
    ts = [h._ts[k].pestana for k in h.claves()]
    check(all(x.toolButtonStyle() == Qt.ToolButtonTextBesideIcon and x.text() and x.width() >= x.sizeHint().width()
              for x in ts), f"tres pestañas reales con icono y nombre, ninguna cortada ({[x.text() for x in ts]})")
    if h.donde == "pestana":
        check(h.dock.windowTitle() == h._ts[h.activa].corto,
              f"junto al Inspector, la pestaña lleva el nombre de la herramienta ({h.dock.windowTitle()})")
    win.grab().save(os.path.join(out, "1_tres_pestanas.png"))
    sil.reject()
    pump(app, 0.2)
    check(not h.abierta("silencios"), "«Cancelar» de Silencios cierra su pestaña")
    pump(app, 0.5)
    hu = h._hueco()
    check(h.donde == "hueco" or (hu is not None and h.ancho_necesario() + 12 > hu.width()),
          f"al cerrar la ancha, la que queda vuelve junto al visor si cabe ({h.donde}, pide {h.ancho_necesario()}, "
          f"hueco {hu.width() if hu else None})")

    # ---- el menú rápido del clip, delante (sin contar) y, sin selección, vuelve la herramienta
    print(f"  (Exportar va en: {h.donde}; ancho que pide {h.ancho_necesario()})")
    for k in list(h.claves()):
        h.cerrar(k)
    pump(app, 0.6)
    check(not h.claves(), "Cerrar las pestañas de diálogo (Mezcla y Exportar) las quita")
    win.export()                                       # (una herramienta real, que cabe junto al visor)
    pump(app, 0.4)
    check(h.donde == "hueco" and h.activa == "exportar", f"Exportar vuelve al hueco del visor ({h.donde})")
    clip = next(c.id for c in ctrl.project.clips.values() if ctrl.project.media_of(c) is not None
                and ctrl.project.media_of(c).kind in ("video", "image"))
    win.timeline.set_selection([clip])
    pump(app, 0.3)
    mr = win.menu_rapido
    check(h.clip_delante() and mr.isVisible() and h.panel.pila.currentWidget() is h.panel.vacia,
          f"con un clip elegido, el menú rápido va delante dentro del panel ({h.clip_delante()}, {mr.isVisible()}, {mr._clip}, {h._herramienta_pedida}, {h._clip_delante}, {getattr(win.preview.canvas, 'framing_enabled', None)}, {getattr(win.inspector, '_ids', None)})")
    check(h.marco.geometry().contains(mr.geometry().center()) and h.claves() == ["exportar"],
          "dentro del panel y sin contar en el límite")
    pila = h.panel.pila.geometry()
    arriba = h.panel.mapTo(win.preview.canvas.viewport(), pila.topLeft()).y()
    check(abs(mr.geometry().top() - arriba) <= 2 and mr.geometry().bottom() <= h.marco.geometry().bottom() + 2 and
          h.marco.height() < win.preview.canvas.viewport().height() - 2 * 6 - 4,
          f"pegado arriba y el panel a su alto, sin hueco (menú {mr.geometry().top()}–{mr.geometry().bottom()}, "
          f"panel {h.marco.geometry().top()}–{h.marco.geometry().bottom()})")
    win.grab().save(os.path.join(out, "4_menu_rapido_delante.png"))
    win.timeline.set_selection([])
    pump(app, 0.3)
    check(not h.clip_delante() and h.activa == "exportar" and h.panel.pila.currentWidget() is h._ts["exportar"].caja,
          "sin selección, vuelve la herramienta")

    # ---- «Edita desde tu voz», una pestaña más
    ev = win.edita_voz
    ev.abrir(1)
    pump(app, 0.2)
    check(h.abierta("edita_voz") and h.activa == "edita_voz" and ev.anfitrion.visible,
          "«Edita desde tu voz» es una pestaña más del mismo panel")
    win.grab().save(os.path.join(out, "5_edita_voz.png"))

    # ---- sin sitio: pestaña «Herramienta» junto al Inspector
    ctrl.set_project_format("youtube")
    win.resize(1300, 900)
    pump(app, 0.6)
    h.mostrar()
    pump(app, 0.3)
    check(h.donde == "pestana" and h.dock is not None and not h.dock.isFloating() and
          win.tabifiedDockWidgets(win.docks["inspector"]).count(h.dock) == 1,
          f"sin sitio, pestaña junto al Inspector, nunca flotando ({h.donde})")
    check(h.dock.windowTitle() == h._ts[h.activa].corto and h.dock.windowTitle() != "Herramienta",
          f"y con el nombre de la herramienta, nunca «Herramienta» ({h.dock.windowTitle()})")
    win.grab().save(os.path.join(out, "6_junto_al_inspector.png"))

    # ---- interruptores de la derecha: nombre corto antes que solo icono
    malos = []
    for b in list(win.interruptores.values()) + [win._btn_alto]:
        if b.isHidden():
            continue
        nombre, corto = b.property("nombre"), b.property("corto")
        if b.toolButtonStyle() != Qt.ToolButtonIconOnly and b.text() not in (nombre, corto):
            malos.append(b.text())
        if b.width() < b.sizeHint().width() - 1:
            malos.append("cortado: " + b.text())
    check(not malos and win._btn_alto.property("corto") == "Alto", f"interruptores con nombre o nombre corto ({malos})")
    print("TODO BIEN")


if __name__ == "__main__":
    main()
