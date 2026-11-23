"""
🗣 Voz IA (texto → voz con Kokoro, sin sonido):
  · troceo por frases y párrafos, números y abreviaturas, diccionario de pronunciación (solo cambia lo que se LEE);
  · «✓ Crear narración» con la voz de entrada (🎙 Narrador de documental): WAV (mono, 16 bits, 24 kHz) con su duración, en Medios (Narración, 🗣 Voz IA), en la
    pista de voz en el cabezal, con su transcripción YA hecha (texto exacto, tiempos crecientes dentro de la duración,
    una frase por segmento); los subtítulos salen de ella;
  · Vertical con «💬 Subtítulos auto»: los subtítulos se ponen solos con la narración IA (sin Whisper);
  · otra vez con «♻ Reemplazar»: la nueva va en el sitio de la anterior, los subtítulos pasan a la nueva, un Ctrl+Z;
  · cancelar a mitad: ni archivos ni medios nuevos;  ▶ Muestra: solo la primera frase (no suena en pruebas);
  · sin el modelo: aviso claro y botones apagados;  accesos «🗣 Que lo lea la IA» (barra de Vertical y 🎙 Transcribir).
Ejecutar:  .venv/Scripts/python.exe tests/test_voz_ia.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from editoria.ai import tts  # noqa: E402

GUION = ("Hola, esto es una prueba de Reclaimer. ¿Se oye bien la voz?\n\n"
         "Ahora vienen los subtítulos, uno por uno.")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def esperar(app, panel, tope=180.0):
    t0 = time.time()
    while panel.job is not None:
        app.processEvents()
        time.sleep(0.02)
        assert time.time() - t0 < tope, "la voz IA tardó demasiado"
    pump(app, 0.1)


def wav_info(ruta):
    with wave.open(ruta, "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes() / w.getframerate()


def comprobar_transcripcion(tr, texto, dur):
    words = tr["words"]
    assert [w[2] for w in words] == texto.split(), "el texto de la transcripción es EXACTAMENTE el pegado"
    prev = 0.0
    for w in words:
        assert prev - 1e-6 <= w[0] <= w[1] <= dur + 1e-3, (w, prev, dur)
        prev = w[1]
    assert words[-1][1] > dur - 0.5, "la última palabra acaba con la narración"
    segs = tr["segments"]
    assert len(segs) == len(tts.frases(texto)) and segs[0][2] == 0 and segs[-1][3] == len(words), segs
    assert tr.get("estimada") and not tr.get("aligned") and tr.get("voz_ia") and tr.get("hasta") is None


def main():
    app = QApplication.instance() or QApplication([])
    ok, why = tts.available()
    assert ok, why

    # ---- texto: frases, números, diccionario
    fr = tts.frases("El Sr. García llegó. Dijo que sí, etc. y se fue.\nLínea sin punto\nque sigue aquí.\n\nOtro párrafo.")
    assert [f["texto"] for f in fr] == ["El Sr. García llegó.", "Dijo que sí, etc. y se fue.",
                                        "Línea sin punto que sigue aquí.", "Otro párrafo."], fr
    assert [f["fin_parrafo"] for f in fr] == [False, False, True, True]
    assert tts.dicho("1.500") == "mil quinientos" and tts.dicho("25€") == "veinticinco euros", tts.dicho("25€")
    assert tts.dicho("2026") == "dos mil veintiséis" and tts.dicho("3,5") == "tres coma cinco"
    tts.añadir_al_diccionario("Reclaimer", "riclé imer")
    assert tts.aplicar_diccionario("Hola reclaimer.") == "Hola riclé imer."
    n, seg = tts.contar(GUION, 1.1, 0.25, 0.6)
    assert n == len(GUION.split()) and 3.0 < seg < 12.0, (n, seg)
    md = tts.frases("# Mi título\nHola 👋 amigos, mirad **esto** https://ejemplo.com/x y #tema 😀.\n- Un punto\n"
                    "- Otro punto.")
    assert [f["texto"] for f in md] == ["Mi título.", "Hola amigos, mirad esto y tema.", "Un punto.", "Otro punto."], md
    print("✓ frases (sin partir «Sr.», «etc.»), números en letras, diccionario y contador; Markdown, enlaces y emojis "
          "fuera también de lo que se escribe")

    # ---- ⬇ descarga del modelo: servidor local con archivos falsos (nunca se bajan los 350 MB de verdad)
    import hashlib
    import http.server
    import threading
    servido = os.path.join(_TMP, "servidor")
    os.makedirs(servido, exist_ok=True)
    falsos = {"kokoro-v1.0.onnx": os.urandom(3 * 1024 * 1024 + 17), "voices-v1.0.bin": os.urandom(4096)}
    for n_, b_ in falsos.items():
        with open(os.path.join(servido, n_), "wb") as f:
            f.write(b_)

    class _H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=servido, **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.handle_error = lambda *a: None                # (la conexión cortada al cancelar no es un error)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    archivos_reales = dict(tts.ARCHIVOS)
    tts.ARCHIVOS.clear()
    tts.ARCHIVOS.update({n_: (len(b_), hashlib.sha256(b_).hexdigest()) for n_, b_ in falsos.items()})
    destino_dl = os.path.join(_TMP, "kokoro_descargado")
    os.environ["RECLAIMER_KOKORO"] = destino_dl
    os.environ["RECLAIMER_KOKORO_URL"] = url
    try:
        assert tts.falta_modelo() and "Descargar esta voz" in tts.available()[1]
        llamadas = []
        try:                                          # cancelar a mitad: sin .part ni archivo a medias
            tts.descargar(cancelled=lambda: (llamadas.append(1), len(llamadas) > 2)[1])
            raise AssertionError("tenía que cancelarse")
        except tts.Cancelled:
            pass
        assert not os.listdir(destino_dl), os.listdir(destino_dl)
        try:                                          # 404: aviso claro y nada a medias
            tts.descargar(url_base=url + "no_existe/")
            raise AssertionError("tenía que fallar")
        except RuntimeError as exc:
            assert "No se pudo descargar" in str(exc), exc
        assert not os.listdir(destino_dl)
        bueno = tts.ARCHIVOS["voices-v1.0.bin"]       # huella que no coincide: se rechaza
        tts.ARCHIVOS["voices-v1.0.bin"] = (bueno[0], "0" * 64)
        try:
            tts.descargar()
            raise AssertionError("tenía que rechazar la huella")
        except RuntimeError as exc:
            assert "SHA-256" in str(exc), exc
        assert not any(x.endswith(".part") or x == "voices-v1.0.bin" for x in os.listdir(destino_dl))
        tts.ARCHIVOS["voices-v1.0.bin"] = bueno
        tts.descargar()
        assert sorted(os.listdir(destino_dl)) == sorted(falsos) and not tts.falta_modelo()
        for n_, b_ in falsos.items():
            with open(os.path.join(destino_dl, n_), "rb") as f:
                assert f.read() == b_
        print("✓ ⬇ descarga (servidor local): .part y renombrar; cancelar, 404 y huella mala no dejan nada")
    finally:
        tts.ARCHIVOS.clear()
        tts.ARCHIVOS.update(archivos_reales)
        os.environ.pop("RECLAIMER_KOKORO", None)

    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").remove("voz_ia/voz")    # (la voz de entrada; _ajustes devuelve la tuya al final)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ctrl = win.ctrl
        panel = win.voz_ia
        carpeta = os.path.join(_TMP, "Grabaciones de voz")
        os.makedirs(carpeta, exist_ok=True)
        panel.carpeta = lambda: carpeta
        assert "voz_ia" in win.docks and "voz_ia" in win.ICONO_PANEL
        ventana = next(a.menu() for a in win.menuBar().actions() if a.text() == "&Ventana")
        # (agrupación 20–22/11: Voz IA es la sección 4 de «Voz y texto»; el menú Ventana abre ese panel)
        assert win.docks["voz_texto"].toggleViewAction() in ventana.actions(), "«Voz y texto» en el menú Ventana"
        win.open_voz_ia()
        pump(app, 0.3)
        assert win.docks["voz_texto"].isVisible() and win.voz_texto.abierta() == "voz_ia", "abre su sección"
        assert panel.voz.currentData() == tts.VOZ_DEFECTO == "narrador_documental", "el narrador de documental por defecto"
        assert getattr(win, "_btn_voz_ia_tr", None) is not None, "acceso en 🎙 Transcribir"

        # ---- 🎬 Video horizontal: narración en el cabezal + transcripción + subtítulos
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        panel.afinar.setChecked(False)
        panel.velocidad.setValue(1.1)
        panel.texto.setPlainText(GUION)
        win.engine.seek(1.5)
        pump(app, 0.1)
        t_cab = win.engine.time
        p = ctrl.project
        n_media = len(p.media)
        t0 = time.time()
        panel.crear(modo="nueva")
        esperar(app, panel)
        u = panel.ultimo
        assert u, panel.status.text()
        print(f"  (narración en {time.time() - t0:.1f} s: {u['duracion']:.1f} s de audio)")
        ch, sw, sr, dur = wav_info(u["ruta"])
        assert (ch, sw, sr) == (1, 2, 24000) and abs(dur - u["duracion"]) < 0.01 and 3.0 < dur < 15.0, (ch, sw, sr, dur)
        assert os.path.dirname(u["ruta"]) == carpeta and os.path.basename(u["ruta"]).startswith("Narración IA")
        mid = u["media_id"]
        m = p.media[mid]
        assert len(p.media) == n_media + 1 and m.category == "Narración" and tts.ETIQUETA in m.tags
        c = p.clips[u["clips"][0]]
        tr_ = p.track(c.track_id)
        assert tr_.kind == "audio" and abs(c.start - t_cab) < 0.02 and abs(c.duration - dur) < 0.1, \
            (c.start, t_cab, c.duration, dur)
        assert tr_.role == "voz" or tr_ is next(t for t in p.tracks if t.kind == "audio"), "en la pista de voz"
        tr = p.transcripts[mid]
        comprobar_transcripcion(tr, GUION, dur)
        # (nada de afinarla sola ni de aprender «tu voz» con la sintética)
        afinadas = []
        win._start_align = lambda mid_: afinadas.append(mid_)
        win._maybe_align(mid)
        from editoria.ai import voice_model as VM
        apuntadas = []
        _q = VM.queue_example
        VM.queue_example = lambda *a, **k: apuntadas.append(a)
        try:
            win.learn_voice(mid, tr["words"])
        finally:
            VM.queue_example = _q
        assert not apuntadas, "una narración de la Voz IA no enseña «tu voz»"
        from PySide6.QtWidgets import QMessageBox
        preguntas = []
        _qq = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: (preguntas.append(a), QMessageBox.No)[1])
        try:
            win.voice.transcribe()
            win.voice.btn_transcribe.click()
        finally:
            QMessageBox.question = _qq
        assert len(preguntas) == 2 and "transcripción EXACTA" in preguntas[0][2] and win.voice.job is None, preguntas
        assert p.transcripts[mid] is tr or p.transcripts[mid] == tr
        assert win.voice.media_id() == mid, "elegida como narración (Transcribir, Limpieza, Texto)"
        assert p.subtitles.media_id == mid, "los subtítulos salen de ella"
        ctrl.undo_stack.undo()
        assert u["clips"][0] not in ctrl.project.clips, "un Ctrl+Z quita la narración"
        ctrl.undo_stack.redo()
        assert u["clips"][0] in ctrl.project.clips
        win.subtitles.quick_short()
        pump(app, 0.2)
        from editoria.core.subtitles import styled_cues
        st = ctrl.project.subtitles
        assert st.enabled and st.media_id == mid
        cues = styled_cues(ctrl.project)
        texto_cues = " ".join(w.text for cue in cues for w in cue.words)
        import re

        def bare(xs):
            return [re.sub(r"[^\w]", "", x).lower() for x in xs]
        assert cues and bare(w.text for cue in cues for w in cue.words) == bare(GUION.split()), texto_cues
        assert cues[0].start >= t_cab - 0.01 and cues[-1].end <= t_cab + dur + 0.3, (cues[0].start, cues[-1].end, t_cab, dur)
        assert all(a.start <= b.start for a, b in zip(cues, cues[1:]))
        print(f"✓ narración con el narrador de documental ({dur:.1f} s) en Medios y en la pista de voz en el cabezal, ya transcrita "
              f"({len(tr['words'])} palabras, texto exacto); subtítulos: {len(cues)} bloques sin Whisper")

        # diccionario: se LEE distinto, el texto no cambia
        res = tts.sintetizar("Esto es Reclaimer.", destino=os.path.join(_TMP, "dic.wav"))
        assert "riclé imer" in res["frases"][0]["leido"] and res["transcripcion"]["words"][-1][2] == "Reclaimer."
        os.remove(os.path.join(_TMP, "dic.wav"))
        print("✓ diccionario aplicado a lo que se lee (los subtítulos siguen con lo escrito)")

        # ---- 📱 Vertical con «💬 Subtítulos auto»: se ponen solos con la narración IA
        for k_ in win.TAB_MANAGED:          # (lo de fábrica de la pestaña, no lo que dejaste tú en la tuya)
            QSettings("EditorIA", "EditorIA").remove(f"paneles_pestana/short/{k_}")
        win.workspaces.switch("short")
        pump(app, 0.4)
        # (Voz IA vive en «Voz y texto»: en Vertical ese panel está puesto y su acceso, en la barra de Vertical)
        assert win.docks["voz_texto"].toggleViewAction().isChecked(), "en Vertical, «Voz y texto» está puesto"
        textos = [b.property("texto_completo") or b.text()                # (en estrecho, solo su icono)
                  for b in win.preview.shorts_bar.findChildren(QPushButton)]
        assert "🗣 Que lo lea la IA" in textos, textos
        win.btn_subs_auto.setChecked(True)
        p = ctrl.project
        assert p.format == "short" and not p.transcripts
        panel.texto.setPlainText("Primera frase del vertical. Segunda frase, más corta.")
        win.engine.seek(0.0)
        panel.crear()                       # (sin narración IA en la línea: no pregunta, va en el cabezal)
        esperar(app, panel)
        pump(app, 1.0)                      # (Subtítulos auto se lanza a los 0,4 s)
        mid1, clip1 = panel.ultimo["media_id"], panel.ultimo["clips"][0]
        st = ctrl.project.subtitles
        assert st.enabled and st.media_id == mid1, (st.enabled, st.media_id, mid1)
        assert win.voice.job is None, "sin Whisper"
        print("✓ Vertical: «💬 Subtítulos auto» los pone solos con la narración IA (sin transcribir)")

        # ---- ♻ reemplazar la narración anterior
        preguntado = []
        panel._preguntar_modo = lambda: (preguntado.append(1), "reemplazar")[1]
        start1 = ctrl.project.clips[clip1].start
        win.engine.seek(3.0)
        panel.texto.setPlainText("Una versión nueva y distinta del guion.")
        n_pasos = ctrl.undo_stack.count()
        panel.crear()
        esperar(app, panel)
        assert preguntado, "con narración IA en la línea de tiempo, pregunta"
        mid2, clip2 = panel.ultimo["media_id"], panel.ultimo["clips"][0]
        p = ctrl.project
        assert clip1 not in p.clips and abs(p.clips[clip2].start - start1) < 0.01, "en el sitio de la anterior"
        assert mid1 in p.media, "la anterior sigue en Medios"
        assert p.subtitles.media_id == mid2, "los subtítulos pasan a la nueva"
        assert ctrl.undo_stack.count() == n_pasos + 1, (n_pasos, ctrl.undo_stack.count())
        ctrl.undo_stack.undo()
        p = ctrl.project
        assert clip1 in p.clips and clip2 not in p.clips and p.subtitles.media_id == mid1, "un Ctrl+Z lo deshace todo"
        ctrl.undo_stack.redo()
        print("✓ «♻ Reemplazar»: la nueva en el sitio de la anterior, subtítulos de la nueva, un solo Ctrl+Z")

        # ---- cancelar a mitad: nada en disco ni en Medios
        antes = set(os.listdir(carpeta))
        n_media = len(ctrl.project.media)
        panel.texto.setPlainText(" ".join(f"Esta es la frase número {i} de una prueba larga para cancelar."
                                          for i in range(1, 40)))
        panel.crear(modo="nueva")
        t0 = time.time()
        while panel.job is not None and "frase 3 de" not in panel.status.text():
            app.processEvents()
            time.sleep(0.02)
            assert time.time() - t0 < 120
        panel.cancelar()
        esperar(app, panel)
        assert set(os.listdir(carpeta)) == antes, set(os.listdir(carpeta)) ^ antes
        assert len(ctrl.project.media) == n_media and "Cancelado" in panel.status.text(), panel.status.text()
        print("✓ cancelar a mitad: ningún archivo (ni temporal) ni medio nuevo")

        # ---- ▶ muestra: solo la primera frase, sin sonar
        panel.texto.setPlainText("Solo esta frase. Esta otra no se lee en la muestra.")
        panel.muestra()
        esperar(app, panel)
        ruta = panel._muestra_ruta
        assert ruta and os.path.isfile(ruta) and wav_info(ruta)[3] < 3.0, ruta
        assert panel._player is None, "en las pruebas no se reproduce nada"
        print("✓ ▶ Muestra: solo la primera frase y sin sonido en las pruebas")

        pump(app, 3.3)
        assert not afinadas, "la transcripción de la Voz IA no se afina sola"
        print("✓ ni se afina sola ni enseña «tu voz»; 🎙 Transcribir pregunta antes de pisar su texto exacto")

        # ---- 📝 el borrador va a datos/voz_ia/borrador.txt (no al registro)
        from PySide6.QtCore import QSettings
        panel.texto.setPlainText("Borrador de prueba.")
        pump(app, 0.6)
        assert tts.leer_borrador() == "Borrador de prueba." and not QSettings("EditorIA", "EditorIA").contains(
            "voz_ia/texto")
        print("✓ el borrador se guarda en datos/voz_ia/borrador.txt")

        # ---- ⬇ desde el panel: botón a la vista cuando falta el modelo
        tts.ARCHIVOS.clear()
        tts.ARCHIVOS.update({n_: (len(b_), hashlib.sha256(b_).hexdigest()) for n_, b_ in falsos.items()})
        otro = os.path.join(_TMP, "kokoro_panel")
        os.environ["RECLAIMER_KOKORO"] = otro
        try:
            assert not panel._comprobar() and not panel.b_descargar.isHidden() and not panel.b_crear.isEnabled()
            assert "Descargar esta voz" in panel.aviso.text() and "≈350 MB" in panel.b_descargar.text()
            panel.b_descargar.click()
            esperar(app, panel)
            assert sorted(os.listdir(otro)) == sorted(falsos), os.listdir(otro)
            assert panel.b_descargar.isHidden() and panel.b_crear.isEnabled() and "descargada" in panel.status.text()
        finally:
            tts.ARCHIVOS.clear()
            tts.ARCHIVOS.update(archivos_reales)
            os.environ.pop("RECLAIMER_KOKORO", None)
            os.environ.pop("RECLAIMER_KOKORO_URL", None)
            srv.shutdown()
        print("✓ «⬇ Descargar esta voz» a la vista sin el modelo; al bajarlo, el panel queda listo")

        # ---- sin el modelo: aviso y nada se rompe
        vacio = os.path.join(_TMP, "sin_modelo")
        os.makedirs(vacio, exist_ok=True)
        os.environ["RECLAIMER_KOKORO"] = vacio
        try:
            assert not panel._comprobar()
            assert not panel.aviso.isHidden()
            assert "Falta esta voz" in panel.aviso.text() and not panel.b_crear.isEnabled()
            assert not panel.b_descargar.isHidden(), "en el aviso, el botón de descargar"
            n_media = len(ctrl.project.media)
            panel.crear(modo="nueva")
            assert panel.job is None and len(ctrl.project.media) == n_media
        finally:
            del os.environ["RECLAIMER_KOKORO"]
        assert panel._comprobar() and panel.b_crear.isEnabled()
        print("✓ sin el modelo: aviso en español, botones apagados y nada se rompe")

        # ---- 🗣 voz CC BY (sharvard): sus créditos junto al WAV y en la descripción, en «🗣 Voz:»
        from editoria.core import credits as CR
        panel.voz.setCurrentIndex(panel.voz.findData("narrador_solemne"))
        panel.texto.setPlainText("Una frase con la voz solemne.")
        panel.crear(modo="nueva")
        esperar(app, panel)
        u = panel.ultimo
        assert u and os.path.basename(u["ruta"]).endswith("(Narrador solemne).wav"), panel.status.text()
        assert os.path.isfile(tts.ruta_creditos(u["ruta"])), "créditos junto al WAV"
        cr_txt = CR.text(CR.collect(ctrl.project))
        assert "🗣 Voz:\n• Voz sintética: Piper, voz sharvard (Sharvard Corpus, CC BY 3.0)" in cr_txt, cr_txt
        assert "Clips usados" not in cr_txt.split("🗣 Voz:")[1]
        panel.voz.setCurrentIndex(panel.voz.findData(tts.VOZ_DEFECTO))
        print("✓ voz CC BY: «.creditos.json» junto a la narración y apartado «🗣 Voz:» en los créditos del video")

        # ---- acceso desde la barra de Vertical
        win.docks["voz_texto"].hide()
        next(b for b in win.preview.shorts_bar.findChildren(QPushButton) if (b.property("texto_completo") or b.text()) == "🗣 Que lo lea la IA").click()
        pump(app, 0.2)
        assert win.docks["voz_texto"].isVisible() and win.voz_texto.abierta() == "voz_ia",             "«🗣 Que lo lea la IA» abre su panel"
        print("✓ «🗣 Que lo lea la IA» abre el panel")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.3)
    print("✓ TODO OK")


if __name__ == "__main__":
    main()
