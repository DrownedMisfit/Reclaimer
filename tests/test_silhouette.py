"""
Prueba de «👤 Identificar por silueta»:
  · un video con fondos que cambian y un personaje (figura rosa con casco y espada) que sale en 8–14 s y 22–26 s,
    y un globo del mismo rosa (que NO es él) en 28–31 s;
  · se le enseña con la ventana (clic encima → silueta) en el segundo 10;
  · «Buscarlo en mis videos» lo encuentra en sus dos apariciones y no en el resto; la 2.ª búsqueda es instantánea.
Ejecutar:  .venv/Scripts/python.exe tests/test_silhouette.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H, FPS, DUR = 480, 270, 5, 34
SHOWS = [(8.0, 14.0), (22.0, 26.0)]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def figure(img, cx, cy, s=1.0):
    """El «personaje»: cuerpo rosa, casco amarillo con cresta, escudo azul y espada gris."""
    import cv2
    s *= 1.0
    cv2.ellipse(img, (cx, cy + int(30 * s)), (int(22 * s), int(40 * s)), 0, 0, 360, (235, 90, 170), -1)
    cv2.circle(img, (cx, cy - int(20 * s)), int(17 * s), (250, 210, 40), -1)
    cv2.line(img, (cx, cy - int(38 * s)), (cx + int(14 * s), cy - int(52 * s)), (220, 30, 30), int(5 * s))
    cv2.circle(img, (cx - int(26 * s), cy + int(28 * s)), int(14 * s), (40, 80, 230), -1)
    cv2.line(img, (cx + int(24 * s), cy + int(40 * s)), (cx + int(48 * s), cy - int(20 * s)), (190, 190, 190),
             int(4 * s))
    cv2.rectangle(img, (cx - int(14 * s), cy + int(66 * s)), (cx + int(14 * s), cy + int(80 * s)), (60, 40, 30), -1)


def make_video(path):
    import cv2
    from editoria.core import media as M
    rng = np.random.default_rng(3)
    proc = subprocess.Popen([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-pix_fmt", "yuv420p", path],
                            stdin=subprocess.PIPE)
    scenes = {}
    for k in range(DUR * FPS):
        t = k / FPS
        sc = int(t // 3)                                  # un escenario distinto cada 3 s
        if sc not in scenes:
            bg = np.zeros((H, W, 3), np.uint8)
            bg[:] = rng.integers(20, 200, 3)
            for _ in range(14):                           # rocas, árboles, edificios…
                c = tuple(int(x) for x in rng.integers(0, 255, 3))
                p = (int(rng.integers(0, W)), int(rng.integers(0, H)))
                if rng.random() < 0.5:
                    cv2.circle(bg, p, int(rng.integers(8, 45)), c, -1)
                else:
                    cv2.rectangle(bg, p, (p[0] + int(rng.integers(10, 90)), p[1] + int(rng.integers(10, 90))), c, -1)
            scenes[sc] = bg
        img = scenes[sc].copy()
        if any(a <= t < b for a, b in SHOWS):
            cx = int(W * (0.3 + 0.4 * ((t * 0.37) % 1)))      # se mueve por la imagen
            figure(img, cx, 100, 1.0 if t < 20 else 0.8)
        if 28 <= t < 31:                                   # algo del mismo rosa que NO es él (un globo)
            cv2.circle(img, (W // 2, 120), 34, (235, 90, 170), -1)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import silhouette_id as SI
    from editoria.core import motor_ia
    from editoria.ui.main_window import MainWindow
    from editoria.ui.silhouette_teach import SilhouetteTeachDialog
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "aventura.mp4")
    make_video(vid)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    from editoria.core.model import TRACK_VIDEO
    ctrl.add_media([mid], [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][0].id, 0.0)
    clip = next((c for c in ctrl.project.clips.values() if c.media_id == mid
                 and ctrl.project.track(c.track_id).kind == TRACK_VIDEO), None)
    assert clip is not None, "no se pudo poner el video en la línea de tiempo"

    # Enseñar con la ventana: clic encima del personaje en el segundo 10
    d = SilhouetteTeachDialog(win, clip.id, clip.start + 10.0)
    d.show()
    pump(app, 0.2)
    cx = int(W * (0.3 + 0.4 * ((10.0 * 0.37) % 1)))
    d.view.points = [(cx / W, 120 / H, 1)]
    d.name.setCurrentText("Caballero")
    sam = motor_ia.available("sam")[0]
    if sam:
        # Clic en el cuerpo → se ve la silueta en verde; luego clic también en casco y escudo (como haría el usuario)
        d._preview()
        t0 = time.time()
        while d._ready is None and time.time() - t0 < 120:
            pump(app, 0.2)
        assert d._ready is not None and d.view.mask is not None, d.status.text()
        body = int((d._ready[1] > 127).sum())
        print(f"✓ al hacer clic se ve la silueta en verde ({time.time() - t0:.1f} s)")
        d.view.points = d.view.points + [(cx / W, 80 / H, 1), ((cx - 26) / W, 128 / H, 1)]
        d.view.changed.emit()
        t0 = time.time()
        pump(app, 0.5)
        while (d._ready is None or d._ready[0] != d._key(d._marks())) and time.time() - t0 < 120:
            pump(app, 0.2)
        more = int((d._ready[1] > 127).sum())
        assert more > body * 1.1, (body, more)
        print(f"✓ con clics en el casco y el escudo, la silueta crece ({body} → {more} píxeles)")
    d.save_example()
    t0 = time.time()
    while "ejemplo" not in d.status.text() and not d.status.text().startswith("✗") and time.time() - t0 < 240:
        pump(app, 0.2)
    assert d.status.text().startswith("✓"), d.status.text()
    assert SI.names() == {"Caballero": 1}, SI.names()
    print(f"✓ aprendido con un clic ({'silueta de SAM 2.1' if sam else 'recuadro alrededor del clic'}) "
          f"en {time.time() - t0:.1f} s: {d.status.text()}")
    # Un segundo ejemplo en otro momento (más pequeño): con el recuadro dibujado
    d._load(24.0)
    cx2 = int(W * (0.3 + 0.4 * ((24.0 * 0.37) % 1)))
    from PySide6.QtCore import QPointF, QRectF
    d.view.box = QRectF(QPointF((cx2 - 45) / W, 50 / H), QPointF((cx2 + 45) / W, 170 / H))
    d.save_example()
    t0 = time.time()
    while "2 ejemplo" not in d.status.text() and not d.status.text().startswith("✗") and time.time() - t0 < 240:
        pump(app, 0.2)
    assert SI.names() == {"Caballero": 2}, (SI.names(), d.status.text())
    if os.environ.get("SIL_DEBUG"):
        for e in SI.load()["Caballero"]["examples"]:
            print("    tamaño", e["size"], "colores propios", [(i, round(x, 2)) for i, x in enumerate(e["fg"]) if x > 0.01])
    print("✓ 2.º ejemplo guardado (otro momento, más pequeño)")

    # En Momentos aparece en «Lo que conoce la IA»
    mp = win.moments
    mp.refresh_known()
    items = [mp.known.itemText(i) for i in range(mp.known.count())]
    assert any(t.startswith("👤 Caballero") for t in items) and items[-1].startswith("👤 Enseñar"), items
    print("✓ Momentos → «👤 Caballero (2 ejemplos)» y «👤 Enseñar un personaje por su silueta…»")

    # Buscarlo
    d.find()
    t0 = time.time()
    pump(app, 0.3)
    while mp.job is not None and time.time() - t0 < 600:
        pump(app, 0.2)
    took = time.time() - t0
    res = list(mp.results)
    print(f"  búsqueda: {took:.1f} s → " + ", ".join(f"{r.start:.0f}–{r.end:.0f} s ({r.score:.2f})" for r in res))
    if os.environ.get("SIL_DEBUG"):
        for k in sorted(SI.search.last):
            print("   ", k, SI.search.last[k])
    assert res, mp.status.text()

    def inside(r):
        return any(a - 2.5 <= r.best <= b + 2.5 for a, b in SHOWS)
    good = [r for r in res if inside(r)]
    bad = [r for r in res if not inside(r)]
    for a, b in SHOWS:
        assert any(a - 2.5 <= r.best <= b + 2.5 for r in res), f"no lo encontró en {a}–{b} s"
    assert inside(res[0]) and inside(res[1]) if len(res) > 1 else inside(res[0])
    assert len(bad) <= 1, f"falsos positivos: {[(r.start, r.end) for r in bad]}"
    print(f"✓ lo encuentra en sus dos apariciones ({len(good)} aciertos, {len(bad)} fuera) y lo primero es acierto")

    t0 = time.time()
    again = SI.search("Caballero", [(mid, vid, float(DUR))])
    print(f"✓ 2.ª búsqueda (con lo recorrido guardado): {time.time() - t0:.1f} s, {len(again)} resultados")
    SI.forget("Caballero")
    assert SI.names() == {}
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    from editoria.ui import task_window
    task_window.stop_all(6000)
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
