"""
🎨 PRUEBA de la fase 7 de la línea de tiempo: colores y fallos de cabecera.
  · cabeceras sin texto cortado con pistas de 28 px y nombres largos, en ventanas de 1920×1040 y 1366×740 (la cabecera
    se ensancha al nombre más largo; «N clips» solo si cabe), con capturas;
  · color de cada clip por su origen (narración, gameplay, B-roll de la IA, palabra clave, escena…) y el «Color de
    clip» que eliges tú manda; la insignia de la pista con su papel (voz, música, efectos) lleva su color;
  · el nombre del clip pegado al borde izquierdo visible aunque su principio quede fuera de la vista;
  · iconos monocromos (sin emojis en el título del clip ni en la cabecera) y «⋯ Más» legible.
Sin ventanas visibles (offscreen), datos aislados. Ejecutar:  .venv/Scripts/python.exe tests/test_cabeceras_colores.py <c>
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None


def _vigilante(segundos: float = 420.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "cabeceras_colores")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import colores_origen as CO
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, new_id
    from editoria.ui import timeline as TLmod
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "gameplay_partida.mp4")
    if not os.path.exists(vid):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=30",
                        "-f", "lavfi", "-i", "sine=f=500:d=30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                        "-shortest", vid], check=True)
    voz = os.path.join(RAIZ, "tests", "assets", "narracion_prueba.wav")
    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    pump(app, 0.6)
    ctrl, tl = win.ctrl, win.timeline
    vid_id, nid = ctrl.import_now([vid, voz])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    p = ctrl.project
    p.media[vid_id].category = "Videos"                 # (sin clasificar: la IA o tú lo clasificáis DESPUÉS)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    v2 = [t for t in p.tracks if t.kind == TRACK_VIDEO][0]
    ctrl.add_media([nid], a1.id, 0.0)
    ctrl.add_media([vid_id], v1.id, 0.0)
    ctrl.add_track("audio")
    ctrl.add_track("audio")
    p = ctrl.project
    auds = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    ctrl.set_track_props(a1.id, "Pista", name="A1 · Narración principal del análisis", role="voz")
    ctrl.set_track_props(auds[-2].id, "Pista", name="Música de fondo tranquila", role="musica")
    ctrl.set_track_props(auds[-1].id, "Pista", name="Efectos de sonido y golpes", role="efectos")
    p = ctrl.project
    # clips de cada origen (en V2) y uno con «Color de clip» elegido a mano
    c_broll = Clip(new_id(), vid_id, v2.id, 0.0, 1.0, 3.0, note="B-roll IA: lo que dices")
    c_pal = Clip(new_id(), vid_id, v2.id, 4.0, 5.0, 3.0, note="🔑 Palabra clave")
    c_lab = Clip(new_id(), vid_id, v2.id, 8.0, 9.0, 3.0, label="#c0392b")
    for c in (c_broll, c_pal, c_lab):
        p.clips[c.id] = c
    ctrl._bump_rev()
    ctrl.project_changed.emit()
    pump(app, 0.3)

    # ---------------------------------------------------------------- 1) colores por origen y por papel
    def color(c):
        return tl._clip_base(c)[0].name()
    narr = next(c for c in p.clips.values() if c.media_id == nid)
    game = next(c for c in p.clips.values() if c.media_id == vid_id and c.track_id == v1.id)
    assert color(narr) == CO.ORIGENES["narracion"][1], color(narr)
    tl.repaint()                                        # (primer pintado: sin clasificar, su gris propio)
    assert color(game) == CO.ORIGENES["sin_clasificar"][1], color(game)
    assert "Sin clasificar" in tl._leyenda_colores()
    p.media[vid_id].category = "Gameplay"               # la categoría cambia DESPUÉS: el color, al momento
    ctrl.media_changed.emit()
    pump(app, 0.2)
    assert color(game) == CO.ORIGENES["gameplay"][1], color(game)
    # paleta: contraste ≥ 4,5:1 con el texto blanco y ΔE ≥ 20 entre los colores que van en la misma pista
    import itertools
    import math

    def lab(hx):
        r_, g_, b_ = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c_ / 12.92 if c_ <= 0.04045 else ((c_ + 0.055) / 1.055) ** 2.4 for c_ in (r_, g_, b_)]
        X = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
        Y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        Z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
        f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (X, Y, Z)]
        return (116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])), Y
    for k_, (nom, hx) in CO.ORIGENES.items():
        assert (lab("#e6e6e8")[1] + 0.05) / (lab(hx)[1] + 0.05) >= 4.5, (nom, hx)    # (frente al texto del título)
    sonido = {"narracion", "musica", "efectos", "audio"}
    for grupo in (sonido, set(CO.ORIGENES) - sonido):
        for a_, b_ in itertools.combinations(sorted(grupo), 2):
            d_ = math.dist(lab(CO.ORIGENES[a_][1])[0], lab(CO.ORIGENES[b_][1])[0])
            assert d_ >= 20, (a_, b_, round(d_, 1))
    assert color(c_broll) == CO.ORIGENES["broll_ia"][1], color(c_broll)
    assert color(c_pal) == CO.ORIGENES["palabra"][1], color(c_pal)
    assert color(c_lab) == "#c0392b", "tu «Color de clip» manda"
    assert CO.color_pista("musica") == CO.ORIGENES["musica"][1] and CO.color_pista("") is None
    ley = tl._leyenda_colores()
    assert "Narración" in ley and "Gameplay" in ley and "B-roll de la IA" in ley and "Palabra clave" in ley, ley
    print("✓ colores por origen (y el tuyo manda), insignia por papel y leyenda")

    # ---------------------------------------------------------------- 2) cabeceras sin cortes a 28 px, dos pantallas
    tl.video_h = tl.audio_h = 28
    tl._on_project_changed()
    for (w, h), nombre in (((1920, 1040), "1920"), ((1366, 740), "1366")):
        win.resize(w, h)
        pump(app, 0.4)
        tl.repaint()
        cort = tl.textos_cortados()
        assert not cort, (nombre, cort)
        assert 170 * tl.ui_k <= tl.HEADER_W <= TLmod.TimelineWidget.CABECERA_MAX * tl.ui_k, tl.HEADER_W
        assert tl.HEADER_W <= max(170 * tl.ui_k, 0.22 * win.width()) + 1, ("tope del 22 %", tl.HEADER_W, win.width())
        img = tl.grab()
        img.save(os.path.join(out, f"cabeceras_{nombre}.png"))
        print(f"✓ {nombre}: ninguna cabecera cortada con pistas de 28 px (cabecera de {tl.HEADER_W} px)")
    assert tl.HEADER_W > 170 * tl.ui_k, "se ensanchó al nombre más largo"

    # ---------------------------------------------------------------- 3) nombre pegado al borde visible
    tl.video_h = tl.audio_h = 54
    tl._on_project_changed()
    tl.pps = 60.0
    tl.scroll = 10.0                                    # el clip de gameplay empieza en 0: su principio, fuera
    tl.update()
    pump(app, 0.3)
    i_v1 = p.tracks.index(p.track(v1.id))
    y0 = int(tl.track_y(i_v1) + 2)
    img = tl.grab().toImage()
    blancos = 0
    for x in range(int(tl.HEADER_W) + 4, int(tl.HEADER_W) + 90):
        for y in range(y0, y0 + int(12 * tl.ui_k)):
            col = img.pixelColor(x, y)
            if col.red() > 200 and col.green() > 200 and col.blue() > 200:
                blancos += 1
    assert blancos > 15, f"el nombre se lee junto al borde izquierdo ({blancos} píxeles de letra)"
    print("✓ el nombre del clip se queda pegado al borde visible")

    # ---------------------------------------------------------------- 4) iconos monocromos y «⋯ Más» legible
    import io
    import textwrap
    import tokenize

    def sin_comentarios(fn) -> str:                    # (los comentarios pueden llevar emojis: lo pintado, no)
        src = textwrap.dedent(inspect.getsource(fn))
        return " ".join(t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
                        if t.type not in (tokenize.COMMENT,))
    fuente = "".join(sin_comentarios(f) for f in (TLmod.TimelineWidget._paint_clip, TLmod.TimelineWidget._titulo_clip,
                                                    TLmod.TimelineWidget._paint_headers))
    for emo in ("🔗", "🔒", "📝", "🔍", "🎞", "❄", "🎯", "📌", "👁", "🚫"):
        assert emo not in fuente, f"emoji de color en la línea de tiempo: {emo}"
    from editoria.ui.responsive import widgets_en
    for w_, h_ in ((1920, 1040), (1366, 740)):        # la barra nunca se monta encima de sí misma
        win.resize(w_, h_)
        pump(app, 0.4)
        win._tl_fit_bar()
        pump(app, 0.2)
        vis = [x for x in widgets_en(win._tl_bar.layout()) if x.isVisible()]
        for a_, b_ in zip(vis, vis[1:]):
            assert a_.geometry().right() < b_.geometry().left() + 1, \
                (w_, type(a_).__name__, getattr(a_, "text", lambda: "")(), a_.geometry(), b_.geometry())
        tc = win.tl_timecode
        assert tc.width() + 1 >= tc.fontMetrics().horizontalAdvance(tc.text()), "el reloj, entero"
    win.resize(1920, 1040)
    pump(app, 0.4)
    win._tl_fit_bar()
    print("«⋯ Más»:", repr(win.btn_more.text()), win.btn_more.size().toTuple())
    assert win.btn_more.text() in ("⋯ Más", "Más"), "compacto, la palabra (no tres puntitos)"
    bm = win.btn_more.grab().toImage()
    lum = [0.299 * bm.pixelColor(x, y).red() + 0.587 * bm.pixelColor(x, y).green() + 0.114 * bm.pixelColor(x, y).blue()
           for x in range(2, bm.width() - 2) for y in range(2, bm.height() - 2)]
    fondo = sorted(lum)[len(lum) // 2]
    assert fondo < 110 and max(lum) - fondo > 90, ("«⋯ Más» legible", fondo, max(lum))
    print("✓ iconos monocromos y «⋯ Más» legible")
    print("TODO OK")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    main()
