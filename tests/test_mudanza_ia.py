"""
Prueba corta de la mudanza de la pestaña «IA» (24/11): ya no hay pestaña IA; Transcribir está en «Voz y texto»;
Comparación y Recortar sujeto, en el menú rápido del clip y en su clic derecho; lo demás, en «Edita desde tu voz» ›
Más herramientas (plegada de entrada; cada una abre su bloque de siempre como pestaña del panel de herramientas); el
aviso de la mudanza sale una sola vez. Sin ventanas visibles. Capturas en la carpeta de salida.
Ejecutar:  .venv/Scripts/python.exe tests/test_mudanza_ia.py <carpeta>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp", "mudanza_ia"))
    os.makedirs(out, exist_ok=True)
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    st = QSettings("EditorIA", "EditorIA")
    st.remove(MainWindow.AJ_MUDANZA_IA)
    st.setValue("edita_voz/mas_herramientas", "false")
    win = MainWindow()
    win.resize(1900, 1040)
    win.show()
    pump(app, 3.2)                                         # (el aviso sale a los 2,5 s)

    # ---- el aviso de la mudanza, una vez
    check(win.TEXTO_MUDANZA_IA in win.statusBar().currentMessage(),
          "el aviso de la mudanza sale en la barra de estado (sin ventanas)")
    check(str(st.value(win.AJ_MUDANZA_IA)).lower() == "true" and win._aviso_mudanza_ia() is False,
          "y se recuerda: no vuelve a salir")

    # ---- sin pestaña IA
    check("ai" not in win.interruptores and win.docks["ai"].isHidden()
          and not win.docks["ai"].toggleViewAction().isVisible(), "no hay pestaña «IA» (ni su interruptor)")

    # ---- Transcribir, en Voz y texto
    win.abrir_seccion("voz_texto", "transcribir")
    pump(app, 0.4)
    check(win.voz_texto.clave_de(win.voice.sec1) == "transcribir" and win.voice.sec1.isVisible(),
          "«Transcribir» está en «Voz y texto», como sección plegable")
    win.grab().save(os.path.join(out, "1_voz_y_texto_transcribir.png"))

    # ---- Comparación y Recortar sujeto: menú rápido y clic derecho del clip
    from editoria.core import media as MT
    vid = os.path.join(out, "clip.mp4")
    subprocess.run([MT.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30",
                    "-t", "4", "-pix_fmt", "yuv420p", vid], check=True)
    win.ctrl.set_project_format("short")
    (mid,) = win.ctrl.import_now([vid])
    (cid,) = [i for i in win.ctrl.add_media([mid], None, 0.0) if win.ctrl.project.clips[i].media_id == mid]
    pump(app, 0.4)
    win.timeline.set_selection([cid])
    pump(app, 0.5)
    mr = win.menu_rapido
    check(mr.isVisible() and mr.botones["comparacion"].isVisibleTo(mr) and mr.botones["sujeto"].isVisibleTo(mr),
          "el menú rápido del clip lleva «Comparación» y «Recortar sujeto»")
    h = win.herramientas
    pila = h.panel.pila.geometry()
    arriba = h.panel.mapTo(win.preview.canvas.viewport(), pila.topLeft()).y()
    check(h.clip_delante() and h._pestana_clip.isVisible() and abs(mr.geometry().top() - arriba) <= 2,
          "aunque no haya otra herramienta, va dentro del panel con su pestaña «Clip», pegado arriba")
    win.grab().save(os.path.join(out, "2_menu_rapido.png"))
    menu = win.timeline.build_clip_menu(win.ctrl.project.clips[cid], QPoint(10, 10))

    def textos(m):
        out_ = []
        for a in m.actions():
            out_.append(a.text())
            if a.menu() is not None:
                out_ += textos(a.menu())
        return out_
    todos = textos(menu)
    check(any(t.startswith("Comparación") for t in todos) and any(t.startswith("Recortar sujeto") for t in todos),
          "y el clic derecho del clip también")
    mr.botones["comparacion"].click()
    pump(app, 0.4)
    check(win.herramientas.abierta("comparar"), "«Comparación» se abre en el panel de herramientas")
    win.herramientas.cerrar("comparar")
    win.timeline.set_selection([])
    pump(app, 0.3)

    # ---- Más herramientas, al final de «Edita desde tu voz»
    ev = win.edita_voz
    ev.abrir(1)
    pump(app, 0.3)
    sec = ev.panel.mas_herramientas
    check(not sec.cuerpo.isVisible() and sec.cab.isVisible(), "«Más herramientas»: plegada de entrada")
    sec.cab.click()
    pump(app, 0.3)
    claves = list(sec.botones)
    check(sec.cuerpo.isVisible() and {"voz", "broll", "audio", "director", "temas"} <= set(claves)
          and all(b.text() and b.toolTip() for b in sec.botones.values()),
          f"abierta: sus herramientas con nombre y tooltip ({claves})")
    win.grab().save(os.path.join(out, "3_mas_herramientas.png"))
    sec.botones["temas"].click()
    pump(app, 0.4)
    caja = win.herramientas.widget("ia_temas")
    check(win.herramientas.abierta("ia_temas") and caja is not None
          and caja.isAncestorOf(win.ai_panel._groups["topics"]),
          "«Temas» abre su bloque de siempre (el mismo, no una copia) como pestaña de herramientas")
    sec.botones["broll"].click()
    pump(app, 0.4)
    check(win.herramientas.abierta("ia_broll") and win.herramientas.widget("ia_broll").isAncestorOf(
        win.ai_panel.btn_propose), "«B-roll» igual, con su «Proponer B-roll»")
    sec.botones["voz"].click()
    pump(app, 0.4)
    check(win.audio_panel.clave_de(win.voice) == "limpieza" and win.voice.isVisible(),
          "«Voz y limpieza automática» abre su sitio (Limpieza y mezcla → Limpieza)")
    win.grab().save(os.path.join(out, "4_temas_y_broll.png"))
    print("TODO BIEN")


if __name__ == "__main__":
    main()
