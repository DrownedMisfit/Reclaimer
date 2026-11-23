"""
🎨 Prueba del sistema de diseño (ui/diseno.py) en el panel «Limpieza» (pestaña «Limpiar»):
  1) la tabla «Qué buscar» combina las dos listas viejas (una fila por opción, columnas «Marcar» y «Quitar»; sin
     «Quitar» donde no hay limpieza automática, con su tooltip) y ya no quedan emojis ni cuadros de número viejos;
  2) la migración de ajustes (de las dos listas a la tabla, sin perder nada; una sola vez);
  3) el análisis con los ajustes de siempre da EXACTAMENTE lo mismo que la versión anterior de voice_cleanup;
  4) «Limpiar» usa las casillas «Quitar» y «Volver a analizar» usa las de «Marcar»;
  5) ningún texto cortado a 200, 280, 360 y 520 px (con la misma revisión que test_paneles_sin_cortes);
  6) cambiar el color de acento repinta el botón principal y las casillas marcadas.
Ejecutar:  .venv/Scripts/python.exe tests/test_diseno_limpieza.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="reclaimer_diseno_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, TMP, True)
os.environ["LOCALAPPDATA"] = TMP
os.environ["EDITORIA_DATOS"] = os.path.join(TMP, "EditorIA")
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(RAIZ, "datos", "modelos"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (ajustes de prueba: nunca los tuyos)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

EMOJIS = ("🧹", "📝", "⚡", "🔍", "✓", "⏸", "🎙")


def W(text, t0):
    out, t = [], t0
    for w in text.split():
        out.append([round(t, 3), round(t + 0.3, 3), w, 0.95])
        t += 0.35
    return out, t


def palabras():
    """Un guion con de todo: tomas repetidas, muletillas seguras y posibles, repeticiones y «muy muy»."""
    t = 0.5
    a, t = W("Este juego tiene un problema", t)
    b, t = W("Este juego tiene un problema muy grande con la cámara.", t + 0.8)
    c, t = W("Este juego eh tiene un problema muy grande con la cámara.", t + 0.8)
    d, t = W("Y eh luego viene el el final", t + 0.8)
    e, t = W("bueno, este, que es muy muy bueno.", t + 0.1)
    f, t = W("Ayer me puse a trabajar un rato largo.", t + 0.9)
    g, t = W("Lo que hice fue trabajar toda la tarde.", t + 0.5)
    return a + b + c + d + e + f + g


def _codificar(textos):
    """Codificador de frases falso y fijo (sin el modelo de verdad): las dos frases de «trabajar» dicen lo mismo con
    otras palabras; las demás, cada una en su dirección."""
    import zlib
    vecs = np.zeros((len(textos), 4096), np.float32)
    for i, t in enumerate(textos):
        vecs[i, 0 if "trabajar" in t.lower() else 1 + zlib.crc32(t.encode("utf-8")) % 4095] = 1.0
    return vecs


COMMIT_ANTERIOR = "e472489"     # (el último commit con el voice_cleanup de antes de la tabla «Marcar · Quitar»)


def voice_cleanup_anterior():
    """voice_cleanup.py tal como era antes de separar seguras/posibles y parecidas/tomas (para comparar)."""
    import importlib.util
    src = subprocess.run(["git", "-C", RAIZ, "show", f"{COMMIT_ANTERIOR}:editoria/ai/voice_cleanup.py"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    assert "soft_fillers" not in src, "COMMIT_ANTERIOR ya tiene la versión nueva"
    ruta = os.path.join(TMP, "voice_cleanup_anterior.py")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("editoria.ai.voice_cleanup_anterior", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def prueba_analisis_igual():
    from editoria.ai import voice_cleanup as nuevo
    viejo = voice_cleanup_anterior()
    for m in (nuevo, viejo):
        m._sentence_encoder = lambda: _codificar
    words = palabras()
    sr = 16000
    rng = np.random.default_rng(1)
    samples = np.zeros(int(words[-1][1] * sr) + sr * 3, np.float32)
    for w in words:                                    # (voz donde hay palabras; silencios largos entre frases)
        a, b = int(w[0] * sr), int(w[1] * sr)
        samples[a:b] = 0.3 * np.sin(np.arange(b - a) * 2 * np.pi * 200 / sr) + 0.01 * rng.standard_normal(b - a)
    import itertools
    campos = ("silences", "noises", "fillers", "repeated_words", "retakes", "similar", "doubtful", "clipping")
    n = 0
    for combo in itertools.product((True, False), repeat=len(campos)):
        if n and sum(combo) not in (len(campos), len(campos) - 1, len(campos) - 2, 1):
            continue                                   # (todas, quitando una o dos, y de una en una)
        kw = dict(zip(campos, combo))
        o_viejo = viejo.CleanupOptions(**kw)
        # lo mismo en la tabla nueva: «Muletillas» = seguras + posibles; «parecidas» solo se buscaban con «tomas»
        o_nuevo = nuevo.CleanupOptions(**dict(kw, similar=kw["similar"] and kw["retakes"]),
                                       soft_fillers=kw["fillers"])
        r1 = viejo.analyze(samples, sr, words, o_viejo)
        r2 = nuevo.analyze(samples, sr, words, o_nuevo)
        assert r1 == r2, (kw, [d["label"] for d in r1], [d["label"] for d in r2])
        assert o_viejo.kinds() == o_nuevo.kinds(), (kw, o_viejo.kinds(), o_nuevo.kinds())
        n += 1
    d = nuevo.CleanupOptions()
    assert nuevo.analyze(samples, sr, words, d) == viejo.analyze(samples, sr, words, viejo.CleanupOptions())
    print(f"✓ el análisis da lo mismo que antes con los ajustes de siempre y {n} combinaciones de casillas")
    # lo nuevo: posibles sin seguras, y parecidas sin tomas
    solo_pos = nuevo.analyze(samples, sr, words, nuevo.CleanupOptions(fillers=False, soft_fillers=True))
    labels = [x["label"] for x in solo_pos if x["kind"] == "filler"]
    assert labels and all(lb.startswith("Posible") for lb in labels), labels
    solo_seg = nuevo.analyze(samples, sr, words, nuevo.CleanupOptions(fillers=True, soft_fillers=False))
    labels = [x["label"] for x in solo_seg if x["kind"] == "filler"]
    assert labels and not any(lb.startswith("Posible") for lb in labels), labels
    par = nuevo.analyze(samples, sr, words, nuevo.CleanupOptions(retakes=False, similar=True))
    tomas = [x for x in par if x["kind"] == "retake"]
    assert tomas and all((x.get("data") or {}).get("level") == "parecido" for x in tomas), [x["label"] for x in tomas]
    print("✓ «Muletillas seguras» y «Posibles muletillas» se marcan por separado; «Frases parecidas» sin «Tomas»")


def prueba_migracion():
    from editoria.ui.voice_panel import migrar_ajustes_limpieza
    ini = os.path.join(TMP, "migracion.ini")
    s = QSettings(ini, QSettings.IniFormat)
    for k, v in (("limpieza/muletillas", False), ("limpieza/tomas", False), ("limpieza/parecidas", True),
                 ("limpieza/ruidos", False), ("limpieza_auto/filler", False), ("limpieza_auto/noise", True)):
        s.setValue(k, v)
    assert migrar_ajustes_limpieza(s)
    assert str(s.value("limpieza/muletillas_posibles")).lower() == "false"
    assert str(s.value("limpieza/parecidas")).lower() == "false"     # (antes no se buscaban sin «tomas»)
    assert str(s.value("limpieza/ruidos")).lower() == "false"
    assert str(s.value("limpieza_auto/filler")).lower() == "false"   # («Quitar»: las de siempre, sin tocar)
    assert str(s.value("limpieza_auto/noise")).lower() == "true"
    s.setValue("limpieza/parecidas", True)
    assert not migrar_ajustes_limpieza(s) and str(s.value("limpieza/parecidas")).lower() == "true", "una sola vez"
    s2 = QSettings(os.path.join(TMP, "migracion_vacia.ini"), QSettings.IniFormat)
    assert migrar_ajustes_limpieza(s2)
    assert s2.value("limpieza/muletillas_posibles") is None and s2.value("limpieza/parecidas") is None
    print("✓ migración: «Muletillas» se reparte en seguras y posibles, «Quitar» = la lista de abajo, una sola vez")


def textos_visibles(raiz):
    from PySide6.QtWidgets import QAbstractButton, QLabel
    out = []
    for w in [raiz] + raiz.findChildren(QWidget):
        if isinstance(w, (QLabel, QAbstractButton)) and w.isVisibleTo(raiz):
            out.append(w.text())
    return out


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_diseno_limpieza")
    os.makedirs(out, exist_ok=True)
    prueba_analisis_igual()
    prueba_migracion()

    app = QApplication(sys.argv)
    from editoria.ui import theme as T
    T.apply_dark_theme(app)
    import test_paneles_sin_cortes as SC
    SC.contar_pintados()
    from editoria.ai import voice_cleanup
    from editoria.core import media as media_tools
    from editoria.core.model import SUG_PENDING, TRACK_AUDIO
    from editoria.ui import diseno as D
    from editoria.ui import voice_panel as VP
    from editoria.ui.main_window import MainWindow

    st = QSettings("EditorIA", "EditorIA")
    # ajustes «viejos» del usuario: deben verse en la tabla tras migrar
    st.remove("limpieza/version_tabla")
    st.remove("limpieza/muletillas_posibles")
    for k, v in (("limpieza/muletillas", True), ("limpieza/tomas", True), ("limpieza/parecidas", True),
                 ("limpieza/ruidos", True), ("limpieza/dudosas", False), ("limpieza/min_silencio", 1.2),
                 ("limpieza/pausa", 0.3), ("limpieza_auto/filler", True), ("limpieza_auto/filler_soft", False),
                 ("limpieza_auto/noise", False), ("limpieza_auto/silence", True), ("limpieza_auto/repeat", True),
                 ("limpieza_auto/retake", True), ("limpieza_auto/al_terminar", False)):
        st.setValue(k, v)

    win = MainWindow()
    win.show()
    vp = win.voice
    c = win.ctrl
    p = c.project

    # ---- 1) la tabla combina las dos listas
    t = vp.tabla
    assert t.filas() == ["silence", "filler", "filler_soft", "repeat", "retake", "noise", "similar", "doubt",
                         "clipping"], t.filas()
    assert [t.etiqueta(f).text() for f in t.filas()] == [
        "Silencios largos", "Muletillas seguras", "Posibles muletillas", "Palabras repetidas", "Tomas repetidas",
        "Respiraciones y ruidos", "Frases parecidas", "Palabras dudosas", "Saturación"]
    assert set(vp.auto_chk) == set(voice_cleanup.AUTO_DEFAULTS)
    for f in t.filas():
        assert t.casilla(f, "marcar") is not None, f
        if f in voice_cleanup.AUTO_DEFAULTS:
            assert t.casilla(f, "quitar") is vp.auto_chk[f], f
        else:
            assert t.casilla(f, "quitar") is None and "solo se avisa" in t.celda(f, "quitar").toolTip(), f
    assert vp.chk_sil is t.casilla("silence", "marcar") and vp.chk_fill_soft is t.casilla("filler_soft", "marcar")
    from PySide6.QtWidgets import QDoubleSpinBox, QGroupBox
    assert not vp.limpiar_vista.findChildren(QDoubleSpinBox) and not vp.limpiar_vista.findChildren(QGroupBox)
    vistos = textos_visibles(vp.limpiar_vista) + textos_visibles(vp.narr_fila) + [vp.status.text()] + \
        [vp.tabs._secs[i].head.text() for i in range(vp.tabs.count())]
    malos = [x for x in vistos if any(e in x for e in EMOJIS)]
    assert not malos, malos
    print(f"✓ una sola tabla «Marcar · Quitar» con {len(t.filas())} filas (las dos listas viejas), sin emojis")

    # ---- 2) migración, en el panel
    assert vp.chk_fill.isChecked() and vp.chk_fill_soft.isChecked(), "«Muletillas» → seguras y posibles"
    assert vp.auto_chk["filler"].isChecked() and not vp.auto_chk["filler_soft"].isChecked()
    assert vp.chk_noise.isChecked() and not vp.auto_chk["noise"].isChecked()
    assert not vp.chk_doubt.isChecked() and vp.chk_similar.isChecked()
    assert abs(vp.min_sil.value() - 1.2) < 1e-6 and abs(vp.keep.value() - 0.3) < 1e-6
    assert vp.min_sil.campo.text() == "1,20 s" and vp.keep.campo.text() == "0,30 s"
    assert int(st.value("limpieza/version_tabla")) == VP.VERSION_AJUSTES_LIMPIEZA
    print("✓ el panel enseña tus ajustes de antes (coma decimal: «1,20 s»)")

    # ---- el número se escribe y se arrastra
    vp.min_sil.campo.escrito.emit("2,5")
    assert abs(vp.min_sil.value() - 2.5) < 1e-6 and vp.min_sil.campo.text() == "2,50 s"
    vp.min_sil.campo.arrastrado.emit(-3.0)
    assert abs(vp.min_sil.value() - 2.2) < 1e-6, vp.min_sil.value()
    vp.min_sil.campo.escrito.emit("hola")
    assert abs(vp.min_sil.value() - 2.2) < 1e-6
    vp.min_sil.setValue(99)
    assert vp.min_sil.value() == 5.0
    vp.min_sil.setValue(1.2)
    print("✓ «Mayores de»: se escribe (con coma), se arrastra y no se sale del rango")

    # ---- 4) «Limpiar» usa «Quitar»; «Volver a analizar» usa «Marcar»
    voz = os.path.join(TMP, "voz.wav")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=40",
                    voz], check=True)
    [mid] = c.import_now([voz])
    nar = [x for x in p.tracks if x.kind == TRACK_AUDIO][0]
    c.add_media([mid], nar.id, 0.0)
    words = palabras()
    c.set_transcript(mid, {"language": "es", "words": words, "segments": []})
    vp.media_combo.setCurrentIndex(vp.media_combo.findData(mid))
    app.processEvents()
    assert vp.narr_punto.estado() == "listo" and vp.status.text().startswith("Transcrita"), vp.status.text()

    capturado = {}
    analizar_real = voice_cleanup.analyze

    def analizar_falso(samples, sr, ws, opts, progress=None, cancelled=None):
        capturado["opts"] = opts
        return analizar_real(samples, sr, ws, opts, None, None)
    VP.voice_cleanup.analyze = analizar_falso
    vp._start_job = lambda fn, on_done, label, on_partial=None: on_done(fn(lambda *a: None, lambda: False))
    vp.chk_take.setChecked(False)
    vp.chk_doubt.setChecked(True)
    vp.chk_fill_soft.setChecked(False)
    assert not vp.auto_chk["retake"].isChecked(), "sin «Marcar», «Quitar» se apaga"
    vp.btn_analyze.click()
    o = capturado["opts"]
    assert not o.retakes and o.doubtful and o.fillers and not o.soft_fillers and abs(o.min_silence - 1.2) < 1e-6, o
    assert str(st.value("limpieza/muletillas_posibles")).lower() == "false"
    vp.auto_chk["retake"].setChecked(True)
    assert vp.chk_take.isChecked(), "«Quitar» marca también «Marcar»"
    vp.chk_fill_soft.setChecked(True)
    vp.btn_analyze.click()
    o = capturado["opts"]
    assert o.retakes and o.soft_fillers
    VP.voice_cleanup.analyze = analizar_real
    print("✓ «Volver a analizar» (icono) busca lo marcado en «Marcar»; «Quitar» necesita «Marcar»")

    pend = [s for s in p.suggestions if s.media_id == mid and s.status == SUG_PENDING]
    assert any(s.kind == "filler" for s in pend) and any(s.kind == "retake" for s in pend)
    vp.auto_chk["filler"].setChecked(False)
    assert not any(s.kind == "filler" for s in vp.auto_candidates())
    vp.auto_chk["filler"].setChecked(True)
    assert str(st.value("limpieza_auto/filler")).lower() == "true"
    cand = vp.auto_candidates()
    kinds = {s.kind for s in cand}
    assert "filler" in kinds and "retake" in kinds and "doubt" not in kinds, kinds
    from PySide6.QtWidgets import QMessageBox
    VP.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    idx = c.undo_stack.index()
    vp.btn_auto_clean.click()
    aplicadas = [s for s in p.suggestions if s.media_id == mid and s.status == "applied"]
    assert len(aplicadas) == len(cand) and c.undo_stack.index() == idx + 1, (len(aplicadas), len(cand))
    c.undo_stack.undo()
    print(f"✓ «Limpiar» (el botón principal) quita lo marcado en «Quitar»: {len(cand)} cortes, un solo Ctrl+Z")

    # ---- 5) sin texto cortado a 280 / 360 / 520 px
    largo = ("narracion_con_un_nombre_larguisimo_que_no_cabe_de_ninguna_manera_ni_en_el_panel_mas_ancho_"
             "que_puedas_imaginar_version_final_definitiva.wav")
    m = p.media[mid]
    m.name = largo
    vp._refresh_media()
    caja = QWidget()
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(vp)
    # (en la ventana, «Limpieza» va dentro de una sección plegable de «Limpieza y mezcla», que la esconde si está
    #  cerrada: escondida, la caja no la coloca y se queda con su tamaño de antes —640 × 480—. Aquí, a la vista)
    vp.show()
    from editoria.ui import responsive as R
    R.adaptar(caja)
    for ancho in (200, 280, 360, 520):
        caja.setFixedWidth(ancho)
        caja.setFixedHeight(1300)
        caja.show()
        for _ in range(6):
            app.processEvents()
        cortes, vis = {}, set()
        SC.revisar(caja, cortes, vis, f"{ancho} px")
        assert not cortes, "\n".join(cortes.values())
        assert vp.narr_info.text().endswith("…") and largo in vp.narr_info.toolTip(), vp.narr_info.text()
        from PySide6.QtCore import QPoint
        for w in (vp.btn_auto_clean, vp.auto_after, vp.min_sil.campo, vp.btn_analyze):
            der = w.mapTo(caja, QPoint(w.width(), 0)).x()
            minimo = min(w.minimumSizeHint().width(), w.maximumWidth())
            assert der <= ancho and w.width() >= minimo - 1, (w, ancho, der, w.width(), minimo)
        caja.grab().save(os.path.join(out, f"limpieza_{ancho}.png"))
    print(f"✓ nada cortado a 200, 280, 360 y 520 px ({len(vis)} controles revisados); el nombre largo acaba en «…»")

    # ---- 6) el cambio de acento repinta
    def centro(w, dx=0.08):
        img = w.grab().toImage()
        return QColor(img.pixel(int(img.width() * dx) + 1, img.height() // 2))

    def cerca(a: QColor, b: str):
        b = QColor(b)
        return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) < 30

    antes = T.ACENTO
    casilla = vp.auto_chk["filler"]
    try:
        for clave in ("naranja", "azul"):
            T.poner_acento(clave, app, guardar=False)
            app.processEvents()
            g = D.degradado_acento()                 # (🎨 con profundidad: el degradado sale del acento)
            img = vp.btn_auto_clean.grab().toImage()
            medio = QColor(T.mezcla(g["arriba"], g["abajo"], 0.5))
            pix = QColor(img.pixel(int(img.width() * 0.03) + 2, img.height() // 2))
            assert cerca(pix, medio.name()), (clave, pix.name(), medio.name())
            img = casilla.grab().toImage()
            lado = D.px(D.CASILLA)
            x0 = (img.width() - lado) // 2 + 2
            y0 = (img.height() - lado) // 2 + 2
            assert cerca(QColor(img.pixel(x0, y0)), T.ACCENT), (clave, QColor(img.pixel(x0, y0)).name())
            assert vp.btn_auto_clean.degradado_ahora()["abajo"] == D.degradado_acento(T.ACCENT)["abajo"]
    finally:
        T.poner_acento(antes, app, guardar=False)
    print("✓ cambiar el acento repinta «Limpiar» y las casillas marcadas al momento")

    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    cerrar_trabajos(app, win)
    print("TODO OK")


def cerrar_trabajos(app, win):
    """Los trabajos en segundo plano (p. ej. «🎯 Afinar palabras», que arranca solo tras poner una transcripción) se
    paran y se esperan antes de salir: si Python se cierra con un hilo vivo, sale con código 127 (ver test_phase3)."""
    import time
    from editoria.ui.jobs import live_jobs
    from editoria.ui.task_window import stop_all
    stop_all(15000)
    win.analyzer.shutdown()
    win.ctrl.shutdown(15000)
    t_fin = time.time() + 60
    while time.time() < t_fin and any(j.isRunning() for j in live_jobs()):
        app.processEvents()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
