"""
📍 La guía, paso a paso: TODOS los pasos de TODAS las lecciones. En cada uno, «📍 Muéstrame» tiene que encontrar su
opción y dejarla A LA VISTA (abriendo su interruptor, su sección del acordeón «Voz y texto» / «Audio», su pestaña…),
sin caer en el aviso «Selecciona un clip…» cuando no hace falta un clip. Con un clip elegido (para las opciones del
Inspector), ningún paso puede acabar sin su opción visible. Y ningún texto de la guía habla de páginas que ya no están.
Ejecutar:  .venv/Scripts/python.exe tests/test_guia_pasos.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_guia_", dir=_TMPROOT)
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

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

# páginas y sitios que ya no existen (agrupación del 20/11): ningún texto de la guía ni de la ayuda puede mandarte ahí
VIEJOS = ("página «✦ Efectos»", "La página <b>«✦ Efectos»", "página <b>🎚 Audio", "«🎚 Audio»</b> (barra de abajo)",
          "«📝 Transcripción»</b>, a su lado", "página <b>«📝 Transcripción»", "«⬆ Exportar»",
          "IA ✨ → 🎙 Transcribir", "elígela en 📝 Transcripción")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_guia_pasos")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui import guide as G
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    textos = " ".join(t for _l, _t, _w, pasos in G.LESSONS for t, _o, _d in pasos)
    from editoria.ui import help as AYUDA
    fuente_ayuda = open(AYUDA.__file__, encoding="utf-8").read()
    textos_malos = [f"guía: {v}" for v in VIEJOS if v in textos] + [f"ayuda: {v}" for v in VIEJOS if v in fuente_ayuda]

    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    win._show_shortcuts = lambda: None                     # (sin ventanas modales)
    pump(app, 0.8)
    ctrl = win.ctrl
    try:
        # un clip elegido: las opciones del Inspector se ven
        video = os.path.join(out, "fuente.mp4")
        if not os.path.exists(video):
            subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-shortest", video], check=True)
        (mid,) = ctrl.import_now([video])
        v1 = next(tr for tr in ctrl.project.tracks if tr.kind == TRACK_VIDEO)
        cid = next(c for c in ctrl.add_media([mid], v1.id, 0.0) if ctrl.project.clips[c].track_id == v1.id)
        # (22/11) una narración PEQUEÑA con su transcripción (tests/assets/narracion_prueba.*), una sugerencia de la IA y
        # un momento encontrado: así existen los controles que solo salen con algo dentro («Cortar lo tachado», el
        # resumen, «Aplicar» de Limpieza, la rejilla de Momentos) en vez de aceptar sus avisos de estado vacío
        import json
        from PySide6.QtWidgets import QListWidgetItem
        from editoria.core.model import TRACK_AUDIO
        assets = os.path.join(_RAIZ, "tests", "assets")
        wav = os.path.join(out, "narracion_prueba.wav")
        shutil.copy(os.path.join(assets, "narracion_prueba.wav"), wav)
        (nar,) = ctrl.import_now([wav])
        a1 = next(tr for tr in ctrl.project.tracks if tr.kind == TRACK_AUDIO)
        ctrl.add_media([nar], a1.id, 0.0)
        with open(os.path.join(assets, "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
            ctrl.set_transcript(nar, json.load(f))
        ctrl.set_suggestions(nar, [{"kind": "silence", "start": 3.8, "end": 6.9, "label": "Silencio"}], {"silence"},
                             {"silence": True})
        pump(app, 0.3)
        win.voice._refresh_media()
        i_nar = win.voice.media_combo.findData(nar)
        if i_nar >= 0:
            win.voice.media_combo.setCurrentIndex(i_nar)      # (Limpieza y Transcripción, con esa narración)
        win.transcript.set_media(nar)
        win.moments.grid.addItem(QListWidgetItem("Momento de prueba"))
        win.timeline.set_selection([cid])
        pump(app, 0.8)

        win.open_guide()
        pump(app, 0.3)
        g = win.guide
        g.auto.setChecked(False)
        fallos, total = [], 0
        for lid, titulo, _w, pasos in G.LESSONS:
            g.open_lesson(lid)
            for i in range(len(pasos)):
                g.go(i)
                g.show_target()
                pump(app, 0.6 if lid == "miniatura" else 0.2)
                target, do = g.current()
                total += 1
                obj = g.resolve(target)
                if obj is None:
                    fallos.append(f"{titulo} · {i + 1}: no encuentro «{target}»")
                    continue
                if g.image.text().startswith("👉"):
                    fallos.append(f"{titulo} · {i + 1}: «{target}» → aviso «{g.image.text()[:50]}…»")
                    continue
                if isinstance(obj, QWidget):
                    if not obj.isVisible():
                        fallos.append(f"{titulo} · {i + 1}: «{target}» no se ve")
                        continue
                    from PySide6.QtCore import QPoint, QRect
                    r = QRect(obj.mapTo(obj.window(), QPoint(0, 0)), obj.size())
                    if r.width() < 4 or r.height() < 4 or not obj.window().rect().intersects(r):
                        fallos.append(f"{titulo} · {i + 1}: «{target}» fuera de la ventana ({r})")
                        continue
        for f in fallos + textos_malos:
            print("  ✗", f)
        assert not textos_malos, f"textos que hablan de sitios quitados: {textos_malos}"
        print("✓ ni la guía ni la ayuda hablan de páginas o botones quitados")
        assert not fallos, f"{len(fallos)} de {total} pasos no enseñan su opción"
        print(f"✓ los {total} pasos de la guía enseñan su opción (a la vista, sin avisos falsos)")

        # el aviso suave (nudge) usa el mismo reveal: una opción dentro del acordeón también se abre
        from editoria.ui.nudge import reveal_tab
        win.audio_panel.abrir("mezcla")
        win.voz_texto.abrir("voz_ia")
        pump(app, 0.2)
        reveal_tab(win.voice.btn_auto_clean)
        pump(app, 0.3)
        assert win.audio_panel.abierta() == "limpieza", win.audio_panel.abierta()
        reveal_tab(win.subtitles.enabled)
        pump(app, 0.3)
        assert win.voz_texto.abierta() == "subtitulos", win.voz_texto.abierta()
        print("✓ el aviso suave también abre la sección del acordeón donde está la opción")

        # «📝 Cambiar» (Audio → Limpieza) lleva a «Voz y texto → 1 · Transcribir» sin tocar las pestañas de IA ✨
        win.voz_texto.abrir("voz_ia")
        ia = win.ai_panel.tabs
        ia.setCurrentIndex(ia.count() - 1)
        antes = ia.currentIndex()
        win.voice._ir_a_narracion()
        pump(app, 0.2)
        assert win.voz_texto.abierta() == "transcribir", win.voz_texto.abierta()
        assert ia.currentIndex() == antes, "no cambia la pestaña de IA ✨"
        assert win.docks["voz_texto"].isVisible()
        print("✓ «📝 Cambiar» abre «Voz y texto → 1 · Transcribir» (y deja IA ✨ como estaba)")

        # abajo siempre queda marcada una página: lo que no tiene botón propio se hace en «Editar»
        for k in ("guided", "media"):
            win.go_page(k)
            pump(app, 0.2)
            marcados = [n for n, b in win.page_buttons.items() if b.isChecked()]
            assert marcados == ["edit"], (k, marcados)
        print("✓ tras «🧭 Montaje guiado» o Medios, abajo queda marcada «Editar»")
    finally:
        g = getattr(win, "guide", None)
        if g is not None:
            g.clear()
        ed = getattr(win, "_thumb_editor", None)
        if ed:
            ed.close()
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.3)
        # (el taller de miniaturas busca solo «los mejores fotogramas» con la IA al abrirse —lección Miniatura— y,
        #  mientras carga su modelo, no puede parar: Python se cerraba con ese hilo vivo → 0xC0000409 / 127. En el
        #  programa de verdad no pasa: al salir, app.run() ve que no paró a tiempo y sale con os._exit. Aquí se le
        #  pide parar y se espera a que acabe, hasta 60 s)
        from editoria.ui.jobs import live_jobs
        from editoria.ui.task_window import stop_all
        stop_all(4000)
        t_fin = time.time() + 60
        while time.time() < t_fin and any(j.isRunning() for j in live_jobs()):
            pump(app, 0.1)
    print("TODO OK")


if __name__ == "__main__":
    main()
