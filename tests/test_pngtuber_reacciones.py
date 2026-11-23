"""
😄 PNGTuber que reacciona a lo que dices (core/pngtuber.py + core/categorias_palabras.PNGTUBER + ui/pngtuber_dialog.py).
  · Núcleo: categorías (saludos, felicidad, «¿qué?» = sorpresa, tristeza sin «vale la pena»…); cada reacción empieza
    y acaba en reposo; las reacciones no se pisan y caen en su fotograma; solo cambian los fotogramas de la reacción;
    el video deja sitio para saltar y el avatar se ve movido durante la reacción; la imagen opcional «r_feliz» se usa.
  · Ventana: con la transcripción de la voz salen las reacciones y la lista de qué palabra activó qué; quitar una
    categoría la quita; guardar el modelo guarda las categorías y la imagen opcional; crear pone el video (con su
    margen) en la línea de tiempo y un Ctrl+Z lo quita.
Ejecutar:  .venv/Scripts/python.exe tests/test_pngtuber_reacciones.py <carpeta_salida>   (sin ventanas, sin sonido)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

sys.stdout.reconfigure(line_buffering=True)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DUR = 10.0
FPS = 30
# (segundo DEL AUDIO, palabra); el audio empieza en el 0,5 de la línea de tiempo
PALABRAS = [(1.0, "¡Hola"), (1.3, "a"), (1.5, "todos!"), (3.0, "¡Qué"), (3.3, "genial!"), (5.0, "¿Qué?"),
            (6.5, "vale"), (6.8, "la"), (7.0, "pena"), (8.0, "jajaja")]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def caras(out):
    rutas = {}
    for k, color, boca in (("cerrada", (250, 210, 180), False), ("abierta", (250, 210, 180), True),
                           ("r_feliz", (90, 120, 250), True)):
        im = Image.new("RGBA", (200, 240), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([10, 10, 190, 230], fill=color + (255,), outline=(25, 25, 25, 255), width=4)
        if boca:
            d.ellipse([60, 150, 140, 205], fill=(140, 20, 30, 255))
        rutas[k] = os.path.join(out, f"avatar_{k}.png")
        im.save(rutas[k])
    return rutas


def audio(out):
    sr = 48000
    t = np.arange(int(DUR * sr)) / sr
    x = 0.4 * np.sin(2 * np.pi * 220 * t) * (0.55 + 0.45 * np.abs(np.sin(2 * np.pi * 2.5 * t)))
    ruta = os.path.join(out, "voz.wav")
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype(np.int16).tobytes())
    return ruta


def nucleo(out, imgs):
    from editoria.core import categorias_palabras as CP
    from editoria.core import media as M
    from editoria.core import pngtuber as PT
    ws = [(t, t + 0.25, w) for t, w in PALABRAS]
    ms = CP.detectar(ws, CP.PNGTUBER)
    assert [(m["cat"], CP.dicha(m)) for m in ms] == [("saludo", "hola"), ("feliz", "genial"), ("sorpresa", "qué"),
                                                      ("risa", "jajaja")], ms
    otras = CP.detectar([(0, .2, "qué"), (1, 1.2, "pena"), (2, 2.2, "nos"), (2.2, 2.4, "vemos"), (3, 3.2, "gracias"),
                         (4, 4.2, "a"), (4.2, 4.4, "lo"), (4.4, 4.6, "mejor"), (5, 5.2, "odio"), (6, 6.2, "Holanda")],
                        CP.PNGTUBER)
    assert [m["cat"] for m in otras] == ["triste", "despedida", "acuerdo", "duda", "enojo"], otras
    assert len(PT.REACCIONES) >= 10 and {r for _k, _n, r, _d in PT.REACCIONES} <= set(PT.DESC_REACCION)
    for _k, _n, reac, dur in PT.REACCIONES:
        for u in (0.0, 1.0):
            dx, dy, g, s = PT.movimiento(reac, u, dur)
            assert max(abs(dx), abs(dy), abs(g), abs(s - 1)) < 1e-6, ("empieza y acaba quieto", reac, u)
        medio = [PT.movimiento(reac, u, dur) for u in np.linspace(0.1, 0.9, 9)]
        assert max(max(abs(m[0]), abs(m[1]), abs(m[2]) / 50, abs(m[3] - 1)) for m in medio) > 0.01, reac
    assert PT.movimiento("feliz", 0.25)[1] < -0.1, "salta hacia arriba"
    assert PT.movimiento("encoge", 0.5)[3] < 0.96, "se encoge"
    # eventos en fotogramas del avatar (empieza en el 0,5 de la línea de tiempo)
    ws_tl = [(t + 0.5, t1 + 0.5, w) for t, t1, w in ws]
    n = int(DUR * FPS)
    ev = PT.eventos_reaccion(ws_tl, 0.5, n, None, FPS)
    assert [e["cat"] for e in ev] == ["saludo", "feliz", "sorpresa", "risa"], ev
    assert ev[0]["i0"] == round((1.0 - 0.08) * FPS) and ev[0]["i1"] - ev[0]["i0"] == round(1.2 * FPS)
    assert all(a["i1"] <= b["i0"] for a, b in zip(ev, ev[1:])), "no se pisan"
    solo = PT.eventos_reaccion(ws_tl, 0.5, n, ["feliz"], FPS)
    assert [e["cat"] for e in solo] == ["feliz"]
    assert PT.eventos_reaccion(ws_tl, 0.5, n, [], FPS) == []
    pk = M.waveform_peaks(imgs["_wav"])
    base = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, fps=FPS, parpadeo=None)
    con = PT.aplicar_reacciones(base, ev, FPS)
    dentro = set()
    for e in ev:
        dentro.update(range(e["i0"], e["i1"]))
    assert all(con[i] == base[i] for i in range(n) if i not in dentro), "fuera de las reacciones, igual"
    assert all(con[i].boca_abierta == base[i].boca_abierta for i in range(n)), "la boca sigue con la voz"
    assert any(con[i].movido() for i in dentro) and all(con[i].reaccion for i in dentro)
    # el video: sitio para saltar; durante «feliz» se ve su imagen opcional; en reposo, la normal
    modelo = {"nombre": "R", "imagenes": {k: v for k, v in imgs.items() if not k.startswith("_")}}
    mp4 = os.path.join(out, "reacciones.mp4")
    res = PT.renderizar(modelo, con, mp4, 240, FPS)
    W0, H0, iw, ih = PT.medida(modelo, 240, 0.0)
    assert res["alto"] > H0 and res["ancho"] > W0, ("deja sitio", res, (W0, H0))
    assert abs(M.probe(mp4)["duration"] - DUR) < 0.06
    e_f = next(e for e in ev if e["cat"] == "feliz")
    i_f = e_f["a0"] + e_f["largo"] // 4                        # (arriba del primer salto)
    i_q = e_f["i0"] - 3
    f_f = M.frame_rgb(mp4, (i_f + 0.5) / FPS, res["ancho"]).astype(int)
    f_q = M.frame_rgb(mp4, (i_q + 0.5) / FPS, res["ancho"]).astype(int)
    azul = (f_f[..., 2] > 200) & (f_f[..., 0] < 140)
    assert azul.mean() > 0.1, ("se ve la imagen «r_feliz»", azul.mean())
    assert ((f_q[..., 2] > 200) & (f_q[..., 0] < 140)).mean() < 0.01, "antes, la normal"
    filas = np.flatnonzero(azul.any(axis=1))
    abajo_q = np.flatnonzero((np.abs(f_q - f_q[2, 2]).sum(axis=2) > 60).any(axis=1)).max()
    assert filas.max() < abajo_q - 0.05 * ih, ("en el aire", filas.max(), abajo_q)
    print(f"✓ núcleo: {len(PT.REACCIONES)} reacciones que empiezan y acaban quietas; eventos en su fotograma, sin "
          f"pisarse; video {res['ancho']}×{res['alto']} con sitio para saltar, «r_feliz» en el aire")


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMP, "salida"))
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    imgs = caras(out)
    wav = audio(out)
    imgs["_wav"] = wav
    nucleo(out, imgs)
    from editoria.core import pngtuber as PT
    from editoria.core.model import TRACK_AUDIO
    from editoria.ui import pngtuber_dialog as PD
    from editoria.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    win = None
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        (aid,) = ctrl.import_now([wav])
        while ctrl.analyzing:
            pump(app, 0.1)
        a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
        voz = ctrl.add_media([aid], a1.id, 0.5)[0]
        p.transcripts[aid] = {"language": "es", "words": [[t, t + 0.25, w, 0.9] for t, w in PALABRAS]}
        ctrl.ensure_peaks(aid, wait=True)
        d = PD.abrir(win, voz)
        assert d.pestanas.tabText(1) == "😄 Reacciones"
        for k in ("cerrada", "abierta", "r_feliz"):
            d.set_imagen(k, imgs[k])
        assert d.reac_img["feliz"].ruta == imgs["r_feliz"]
        d.nombre.setText("Con reacciones")
        pump(app, 0.4)
        cats = [e["cat"] for e in d._eventos]
        assert cats == ["saludo", "feliz", "sorpresa", "risa"], cats
        textos = [d.reac_lista.item(i).text() for i in range(d.reac_lista.count())]
        assert len(textos) == 4 and "«hola»" in textos[0] and "Saludos" in textos[0], textos
        assert any(e.movido() for e in d._ests), "la vista previa se mueve"
        d._ver_reaccion(d.reac_lista.item(1))
        assert d._bucle[0] <= d._eventos[1]["i0"] < d._bucle[1]
        for _ in range(12):
            d._paso()                                      # (dibuja la vista previa con la reacción)
        d.reac_cb["saludo"].setChecked(False)
        pump(app, 0.4)
        assert [e["cat"] for e in d._eventos] == ["feliz", "sorpresa", "risa"], "quitar una categoría la quita"
        assert "saludo" not in d.ajustes()["reacciones"]
        print("✓ ventana: reacciones por la transcripción, lista de qué palabra activó qué, quitar una categoría")

        assert d.guardar_modelo()
        m = PT.cargar("Con reacciones")
        assert m["imagenes"]["r_feliz"] == os.path.abspath(imgs["r_feliz"])
        assert "saludo" not in m["ajustes"]["reacciones"] and "feliz" in m["ajustes"]["reacciones"]
        d.modelos.setCurrentIndex(0)
        assert not d.reac_img["feliz"].ruta, "avatar nuevo: sin imagen opcional"
        d.modelos.setCurrentIndex(d.modelos.findText("🎭 Con reacciones"))
        assert d.reac_img["feliz"].ruta and not d.reac_cb["saludo"].isChecked(), "carga imagen y categorías"
        print("✓ guardar/cargar el modelo con sus categorías y la imagen opcional")

        n_antes = len(p.clips)
        assert d.crear() is not None
        t0 = time.time()
        while d.job is not None and time.time() - t0 < 120:
            pump(app, 0.1)
        pump(app, 0.2)
        assert d.creado and d.creado in p.clips, d.estado.text()
        c = p.clips[d.creado]
        alto = PT.alto_en_px(d.tamano.value() / 100.0, p.height)
        rb = max(e.rebote_px for e in d._ests)
        W, H, _iw, _ih = PT.medida(d.modelo(), alto, rb, reacciones=True)
        assert (d.resultado["ancho"], d.resultado["alto"]) == (W, H), (d.resultado, W, H)
        assert abs(c.start - 0.5) < 1e-6 and len(p.clips) == n_antes + 1
        ctrl.undo_stack.undo()
        assert d.creado not in p.clips, "un Ctrl+Z lo quita"
        print(f"✓ crear: video {W}×{H} (con sitio para las reacciones) en la línea de tiempo; Ctrl+Z lo quita")
        d.close()
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        if win is not None and win.isVisible():           # (si algo falló: cerrar sin preguntar)
            win.ctrl.undo_stack.setClean()
            win.ctrl._media_dirty = False
            win.close()
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
