"""
🎞 Motor de video propio (sin ventanas visibles): un video de prueba cuyo brillo dice el número de fotograma.
  · en pausa se ve EXACTAMENTE el fotograma pedido (saltos de pocos ms; lo ya visto sale de la caché al instante);
  · reproduciendo va ~0,6 s por delante;
  · en el visor: con «🎞 Video con motor propio» el fotograma del cabezal llega al mismo video de siempre;
  · el corte entre dos archivos está preparado de antemano (el plano siguiente ya está decodificado);
  · un archivo que no se puede abrir vuelve solo a los reproductores de siempre; apagar la opción, también.
Ejecutar:  .venv/Scripts/python.exe tests/test_motor_video.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMP = tempfile.mkdtemp(prefix="reclaimer_video_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.core.live_video import FrameSource  # noqa: E402

FPS = 30


def video(ruta, dur=6, base=0):
    """Fotograma N con brillo (base + N·4) mod 256: así se sabe qué fotograma se ve."""
    subprocess.run([_FF, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"nullsrc=s=640x360:r={FPS}:d={dur},geq=lum='mod({base}+N*4\\,256)':cb=128:cr=128",
                    "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-g", "48", "-pix_fmt", "yuv420p", ruta],
                   check=True, creationflags=M.NO_WINDOW)


def rgb(y: int) -> int:
    """Luma de rango limitado (16–235) → valor RGB, como lo convierte el decodificador."""
    return int(round(min(255.0, max(0.0, (y - 16) * 255 / 219))))


def brillo(data, w, h):
    k = (h // 2 * w + w // 2) * 4
    return data[k]


def esperar(src, t, max_s=3.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_s:
        fr = src.frame_at(t)
        if fr is not None and abs(fr[0] - t) < 0.5 / FPS + 1e-3:
            return fr, time.perf_counter() - t0
        time.sleep(0.002)
    raise AssertionError(f"no llegó el fotograma de {t}")


def main():
    a = os.path.join(_TMP, "a.mp4")
    b = os.path.join(_TMP, "b.mp4")
    video(a)
    video(b, base=128)
    s = FrameSource(a)
    tiempos = []
    for n in (0, 75, 31, 150, 149, 4):
        t = n / FPS
        s.want(t, False, (320, 180))
        (pts, w, h, data), dt = esperar(s, t)
        tiempos.append(dt)
        esperado = rgb((n * 4) % 256)
        assert abs(brillo(data, w, h) - esperado) <= 3, (n, brillo(data, w, h), esperado)
    print(f"✓ en pausa se ve EXACTAMENTE el fotograma pedido (saltos: {max(tiempos) * 1000:.0f} ms el peor)")
    s.want(75 / FPS, False, (320, 180))
    (_p, _w, _h, _d), dt = esperar(s, 75 / FPS)
    assert dt < 0.005, dt
    print(f"✓ volver a un fotograma ya visto es instantáneo (caché: {dt * 1000:.1f} ms)")
    s.want(2.0, True, (320, 180))
    time.sleep(0.4)
    assert s.frame_at(2.5) is not None and s.frame_at(2.5)[0] >= 2.45, "va por delante al reproducir"
    print("✓ reproduciendo, va por delante del cabezal (0,5 s ya decodificados)")
    s.close()

    # reproducción de verdad: una petición cada 15 ms durante 2,5 s (como el visor)
    for vel in (1.0, 4.0):
        s = FrameSource(a)
        s.want(0.5, False, (320, 180))
        esperar(s, 0.5)
        s0, buenos, n = s.seeks, 0, 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 2.5 / vel:
            t = 0.5 + (time.perf_counter() - t0) * vel
            s.want(t, True, (320, 180))
            fr = s.frame_at(t)
            buenos += fr is not None and abs(fr[0] - t) <= 1.5 / FPS
            n += 1
            time.sleep(0.015)
        s.close()
        assert s.seeks - s0 <= 2 and buenos >= 0.9 * n, (vel, s.seeks - s0, buenos, n)
        print(f"✓ reproduciendo a {vel:g}×: {buenos}/{n} fotogramas a tiempo y {s.seeks - s0} saltos")

    # fps variable (móvil) y archivo que no empieza en 0 (.ts): imagen, sin saltos sin fin
    vfr = os.path.join(_TMP, "vfr.mp4")
    subprocess.run([_FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=4",
                    "-vf", "select='lt(mod(n\,5)\,3)'", "-fps_mode", "vfr", "-c:v", "libx264", "-preset",
                    "ultrafast", vfr], check=True, creationflags=M.NO_WINDOW)
    ts = os.path.join(_TMP, "corte.ts")
    subprocess.run([_FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-output_ts_offset", "11.4", "-f", "mpegts", ts],
                   check=True, creationflags=M.NO_WINDOW)
    for ruta in (vfr, ts):
        s = FrameSource(ruta)
        for t in (0.13, 1.0, 2.71, 3.9):
            s.want(t, False, (320, 180))
            t0 = time.perf_counter()
            while s.frame_at(t) is None and time.perf_counter() - t0 < 2:
                time.sleep(0.005)
            assert s.frame_at(t) is not None and s.frame_at(t)[0] <= t + 0.5 / FPS, (ruta, t)
        time.sleep(0.3)
        n0 = s.seeks
        time.sleep(0.5)
        assert s.seeks == n0 and not s.error, (ruta, s.seeks - n0, s.error)
        s.close()
    print("✓ videos de fps variable (móvil) y archivos .ts que no empiezan en 0: imagen y sin saltos sin fin")
    s = FrameSource(a)
    s.want(7.5, False, (320, 180))                  # más allá del final (el video dura 6 s)
    time.sleep(0.8)
    n0 = s.seeks
    time.sleep(0.8)
    fr = s.frame_at(7.5)
    assert fr is not None and fr[0] > 5.8 and s.seeks == n0, (fr and fr[0], s.seeks - n0)
    s.close()
    print("✓ en pausa más allá del final: el último fotograma, sin saltos en bucle")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow
    from editoria.ui.preview import _OwnVideoLane, _VideoLane
    win = MainWindow()
    eng = win.engine
    win.a_own_video.setChecked(True)
    assert eng._own_video_on() and eng._timer.interval() == 15
    p = Project.new()
    p.fps = FPS
    v1 = next(tr for tr in p.tracks if tr.kind == "video" and tr.name == "V1")
    for mid, ruta in (("ma", a), ("mb", b)):
        p.media[mid] = MediaItem(id=mid, path=ruta, kind=KIND_VIDEO, name=os.path.basename(ruta), duration=6.0,
                                 width=640, height=360, fps=FPS, probed=True)
    p.clips["ca"] = Clip("ca", "ma", v1.id, 0.0, 0.0, 3.0)
    p.clips["cb"] = Clip("cb", "mb", v1.id, 3.0, 1.0, 3.0)
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()

    def visto():
        lane = eng._vlanes.get(v1.id)
        img = lane.layer.videos[lane.active].videoSink().videoFrame().toImage()
        if img.isNull():
            return None
        return img.pixelColor(img.width() // 2, img.height() // 2).red()

    eng.seek(2.0)
    lane = eng._vlanes[v1.id]
    assert isinstance(lane, _OwnVideoLane), type(lane)
    for _ in range(100):
        app.processEvents()
        time.sleep(0.01)
        if visto() is not None and abs(visto() - rgb((60 * 4) % 256)) <= 4:
            break
    assert visto() is not None and abs(visto() - rgb((60 * 4) % 256)) <= 4, visto()
    print("✓ en el visor, el fotograma del cabezal (motor propio) llega al video de siempre")

    eng.seek(2.9)                              # cerca del corte: el plano siguiente se prepara
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)
    eng.seek(3.0)
    app.processEvents()
    nuevo = eng._vlanes[v1.id]
    i = nuevo.active
    assert nuevo.paths[i] == b and not nuevo._pend, ("el plano siguiente ya estaba decodificado", nuevo._pend)
    esperado_b = rgb((128 + 30 * 4) % 256)        # cb empieza en el segundo 1 de b (fotograma 30)
    assert abs(visto() - esperado_b) <= 4, (visto(), esperado_b)
    print("✓ el corte entre dos archivos sale al instante: el plano siguiente ya estaba decodificado")

    p2 = win.ctrl.project
    p2.media["ma"].path = os.path.join(_TMP, "no_es_video.mp4")
    open(p2.media["ma"].path, "wb").write(b"no soy un video")
    eng._vlanes[v1.id].park()
    eng._vlanes.pop(v1.id)
    eng.seek(1.0)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.01)
        eng._sync()
        if isinstance(eng._vlanes.get(v1.id), _VideoLane):
            break
    assert isinstance(eng._vlanes.get(v1.id), _VideoLane)
    print("✓ un archivo que el motor propio no abre vuelve solo a los reproductores de siempre")
    win.a_own_video.setChecked(False)
    eng._sync()
    assert isinstance(eng._vlanes.get(v1.id), _VideoLane) and eng._timer.interval() == 30
    print("✓ apagar «🎞 Video con motor propio» vuelve a los reproductores de siempre al momento")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
