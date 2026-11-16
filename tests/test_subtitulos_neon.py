"""
Prueba de los subtítulos «Neón palabra a palabra» : cada palabra aparece cuando se dice
(y no antes) y se queda; el estilo Neón no lleva contorno negro y sí un halo; en una frase con «?» (o una palabra
resaltada) el resplandor pasa de blanco a lila y a magenta; estirón al empezar la frase; golpe final antes de un
corte; el panel trae las casillas; y la EXPORTACIÓN coincide con el VISOR fotograma a fotograma (píxeles).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles ni sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_subtitulos_neon.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H, FPS = 960, 540, 30
BG = "#556070"
# (inicio, fin, palabra) en segundos: 4 frases; un corte de plano a los 4,9 s
WORDS = [(0.50, 0.80, "Hola"), (0.95, 1.25, "a"), (1.40, 1.70, "todos."),
         (2.30, 2.55, "¿Por"), (2.60, 2.95, "qué?"),
         (3.60, 3.85, "Esto"), (3.90, 4.00, "es"), (4.05, 4.60, "increíble."),
         (6.00, 6.30, "Sigue"), (6.35, 6.70, "así.")]
CUT = 4.9


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def qimg_to_np(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    bpl = img.bytesPerLine()
    return np.frombuffer(img.constBits(), np.uint8, count=bpl * img.height()).reshape(
        img.height(), bpl)[:, :img.width() * 3].reshape(img.height(), img.width(), 3).copy()


def np_to_qimg(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.shape[1] * 3, QImage.Format_RGB888).copy()


def paint_on(bg: np.ndarray | None, cue, style, t) -> np.ndarray:
    """Lo que dibuja el visor en t, encima de un fondo (gris o un fotograma exportado sin subtítulos)."""
    from editoria.ui.subtitle_item import paint_subtitle
    if bg is None:
        img = QImage(W, H, QImage.Format_RGB888)
        img.fill(QColor(BG))
    else:
        img = np_to_qimg(bg)
    p = QPainter(img)
    paint_subtitle(p, cue, style, t, W, H)
    p.end()
    return qimg_to_np(img)


def text_box(a: np.ndarray, bg: np.ndarray | None = None, thr: int = 25):
    """Caja (x0, y0, x1, y1) de lo que cambió respecto al fondo."""
    ref = np.array(QColor(BG).getRgb()[:3]) if bg is None else bg
    d = np.abs(a.astype(int) - ref).max(-1) > thr
    ys, xs = np.nonzero(d)
    if not len(xs):
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def frames(ff, mp4, idxs):
    sel = "+".join(f"eq(n\\,{i})" for i in idxs)
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-i", mp4, "-vf", f"select={sel}", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
    arr = np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, 3)
    assert len(arr) == len(idxs), (len(arr), idxs)
    return dict(zip(idxs, arr))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import subtitles as SUBS
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, SubtitleStyle
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.subtitle_item import SubtitleItem

    ff = M.ffmpeg()
    voz = os.path.join(out, "voz.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=10:sample_rate=48000",
                    "-ac", "2", voz], check=True)
    planos = []
    for name, col, d in (("plano_a.mp4", "0x3a4a5c", CUT), ("plano_b.mp4", "0x4d3a3a", 10 - CUT)):
        path = os.path.join(out, name)
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={col}:s={W}x{H}:r={FPS}:d={d:.2f}", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", path], check=True)
        planos.append(path)
    ctrl = ProjectController()
    aid, va, vb = ctrl.import_paths([voz] + planos)
    while ctrl.analyzing:
        pump(app, 0.05)
    ctrl.set_settings(width=W, height=H, fps=float(FPS))
    p = ctrl.project
    ctrl.add_media([aid], [t for t in p.tracks if t.kind == TRACK_AUDIO][0].id, 0)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([va], v1.id, 0)
    ctrl.add_media([vb], v1.id, CUT)
    ctrl.set_transcript(aid, {"language": "es", "model": "prueba", "segments": [],
                              "words": [[a, b, w, 0.99] for a, b, w in WORDS]})
    ctrl.set_subtitle_style("Activar", enabled=True, media_id=aid, preset=SUBS.NEON_WORDS,
                            **SUBS.PRESETS[SUBS.NEON_WORDS])
    ctrl.set_emphasis([7], True)                         # «increíble» resaltada
    p = ctrl.project
    st = p.subtitles
    cues = SUBS.styled_cues(p)
    assert [c.text(" ") for c in cues] == ["HOLA A TODOS.", "¿POR QUÉ?", "ESTO ES INCREÍBLE.", "SIGUE ASÍ."], \
        [c.text(" ") for c in cues]
    assert all(len(c.lines) <= 2 for c in cues)
    print("✓ preset «Neón palabra a palabra»: mayúsculas, centrado, 2 líneas como mucho, 4 frases")

    # 1) Palabra a palabra: cada una aparece cuando se dice, no antes, y se queda
    c1 = cues[0]
    for t, n in ((0.50, 1), (0.94, 1), (0.95, 2), (1.39, 2), (1.40, 3), (1.90, 3)):
        assert SUBS.words_shown(c1, st, t) == n, (t, SUBS.words_shown(c1, st, t), n)
    a1, a2 = paint_on(None, c1, st, 0.94), paint_on(None, c1, st, 0.96)
    b1, b2 = text_box(a1), text_box(a2)
    assert b2[2] - b2[0] > (b1[2] - b1[0]) * 1.3, (b1, b2)
    assert SUBS.words_shown(cues[1], st, 2.31) == 1 and SUBS.words_shown(cues[1], st, 2.60) == 2
    print(f"✓ palabra a palabra: «HOLA» (ancho {b1[2] - b1[0]} px) → «HOLA A» ({b2[2] - b2[0]} px) justo a los "
          "0,95 s, no antes; la frase siguiente empieza vacía otra vez")

    # 2) Neón: sin contorno negro, con halo
    bg_l = np.dot(QColor(BG).getRgb()[:3], (0.299, 0.587, 0.114))
    neon = paint_on(None, c1, st, 1.5)
    x0, y0, x1, y1 = text_box(neon)
    region = neon[y0:y1, x0:x1].astype(float)
    lum = region @ np.array((0.299, 0.587, 0.114))
    assert lum.min() >= bg_l - 3, f"no debería haber nada más oscuro que el fondo (mín {lum.min():.0f} / {bg_l:.0f})"
    clasico = SubtitleStyle(**{**SUBS.PRESETS["YouTube clásico"], "enabled": True, "media_id": aid})
    cl = paint_on(None, c1, clasico, 1.5).astype(float) @ np.array((0.299, 0.587, 0.114))
    assert cl.min() < bg_l - 40, "(control: el estilo clásico SÍ tiene contorno negro)"
    from dataclasses import replace
    sin_halo = paint_on(None, c1, replace(st, glow=0.0), 1.5)
    n_halo = int(((neon.astype(int) - np.array(QColor(BG).getRgb()[:3])).max(-1) > 25).sum())
    n_sin = int(((sin_halo.astype(int) - np.array(QColor(BG).getRgb()[:3])).max(-1) > 25).sum())
    assert n_halo > n_sin * 1.6, (n_halo, n_sin)
    assert st.outline == 0 and st.glow > 0 and st.uppercase and st.position == "middle" and st.max_lines == 2
    print(f"✓ Neón: sin contorno negro (más oscuro que el fondo: nada) y con halo ({n_halo} px iluminados frente a "
          f"{n_sin} sin halo)")

    # 3) Brillo que cambia de color en la frase con «?» (y en la palabra resaltada)
    c2, c3, c4 = cues[1], cues[2], cues[3]
    assert SUBS.glow_color_at(c1, st, 1.5) == "#FFFFFF", "frase normal: blanco"
    assert SUBS.glow_color_at(c2, st, c2.start) == "#FFFFFF"
    assert SUBS.glow_color_at(c2, st, c2.start + 0.15) == SUBS.LILA.upper()
    assert SUBS.glow_color_at(c2, st, c2.start + 0.31) == st.highlight.upper() == "#FF3DF2"
    assert SUBS.glow_color_at(c4, st, c4.start + 0.5) == "#FFFFFF", "la frase siguiente vuelve a blanco"
    tw = next(w for w in c3.words if w.index == 7).start
    assert SUBS.glow_color_at(c3, st, tw - 0.05) == "#FFFFFF" and SUBS.glow_color_at(c3, st, tw + 0.35) == "#FF3DF2"

    def halo_tint(img):
        d = img.astype(int) - np.array(QColor(BG).getRgb()[:3])
        m = (np.abs(d).max(-1) > 25) & (img.min(-1) < 235)          # el halo (no la letra blanca)
        px = img[m].astype(float)
        return float(np.mean((px[:, 0] + px[:, 2]) / 2 - px[:, 1]))
    blanco, magenta = halo_tint(paint_on(None, c2, st, c2.start + 0.001)), halo_tint(paint_on(None, c2, st, 2.9))
    assert magenta > blanco + 25, (blanco, magenta)
    print(f"✓ frase con «?»: el resplandor pasa de blanco a lila y a magenta en 0,3 s (tinte {blanco:.0f} → "
          f"{magenta:.0f}); con la palabra resaltada, desde que se dice; la frase siguiente, blanca")

    # 4) Estirón al cambiar de frase
    assert SUBS.scale_at(c1, st, c1.start) == (1.6, 1.0)
    assert abs(SUBS.scale_at(c1, st, c1.start + 1 / 30)[0] - 1.4) < 1e-6
    assert SUBS.scale_at(c1, st, c1.start + 0.1) == (1.0, 1.0)
    e0, e1 = text_box(paint_on(None, c1, st, c1.start)), text_box(paint_on(None, c1, st, c1.start + 0.2))
    ratio = (e0[2] - e0[0]) / (e1[2] - e1[0])
    assert 1.4 < ratio < 1.75 and abs((e0[3] - e0[1]) - (e1[3] - e1[1])) <= 2, (ratio, e0, e1)
    print(f"✓ estirón: el primer fotograma de la frase sale {ratio:.2f} veces más ancho y en 3 fotogramas vuelve")

    # 5) Golpe final: la frase de antes del corte crece; las demás no
    assert [c.punch for c in cues] == [False, False, True, False], [c.punch for c in cues]
    sx, sy = SUBS.scale_at(c3, st, c3.end - 0.01)
    assert sx > 1.24 and sy > 1.24 and SUBS.scale_at(c4, st, c4.end - 0.01) == (1.0, 1.0)
    g0, g1 = text_box(paint_on(None, c3, st, c3.end - 0.3)), text_box(paint_on(None, c3, st, c3.end - 0.01))
    gr = (g1[2] - g1[0]) / (g0[2] - g0[0])
    assert 1.15 < gr < 1.32, (gr, g0, g1)
    print(f"✓ golpe final: «{c3.text(' ')}» (acaba antes del corte de los {CUT} s) crece ×{gr:.2f} al final; "
          "«SIGUE ASÍ.» no")

    # 6) Visor: la capa se repinta cuando aparece una palabra y no repinta si nada cambia
    item = SubtitleItem()
    item.set_state(c1, st, 0.94)
    k1 = item._key
    item.set_state(c1, st, 0.96)
    assert item._key != k1
    item.set_state(c1, st, 1.10)
    k2 = item._key
    item.set_state(c1, st, 1.20)
    assert item._key == k2, "sin cambios, sin repintar"
    print("✓ visor: se repinta al aparecer cada palabra (y no cuando no cambia nada)")

    # 7) Exportación = visor (fotograma a fotograma)
    mp4 = os.path.join(out, "neon.mp4")
    base = os.path.join(out, "sin_subtitulos.mp4")
    t0 = time.time()
    for path, subs in ((mp4, True), (base, False)):
        args, _t = build_command(p, ExportOptions(path=path, width=W, height=H, fps=FPS, encoder="cpu",
                                                  bitrate_mbps=16, subtitles=subs, max_quality=True),
                                 ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    from editoria.export.ffmpeg_export import subs_dir
    sdir = subs_dir(os.path.join(out, "f.txt"))
    pngs = [f for f in os.listdir(sdir) if f.endswith(".png")]
    alto = QImage(os.path.join(sdir, "sub_00001.png")).height()
    assert alto < H * 0.4, f"las imágenes deberían ir recortadas a la franja del texto ({alto} de {H} px)"
    print(f"  (exportado en {time.time() - t0:.1f} s; {len(pngs)} imágenes de subtítulos de {W}×{alto} px, en su "
          "propia carpeta)")
    checks = {15: "estirón", 28: "1 palabra", 29: "2 palabras", 75: "color a medias", 84: "magenta",
              145: "golpe", 190: "otra frase", 60: "entre frases"}
    fe, fb = frames(ff, mp4, sorted(checks)), frames(ff, base, sorted(checks))
    worst = 0.0
    for n, what in sorted(checks.items()):
        t = n / FPS
        k = max(i for i, c in enumerate(cues) if c.start <= t + 1e-9) if any(c.start <= t for c in cues) else -1
        cue = cues[k] if k >= 0 and t < cues[k].end else None
        vis = paint_on(fb[n], cue, st, t) if cue is not None else fb[n]
        d = np.abs(vis.astype(int) - fe[n].astype(int))
        box = text_box(vis, fb[n]) or text_box(fe[n], fb[n])
        if box is None:
            assert d.mean() < 1.0, (n, d.mean())
            continue
        x0, y0, x1, y1 = box
        sub = d[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8]
        m, p95 = float(sub.mean()), float(np.percentile(sub.max(-1), 95))
        worst = max(worst, m)
        assert m < 4.0 and p95 < 30, f"fotograma {n} ({what}): visor y exportación distintos (media {m:.1f}, p95 {p95})"
        eb = text_box(fe[n], fb[n])
        assert eb is not None and abs(eb[0] - x0) <= 3 and abs(eb[2] - x1) <= 3, (n, what, eb, box)
    assert text_box(fe[60], fb[60]) is None, "entre frases no hay texto"
    print(f"✓ exportación = visor en {len(checks)} fotogramas (estirón, palabra a palabra, color, golpe, entre "
          f"frases): diferencia media ≤ {worst:.1f}/255")

    # 7b) Como la ventana Exportar: build_command SIN dibujar (raster=False) y las imágenes en segundo plano
    from editoria.ui import export_runner
    import shutil
    shutil.rmtree(sdir, ignore_errors=True)
    mp4b = os.path.join(out, "neon_segundo_plano.mp4")
    script = os.path.join(out, "g.txt")
    ob = ExportOptions(path=mp4b, width=W, height=H, fps=FPS, encoder="cpu", bitrate_mbps=16, max_quality=True)
    t0 = time.time()
    args, _t = build_command(p, ob, ff, script, raster=False)
    dt_ui = time.time() - t0
    assert not os.path.exists(os.path.join(subs_dir(script), "sub_00001.png")), "no debería dibujar en esa llamada"
    proc = export_runner.make_single(p, ob, script)
    assert isinstance(proc, export_runner.SubsFirstProcess)
    res, prog = [], []
    proc.finished.connect(lambda c, s: res.append(c))
    proc.readyReadStandardOutput.connect(lambda: prog.append(proc.readAllStandardOutput()))
    export_runner.start(proc, args, ob)
    t1 = time.time()
    while not res and time.time() - t1 < 120:
        pump(app, 0.05)
    assert res == [0], (res, b"".join(prog)[-600:])
    fs = frames(ff, mp4b, [29, 84, 145])
    for n in (29, 84, 145):
        assert np.abs(fs[n].astype(int) - fe[n].astype(int)).mean() < 0.5, n
    export_runner.cleanup(script)
    assert not os.path.exists(subs_dir(script)), "la carpeta de las imágenes se borra al terminar"
    print(f"✓ como la ventana Exportar: la llamada previa no dibuja nada ({dt_ui * 1000:.0f} ms), las imágenes se "
          "hacen en segundo plano con progreso, sale igual y su carpeta se borra al acabar")
    # Cancelar mientras dibuja: termina con error de «subtítulos» (la ventana no reintenta con el procesador)
    proc = export_runner.make_single(p, ob, script)
    res = []
    proc.finished.connect(lambda c, s: res.append(c))
    export_runner.start(proc, args, ob)
    proc.kill()
    t1 = time.time()
    while not res and time.time() - t1 < 30:
        pump(app, 0.05)
    assert res and res[0] != 0 and proc.subs_failed, (res, proc.subs_failed)
    export_runner.cleanup(script)
    assert not os.path.exists(subs_dir(script))
    print("✓ cancelar mientras se dibujan: para enseguida, marca que fallaron los subtítulos y se limpia")

    # 📸 Fotograma (y la captura de Claude): a mitad de una frase que empezó antes del tramo, igual que el video;
    # no deja la carpeta de imágenes junto al PNG
    from editoria.core.still import render_frame
    png = os.path.join(out, "fotograma.png")
    render_frame(p, 1.6, png, ff)
    assert not os.path.exists(os.path.splitext(png)[0] + ".filtro_subs"), "la carpeta de imágenes debe borrarse"
    foto = qimg_to_np(QImage(png))
    ref = frames(ff, mp4, [48])[48]
    bx = text_box(ref, frames(ff, base, [48])[48])
    dif = float(np.abs(foto[bx[1]:bx[3], bx[0]:bx[2]].astype(int) - ref[bx[1]:bx[3], bx[0]:bx[2]].astype(int)).mean())
    assert dif < 4.0, f"el fotograma no coincide con el video ({dif:.1f})"
    print(f"✓ 📸 fotograma a mitad de una frase (empezó antes del tramo): igual que el video (diferencia {dif:.1f}) y "
          "sin carpetas de más")

    # 7c) En paralelo, con un límite de trozo A MITAD de «¿POR QUÉ?»: sigue igual que de una vez
    from editoria.export.parallel import ParallelExport
    mp4p = os.path.join(out, "neon_trozos.mp4")
    work = os.path.join(out, "trozos")
    op = ExportOptions(path=mp4p, width=W, height=H, fps=FPS, encoder="cpu", bitrate_mbps=16, max_quality=True)
    ParallelExport(p, op, ff, work, [(0.0, 2.4), (2.4, 10.0)], 10.0).run()
    idx = [70, 72, 73, 75, 80, 84, 90, 145]
    fp, f1 = frames(ff, mp4p, idx), frames(ff, mp4, idx)
    peor = max(float(np.abs(fp[n].astype(int) - f1[n].astype(int)).mean()) for n in idx)
    assert peor < 1.0, f"por trozos sale distinto ({peor:.2f})"
    print(f"✓ exportación por trozos con el corte a mitad de una frase: igual que de una vez (diferencia ≤ "
          f"{peor:.2f}/255; la frase no vuelve a empezar ni repite el estirón)")

    # 7d) Golpe final: solo los cambios de plano de verdad (no los cortes de «eliminar silencios» ni lo pequeño)
    from editoria.core.model import Clip, KIND_VIDEO, MediaItem, Project, Track, new_id
    q = Project(width=W, height=H, fps=float(FPS))
    tq = Track(new_id(), TRACK_VIDEO, "V1")
    tq2 = Track(new_id(), TRACK_VIDEO, "V2")
    q.tracks += [tq, tq2]
    ma = MediaItem(new_id(), planos[0], KIND_VIDEO, "a", duration=CUT, width=W, height=H, fps=FPS, probed=True)
    mb = MediaItem(new_id(), planos[1], KIND_VIDEO, "b", duration=10 - CUT, width=W, height=H, fps=FPS, probed=True)
    q.media.update({ma.id: ma, mb.id: mb})
    for c in (Clip(new_id(), ma.id, tq.id, 0.0, 0.0, 1.5), Clip(new_id(), ma.id, tq.id, 1.5, 2.1, 1.5),
              Clip(new_id(), mb.id, tq.id, 3.0, 0.0, 2.0),
              Clip(new_id(), mb.id, tq2.id, 0.5, 0.0, 1.0, layout={"x": 0.6, "y": 0.6, "w": 0.3, "h": 0.3})):
        q.clips[c.id] = c
    assert SUBS.cut_times(q) == [3.0, 5.0], SUBS.cut_times(q)
    print("✓ golpe final: cuentan los cambios de plano (3 s) y el final; no la unión de un corte de silencio (1,5 s) "
          "ni una imagen pequeña encima")

    # 8) Panel: el preset trae las casillas encendidas; se pueden quitar; otro estilo las apaga
    from editoria.ui.subtitles_panel import SubtitlesPanel
    panel = SubtitlesPanel(ctrl)
    panel.refresh()
    assert panel.fx_color.isChecked() and panel.fx_stretch.isChecked() and panel.fx_punch.isChecked()
    assert panel.anim.currentData() == "words" and panel.glow.value() > 0
    assert panel.fx_stretch.toolTip() and panel.fx_punch.toolTip() and panel.fx_color.toolTip()
    panel.fx_stretch.setChecked(False)
    assert ctrl.project.subtitles.fx_stretch is False
    assert SUBS.scale_at(c1, ctrl.project.subtitles, c1.start) == (1.0, 1.0)
    panel.preset.setCurrentText("YouTube clásico")
    panel._apply_preset()
    panel.refresh()
    s2 = ctrl.project.subtitles
    assert s2.glow == 0 and not (s2.fx_color or s2.fx_stretch or s2.fx_punch) and s2.outline > 0
    assert not SUBS.needs_raster(s2), "el estilo clásico sigue exportándose con .ass"
    assert not panel.fx_punch.isChecked()
    panel.preset.setCurrentText(SUBS.NEON)
    panel._apply_preset()
    s3 = ctrl.project.subtitles
    assert s3.glow > 0 and s3.outline == 0 and s3.animation == "none" and not s3.fx_punch
    print("✓ panel: «Neón palabra a palabra» trae las 3 casillas; se quitan una a una; otro estilo las apaga")
    ctrl.undo_stack.setClean()
    print("TODO OK")


if __name__ == "__main__":
    main()
