"""
Prueba de 🟦 GENERADORES (color sólido y degradados) y 🎨 CAPA DE AJUSTE:
  · un color sólido en el cabezal: pista de arriba libre, un solo paso de Ctrl+Z, sale en la biblioteca
    («Generadores») y al exportar se ve; «Cambiar color» a un degradado (y Ctrl+Z vuelve);
  · capa de ajuste encima de un video: blanco y negro SOLO mientras dura (lo de antes y después, en color), en el
    visor (la capa de debajo recibe el efecto) y al exportar; no tapa nada; con fundido de entrada el efecto llega
    poco a poco (no funde a negro);
  · si el PNG del generador falta (otro PC), se vuelve a crear al abrir el proyecto.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_generators.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import generators as G
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    red = os.path.join(out, "rojo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xd02020:s=320x180:d=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", red], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p, eng = win.ctrl, win.ctrl.project, win.engine
    p.width, p.height = 320, 180
    (rid,) = ctrl.import_now([red])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([rid], v1.id, 0.0)

    def export(name, t):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
        return [M.frame_rgb(mp4, x, 320).astype(int) for x in t]

    # 1) color sólido
    n0 = ctrl.undo_stack.count()
    gid = ctrl.add_generator({"kind": "solid", "c1": "#2040e0"}, 1.0, 2.0)
    g = p.clips[gid]
    m = p.media_of(g)
    assert ctrl.undo_stack.count() == n0 + 1 and p.track(g.track_id).kind == TRACK_VIDEO and g.track_id != v1.id
    assert m.category == "Generadores" and m.gen["kind"] == "solid" and os.path.exists(m.path), m
    a, b = export("solido.mp4", [0.5, 2.0])
    assert a[90, 160][0] > 170 and b[90, 160][2] > 170 and b[90, 160][0] < 80, (a[90, 160], b[90, 160])
    print(f"✓ color sólido en el cabezal (pista de arriba, «{m.name}» en Generadores) y se exporta")
    ctrl.set_generator([gid], {"kind": "linear", "c1": "#ff0000", "c2": "#00ff00", "angle": 0})
    (fr,) = export("degradado.mp4", [2.0])
    left, right = fr[90, 10], fr[90, 310]
    assert left[0] > 180 and left[1] < 80 and right[1] > 180 and right[0] < 80, (left, right)
    ctrl.undo_stack.undo()
    pump(app, 0.1)
    assert p.media_of(p.clips[gid]).gen["kind"] == "solid"
    print("✓ «Cambiar color» → degradado de rojo a verde (de izquierda a derecha) · Ctrl+Z vuelve")
    ctrl.delete_clips([gid])

    # 2) capa de ajuste: blanco y negro solo mientras dura
    aid = ctrl.add_generator({"kind": "adjust"}, 2.0, 2.0)
    ctrl.set_clip_props([aid], "B/N", fx={"bw": True})
    am = p.media_of(p.clips[aid])
    assert G.is_adjust(am) and p.clips[aid].layout.get("bg") == "none"
    before, during, after = export("ajuste.mp4", [1.0, 3.0, 5.0])
    for fr in (before, after):
        assert fr[90, 160][0] > 170 and fr[90, 160][1] < 80, fr[90, 160]
    r_, g_, b_ = during[90, 160][:3]
    assert abs(r_ - g_) < 18 and abs(g_ - b_) < 18 and 30 < r_ < 160, during[90, 160]
    print(f"✓ capa de ajuste B/N: antes y después en color, durante en gris ({r_},{g_},{b_}) · no tapa nada")
    eng.seek(3.0)
    pump(app, 0.4)
    lower = win.preview.canvas.layers[v1.id]
    eff = lower.box.graphicsEffect()
    assert eff is not None and getattr(eff, "post", None) and eff.post[0]["bw"], "en el visor, lo de debajo en B/N"
    eng.seek(1.0)
    pump(app, 0.4)
    eff = lower.box.graphicsEffect()
    assert not (eff is not None and getattr(eff, "post", None)), "fuera de la capa de ajuste: sin efecto"
    print("✓ en el visor: la capa de debajo recibe el B/N solo mientras dura la capa de ajuste")
    # fundido de entrada: a mitad del fundido, a medias (ni rojo puro ni gris; no se oscurece a negro)
    ctrl.set_clip_props([aid], "Fundido", fx={"bw": True, "fade_in": 1.0})
    (mid,) = export("ajuste_fundido.mp4", [2.5])
    r_, g_, b_ = mid[90, 160][:3]
    assert r_ > g_ + 30 and r_ < 200 and r_ + g_ + b_ > 150, mid[90, 160]
    print(f"✓ fundido de entrada en la capa de ajuste: el efecto llega poco a poco ({r_},{g_},{b_}), sin negro")
    # color en la capa de ajuste
    ctrl.set_clip_props([aid], "Color", fx={}, color={"saturation": -1.0})
    (fr,) = export("ajuste_color.mp4", [3.0])
    r_, g_, b_ = fr[90, 160][:3]
    assert abs(r_ - g_) < 25, fr[90, 160]
    print("✓ el color de la capa de ajuste (saturación a cero) también se aplica a lo de debajo")

    # 3) el PNG falta (otro PC): se vuelve a crear al abrir
    proj = os.path.join(out, "gen.eia")
    ctrl.add_generator({"kind": "radial", "c1": "#ffffff", "c2": "#000000"}, 6.0, 1.0)
    assert ctrl.save(proj)
    paths = [x.path for x in p.media.values() if x.gen]
    for x in paths:
        os.remove(x)
    ctrl.load(proj)
    pump(app, 0.3)
    p = ctrl.project
    assert all(os.path.exists(x.path) for x in p.media.values() if x.gen) and not ctrl.missing, ctrl.missing
    print("✓ si faltan las imágenes de los generadores, se vuelven a crear al abrir el proyecto")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
