"""
🎙 Voces de narración (catálogo de «🗣 Voz IA», sin sonido):
  · cada voz del catálogo (Kokoro, mezclas de estilo, Piper; con tono, ritmo y ecualización) genera audio: duración
    > 0, sin NaN, 24 kHz; la transcripción exacta sale con el texto pegado y tiempos crecientes dentro de la duración;
  · todas igual de fuertes: −18 LUFS (±0,5), picos ≤ −1 dBFS, RMS de los tramos con voz a ±1,5 dB entre voces;
  · el tono cambia de verdad (más grave) y sin rubberband (asetrate+atempo) los tiempos se reescalan a la duración;
  · falta el modelo de una voz Piper: aviso y «⬇ Descargar esta voz (N MB)» (servidor local con archivos falsos);
  · el desplegable va agrupado (🎙 Narración / Kokoro / Piper; los títulos no se eligen), con su descripción y la
    atribución en el tooltip; la voz elegida se recuerda;
  · crear_muestras: un WAV por voz con nombre claro + LEEME.txt con las licencias (y botón «🎧 Muestras de todas las
    voces» en segundo plano); en memoria solo el último Piper;
  · rubberband que falla → asetrate; sin FFmpeg: Alex/Santa/Dora/Piper tal cual funcionan (volumen por RMS) y las de
    tono avisan antes de leer;  atribución CC BY: «.creditos.json» y apartado «🗣 Voz:» en credits.text.
Ejecutar:  .venv/Scripts/python.exe tests/test_voces_narrador.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import types
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_voces_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import tts  # noqa: E402

TEXTO = "En el invierno de aquel año, el país despertó en silencio. Nadie lo imaginaba."


def leer_wav(ruta):
    with wave.open(ruta, "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768.0


def comprobar(res, texto):
    a = leer_wav(res["ruta"])
    dur = len(a) / 24000
    assert dur > 1.0 and abs(dur - res["duracion"]) < 0.01 and np.isfinite(a).all() and np.abs(a).max() > 0.5, dur
    tr = res["transcripcion"]
    words = tr["words"]
    assert [w[2] for w in words] == texto.split(), "texto EXACTO"
    prev = 0.0
    for w in words:
        assert prev - 1e-6 <= w[0] <= w[1] <= dur + 1e-3, (w, prev, dur)
        prev = w[1]
    assert words[-1][1] > dur - 0.6, (words[-1], dur)
    segs = tr["segments"]
    assert len(segs) == len(tts.frases(texto)) and segs[-1][3] == len(words)
    assert all(0 <= s[0] <= s[1] <= dur + 1e-3 for s in segs)
    for f in res["frases"]:
        assert 0 <= f["inicio"] < f["fin"] <= dur + 1e-3, f
    return a, dur


def f0(a, sr=24000):
    """Tono medio aproximado (autocorrelación en los tramos con voz)."""
    hop, n, out = int(sr * 0.02), int(sr * 0.04), []
    for i in range(0, len(a) - n, hop):
        x = a[i:i + n] - a[i:i + n].mean()
        if np.sqrt((x ** 2).mean()) < 0.03:
            continue
        c = np.correlate(x, x, "full")[n - 1:]
        lo, hi = int(sr / 400), int(sr / 60)
        k = lo + int(np.argmax(c[lo:hi]))
        if c[k] > 0.4 * c[0]:
            out.append(sr / k)
    return float(np.median(out)) if out else 0.0


def main():
    app = QApplication.instance() or QApplication([])
    salida = os.path.join(_TMP, "voces")
    os.makedirs(salida, exist_ok=True)

    # ---- catálogo: al menos 6 de narración (graves/calmadas) y 1–2 de mujer; las de antes siguen
    narr = [v for v in tts.CATALOGO.values() if v.grupo == "🎙 Narración"]
    assert len(narr) >= 6 and sum("Narradora" in v.nombre for v in narr) >= 1, [v.nombre for v in narr]
    assert all(v.velocidad < 1.0 and v.tono < 0 and v.eq for v in narr), "las de narración: más lentas y graves"
    assert {"em_alex", "em_santa", "ef_dora"} <= set(tts.CATALOGO) and tts.VOZ_DEFECTO in tts.CATALOGO
    assert {v.motor for v in tts.CATALOGO.values()} == {"kokoro", "piper"}
    for v in tts.CATALOGO.values():
        assert v.descripcion and v.licencia and v.archivo and v.grupo in tts.GRUPOS, v
    assert "CC BY 3.0" in tts.tooltip_voz("narrador_solemne") and "Sharvard" in tts.tooltip_voz("narrador_solemne")
    assert tts.nombre_corto("narrador_documental") == "Narrador de documental" and tts.nombre_corto("em_alex") == "Alex"
    print(f"✓ catálogo: {len(tts.CATALOGO)} voces ({len(narr)} de narración), con descripción y licencia")

    # ---- cada voz genera audio y su transcripción exacta (Kokoro, mezcla, Piper; con tono y ecualización)
    tonos, rms_voz = {}, {}
    for clave, v in tts.CATALOGO.items():
        ok, why = tts.available(clave)
        assert ok, f"{clave}: {why}"
        t0 = time.time()
        res = tts.sintetizar(TEXTO, clave, destino=os.path.join(salida, f"{clave}.wav"))
        a, dur = comprobar(res, TEXTO)
        assert res["transcripcion"]["model"] == f"{v.motor}:{clave}"
        tonos[clave] = f0(a)
        rms_voz[clave] = tts._rms_voz_db(a)
        lufs = tts.sonoridad(a)
        assert np.abs(a).max() <= 0.8913 + 1e-4, f"{clave}: pico por encima de −1 dBFS"
        assert lufs is not None and abs(lufs - tts.LUFS_VOZ) <= 0.5, f"{clave}: {lufs} LUFS"
        print(f"  {clave:22s} {v.motor:6s} {dur:5.2f} s  (en {time.time() - t0:4.1f} s)  tono ~{tonos[clave]:.0f} Hz"
              f"  {lufs:.1f} LUFS  voz {rms_voz[clave]:.1f} dB")
    media_rms = float(np.mean(list(rms_voz.values())))
    assert all(abs(x - media_rms) <= 1.5 for x in rms_voz.values()), \
        f"volumen de voz desigual: {rms_voz} (media {media_rms:.1f})"
    assert tonos["cronista_grave"] < tonos["em_santa"] * 0.93, "el cronista es más grave que Santa"
    assert tonos["narrador_documental"] < min(tonos["em_alex"], tonos["em_santa"]) * 0.95
    assert tonos["narradora_clara"] > 160 and tonos["narradora_serena"] > 140, "las narradoras son voz de mujer"
    print("✓ todas las voces generan audio (sin NaN) con transcripción exacta y tiempos crecientes; las de narración "
          f"suenan más graves; todas a {tts.LUFS_VOZ:.0f} LUFS (±0,5), picos ≤ −1 dBFS y RMS de voz a ±1,5 dB "
          f"(rango {max(rms_voz.values()) - min(rms_voz.values()):.1f} dB)")

    # ---- limitador: nunca pasa del techo y fuera de los picos no toca nada
    x = (np.sin(np.arange(24000) / 24000 * 2 * np.pi * 200) * 1.6).astype(np.float32)
    x[:12000] *= 0.25
    y = tts._limitar(x)
    assert np.abs(y).max() <= tts.PICO + 1e-6 and np.allclose(y[:11000], x[:11000]), "limitador"
    y = tts.normalizar_sonoridad(x * 0.01)
    assert abs(tts.sonoridad(y) - tts.LUFS_VOZ) <= 0.5 and np.abs(y).max() <= tts.PICO + 1e-6
    print("✓ limitador de picos (−1 dBFS) sin tocar lo demás; normalizar_sonoridad lleva a −18 LUFS")

    # ---- sin rubberband (asetrate+atempo): la duración cambia un pelín y los tiempos se reescalan
    guardado = tts._rubberband
    tts._rubberband = False
    try:
        assert "asetrate" in tts.cadena_efectos(-2.0, "documental") and "rubberband" not in tts.cadena_efectos(-2.0)
        res = tts.sintetizar(TEXTO, "narrador_calmado", destino=os.path.join(salida, "sin_rubberband.wav"))
        comprobar(res, TEXTO)
    finally:
        tts._rubberband = guardado
    assert tts.cadena_efectos(0.0, "", False) == ""
    print("✓ sin rubberband (asetrate+atempo) los tiempos siguen dentro de la duración")

    # ---- rubberband falla al usarlo: se reintenta solo con asetrate+atempo
    _proc = tts._procesar
    intentos = []

    def proc_falla(audio, cadena):
        intentos.append(cadena)
        if "rubberband" in cadena:
            raise RuntimeError("rubberband roto (simulado)")
        return _proc(audio, cadena)
    tts._procesar = proc_falla
    guardado = tts._rubberband
    tts._rubberband = True
    try:
        res = tts.sintetizar(TEXTO, "cronista_grave", destino=os.path.join(salida, "rb_falla.wav"))
        comprobar(res, TEXTO)
        assert len(intentos) == 2 and "rubberband" in intentos[0] and "asetrate" in intentos[1], intentos
    finally:
        tts._procesar = _proc
        tts._rubberband = guardado
    print("✓ si rubberband falla, se reintenta con asetrate+atempo")

    # ---- sin FFmpeg: Alex/Santa/Dora funcionan (volumen por RMS); las de tono avisan ANTES de leer
    from editoria.core import media
    _ff = media.ffmpeg

    def sin_ffmpeg():
        raise RuntimeError("No se encontró FFmpeg (simulado).")
    media.ffmpeg = sin_ffmpeg
    guardado = tts._rubberband
    tts._rubberband = None
    try:
        assert not tts.tiene_rubberband() and tts.sonoridad(np.ones(24000, np.float32) * 0.1) is None
        for clave in ("em_alex", "em_santa", "ef_dora", "piper_davefx"):
            res = tts.sintetizar(TEXTO, clave, destino=os.path.join(salida, f"sin_ff_{clave}.wav"))
            a, _d = comprobar(res, TEXTO)
            assert abs(tts._rms_voz_db(a) - media_rms) <= 1.5 and np.abs(a).max() <= 0.8913 + 1e-4, \
                (clave, tts._rms_voz_db(a), media_rms)
        pasos = []
        t0 = time.time()
        try:
            tts.sintetizar(TEXTO, "narrador_documental", destino=os.path.join(salida, "no.wav"),
                           progress=lambda f, t: pasos.append(t))
            raise AssertionError("sin FFmpeg, una voz con tono tenía que avisar")
        except RuntimeError as exc:
            assert "FFmpeg" in str(exc) and not any("Leyendo" in p for p in pasos), (exc, pasos)
        assert not os.path.exists(os.path.join(salida, "no.wav")) and time.time() - t0 < 5
    finally:
        media.ffmpeg = _ff
        tts._rubberband = guardado
    print("✓ sin FFmpeg: Alex, Santa, Dora y Piper tal cual funcionan (volumen por RMS, igual de fuerte); las de tono "
          "avisan antes de leer")

    # ---- 🗣 atribución CC BY: créditos junto al WAV y apartado propio «🗣 Voz:» en la descripción
    from editoria.core import credits as CR
    assert tts.creditos_voz("narrador_calmado") is None and tts.creditos_voz("em_alex") is None
    cv = tts.creditos_voz("narradora_clara")
    assert cv and cv["tipo"] == "voz" and "sharvard" in cv["title"] and "CC BY 3.0" in cv["title"] and cv["url"]
    for clave in ("narrador_solemne", "narradora_clara", "piper_sharvard_m", "piper_sharvard_f"):
        assert "pide atribución en la descripción del video" in tts.tooltip_voz(clave), clave
    assert "pide atribución" not in tts.tooltip_voz("narrador_calmado")
    wav_cc = os.path.join(salida, "narrador_solemne.wav")
    ruta_cc = tts.escribir_creditos(wav_cc, "narrador_solemne")
    assert ruta_cc == os.path.join(salida, "narrador_solemne.creditos.json") and os.path.isfile(ruta_cc)
    assert tts.escribir_creditos(os.path.join(salida, "em_alex.wav"), "em_alex") is None
    clip_json = os.path.join(salida, "clip.creditos.json")
    with open(clip_json, "w", encoding="utf-8") as f:
        f.write('{"title": "Un video", "channel": "Un canal", "url": "https://ejemplo.com/v"}')
    proy = types.SimpleNamespace(media={"a": types.SimpleNamespace(path=wav_cc),
                                        "b": types.SimpleNamespace(path=os.path.join(salida, "clip.mp4")),
                                        "c": types.SimpleNamespace(path=os.path.join(salida, "em_alex.wav"))})
    texto_cr = CR.text(CR.collect(proy))
    assert texto_cr.startswith("🎬 Clips usados en este video:\n• «Un video»") and "\n\n🗣 Voz:\n• Voz sintética: Piper, " \
        "voz sharvard (Sharvard Corpus, CC BY 3.0): https://datashare.ed.ac.uk/handle/10283/574" in texto_cr, texto_cr
    assert texto_cr.count("•") == 2, "la voz no va bajo «Clips usados»"
    assert CR.text([cv]) == "🗣 Voz:\n• " + cv["title"] + ": " + cv["url"]
    print("✓ atribución CC BY: «<narración>.creditos.json» y apartado «🗣 Voz:» propio en los créditos; aviso en el "
          "tooltip")

    # ---- contar: con el ritmo de cada motor
    _n, s_ald = tts.contar(TEXTO * 4, 1.0, 0.25, 0.6, "piper_ald")
    _n, s_dav = tts.contar(TEXTO * 4, 1.0, 0.25, 0.6, "piper_davefx")
    assert s_ald > s_dav * 1.1, (s_ald, s_dav)

    # ---- 🎙 con muestra corta (solo la primera frase) y robot encima de una voz Piper
    res = tts.sintetizar(TEXTO, "piper_davefx", robot=True, solo_primera=True,
                         destino=os.path.join(salida, "robot.wav"))
    comprobar(res, tts.frases(TEXTO)[0]["texto"])
    print("✓ Piper + 🤖 toque robótico y solo la primera frase (▶ Muestra)")

    # ---- falta el modelo Piper: aviso, botón «⬇ Descargar esta voz (N MB)» y descarga (servidor local, falsos)
    import hashlib
    import http.server
    import threading
    servido = os.path.join(_TMP, "servidor")
    modelo = "es_MX-ald-medium"
    m = tts.PIPER_MODELOS[modelo]
    falsos = {}
    for local, (remoto, _tam, _sha) in m["archivos"].items():
        b_ = os.urandom(2 * 1024 * 1024 + 5) if local.endswith(".onnx") else b"{}" if local.endswith(".json") else b"x"
        falsos[local] = (remoto, b_)
        ruta = os.path.join(servido, *m["remoto"].strip("/").split("/"), remoto)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(b_)

    class _H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=servido, **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.handle_error = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    reales = dict(m["archivos"])
    m["archivos"] = {local: (remoto, len(b_), hashlib.sha256(b_).hexdigest()) for local, (remoto, b_) in falsos.items()}
    destino = os.path.join(_TMP, "piper_descargado")
    os.environ["RECLAIMER_PIPER"] = destino
    os.environ["RECLAIMER_PIPER_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/"
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("voz_ia/voz", "narrador_latino")
    from editoria.ui.voz_ia_panel import VozIAPanel
    panel = VozIAPanel(types.SimpleNamespace(ctrl=types.SimpleNamespace(path=None, project=None)))
    try:
        assert panel.voz.currentData() == "narrador_latino", "recuerda la voz guardada"
        assert tts.falta_modelo("narrador_latino") and not tts.falta_modelo("narrador_documental")
        assert not tts.available("narrador_latino")[0] and "Descargar esta voz" in tts.available("narrador_latino")[1]
        assert not panel.aviso.isHidden() and "Falta esta voz" in panel.aviso.text()
        assert not panel.b_descargar.isHidden() and not panel.b_crear.isEnabled()
        mb = f"{sum(len(b_) for _r, b_ in falsos.values()) / 1e6:.0f} MB"
        assert panel.b_descargar.text() == f"Descargar esta voz ({mb})", panel.b_descargar.text()
        assert not panel.acento.isEnabled(), "Piper: acento propio"
        panel.b_descargar.click()
        t0 = time.time()
        while panel.job is not None:
            app.processEvents()
            time.sleep(0.02)
            assert time.time() - t0 < 60
        app.processEvents()
        assert sorted(os.listdir(destino)) == sorted(falsos), os.listdir(destino)
        assert not tts.falta_modelo("narrador_latino") and panel.b_descargar.isHidden(), panel.status.text()
        # otra voz Kokoro: ya está, sin aviso ni botón; acento activo
        panel.voz.setCurrentIndex(panel.voz.findData("narradora_serena"))
        assert panel.aviso.isHidden() and panel.b_descargar.isHidden() and panel.acento.isEnabled()
        print(f"✓ falta una voz Piper: aviso y «⬇ Descargar esta voz ({mb})»; al bajarla, lista")

        # ---- desplegable agrupado, tooltip y voz recordada
        cab = [i for i in range(panel.voz.count()) if panel.voz.itemData(i) is None]
        assert [panel.voz.itemText(i) for i in cab] == [f"── {g} ──" for g in tts.GRUPOS], cab
        mod = panel.voz.model()
        assert all(not (mod.item(i).flags() & Qt.ItemIsSelectable) for i in cab), "los títulos no se eligen"
        assert panel.voz.count() == len(tts.CATALOGO) + len(tts.GRUPOS)
        i = panel.voz.findData("narrador_solemne")
        assert "CC BY 3.0" in str(panel.voz.itemData(i, Qt.ToolTipRole))
        panel.voz.setCurrentIndex(i)
        assert "Serio" in panel.voz.toolTip()
        assert QSettings("EditorIA", "EditorIA").value("voz_ia/voz") == "narrador_solemne"
        otro = VozIAPanel(types.SimpleNamespace(ctrl=types.SimpleNamespace(path=None, project=None)))
        assert otro.voz.currentData() == "narrador_solemne", "la última voz elegida se recuerda"
        assert otro.opciones()["voz"] == "narrador_solemne"
        n1, s1 = tts.contar(TEXTO * 3, 1.1, 0.25, 0.6, "em_alex")
        n2, s2 = tts.contar(TEXTO * 3, 1.1, 0.25, 0.6, "narrador_solemne")
        assert n1 == n2 and s2 > s1 * 1.1, (s1, s2)
        otro.deleteLater()
        st.setValue("voz_ia/voz", "no_existe")
        tercero = VozIAPanel(types.SimpleNamespace(ctrl=types.SimpleNamespace(path=None, project=None)))
        assert tercero.voz.currentData() == tts.VOZ_DEFECTO, "una voz guardada que ya no existe → la de entrada"
        tercero.deleteLater()
        print("✓ desplegable agrupado (títulos sin elegir), descripción y atribución en el tooltip; voz recordada; "
              "el contador usa el ritmo de la voz")

        # ---- 🎧 botón «Muestras de todas las voces»: en segundo plano, con progreso y sin abrir nada (offscreen)
        assert not panel.b_muestras.isHidden() and panel.b_muestras.isEnabled()
        _cm = tts.crear_muestras
        tts.crear_muestras = lambda d, progress=None, cancelled=None: _cm(
            d, texto="Una frase corta.", progress=progress, cancelled=cancelled, voces=["voz_firme", "em_santa"])
        abiertos = []
        _sf = os.startfile
        os.startfile = lambda *a: abiertos.append(a)
        carpeta_b = os.path.join(_TMP, "muestras_boton")
        _cmu = tts.carpeta_muestras
        tts.carpeta_muestras = lambda: __import__("pathlib").Path(carpeta_b)   # (nunca la carpeta del usuario)
        try:
            panel.b_muestras.click()
            assert panel.job is not None and not panel.b_muestras.isEnabled() and not panel.progress.isHidden()
            t0 = time.time()
            while panel.job is not None:
                app.processEvents()
                time.sleep(0.02)
                assert time.time() - t0 < 120
            app.processEvents()
        finally:
            tts.crear_muestras = _cm
            tts.carpeta_muestras = _cmu
            os.startfile = _sf
        hechas_b = panel.ultimas_muestras
        assert [os.path.basename(x) for x in hechas_b] == ["01 Voz firme.wav", "02 Santa (Kokoro).wav"], hechas_b
        assert os.path.dirname(hechas_b[0]) == carpeta_b and os.path.isfile(os.path.join(carpeta_b, "LEEME.txt"))
        assert "2 muestras" in panel.status.text() and not abiertos and panel.b_muestras.isEnabled()
        print("✓ «🎧 Muestras de todas las voces»: en segundo plano, con progreso; en pruebas no abre la carpeta")
    finally:
        m["archivos"] = reales
        os.environ.pop("RECLAIMER_PIPER", None)
        os.environ.pop("RECLAIMER_PIPER_URL", None)
        srv.shutdown()
        panel.shutdown()
        panel.deleteLater()
        tts._piper.pop(modelo, None)
    assert not tts.falta_modelo("narrador_latino"), "otra vez con el modelo de verdad"

    # ---- 🎧 muestras (dos voces, en una carpeta de prueba)
    carpeta = os.path.join(_TMP, "Muestras de voces")
    hechas = tts.crear_muestras(carpeta, texto="Una frase corta de prueba.", voces=["narrador_documental",
                                                                                   "piper_davefx", "narradora_clara"])
    assert list(tts._piper) == ["es_ES-sharvard-medium"], "en memoria solo el último Piper usado"
    hechas = tts.crear_muestras(carpeta, texto="Una frase corta de prueba.", voces=["narrador_documental",
                                                                                   "narradora_clara"])
    assert [os.path.basename(x) for x in hechas] == ["01 Narrador de documental (grave).wav",
                                                     "02 Narradora clara (mujer).wav"], hechas
    leeme = open(os.path.join(carpeta, "LEEME.txt"), encoding="utf-8").read()
    assert "Apache 2.0" in leeme and "CC BY 3.0" in leeme and "CC0" in leeme and "01 Narrador" in leeme
    for x in hechas:
        assert len(leer_wav(x)) > 24000 * 0.5
    print("✓ crear_muestras: un WAV por voz con nombre claro y LEEME.txt con las licencias; en memoria solo el último "
          "Piper")
    print("✓ TODO OK")


if __name__ == "__main__":
    main()
