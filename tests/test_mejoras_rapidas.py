"""
Mejoras aprendidas de Shotcut, Kdenlive y OpenShot (sin ventanas visibles):
  · 📷 copias ligeras de la cámara (GoPro .LRV, DJI .LRF, carpeta «Proxy»): se usan tal cual, sin codificar;
  · copias a medias de una sesión anterior: se borran al abrir (las recientes no);
  · ⌨ exportar e importar los atajos en un archivo;
  · ⏱ el código de tiempo avanza de uno en uno a 23,976, 29,97 y 59,94 fps (sin repetir ni saltar fotogramas);
  · 🎬 Escenas en la barra: cortar, cortar también lo suave o solo poner marcadores.
Ejecutar:  .venv/Scripts/python.exe tests/test_mejoras_rapidas.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as _M  # noqa: E402

_FF = _M.ffmpeg()                       # (antes de cambiar LOCALAPPDATA: FFmpeg de winget se busca ahí)
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMP = tempfile.mkdtemp(prefix="reclaimer_rapidas_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
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

from editoria.core import proxies as PX  # noqa: E402
from editoria.core.paths import cache_dir  # noqa: E402


def _archivo(ruta, datos=b"x" * 4096):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    open(ruta, "wb").write(datos)


def _video(ruta, w, h, dur, audio=True):
    import subprocess
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    args = [_FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={dur}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=440:d={dur}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast"] + (["-c:a", "aac", "-shortest"] if audio else []) + \
        ["-f", "mp4", ruta]
    subprocess.run(args, check=True, creationflags=_M.NO_WINDOW)


def main():
    cam = os.path.join(_TMP, "camara")
    gopro = os.path.join(cam, "GX010123.MP4")
    _video(gopro, 640, 360, 3)
    _video(os.path.join(cam, "GL010123.LRV"), 320, 180, 3)
    corta = os.path.join(cam, "GX020001.MP4")
    _video(corta, 640, 360, 3)
    _video(os.path.join(cam, "GL020001.LRV"), 320, 180, 1)          # truncada (corte de batería)
    muda = os.path.join(cam, "GX030001.MP4")
    _video(muda, 640, 360, 3)
    _video(os.path.join(cam, "GL030001.LRV"), 320, 180, 3, audio=False)
    dji = os.path.join(cam, "DJI_0001.MP4")
    _archivo(dji)
    _archivo(os.path.join(cam, "DJI_0001.LRF"), b"lrf" * 1000)
    otro = os.path.join(cam, "toma.mov")
    _archivo(otro)
    _archivo(os.path.join(cam, "Proxy", "toma.mp4"), b"prx" * 1000)
    sin = os.path.join(cam, "sin_copia.mp4")
    _archivo(sin)
    assert PX.camera_proxy(gopro).endswith("GL010123.LRV")
    assert PX.camera_proxy(dji).endswith("DJI_0001.LRF")
    assert PX.camera_proxy(otro).endswith(os.path.join("Proxy", "toma.mp4"))
    assert PX.camera_proxy(sin) is None
    real_ff = PX.media_tools.ffmpeg
    PX.media_tools.ffmpeg = lambda: (_ for _ in ()).throw(AssertionError("no debe codificar"))
    rutas = PX.make_proxies(gopro, 360, ["half", "quarter"])
    PX.media_tools.ffmpeg = real_ff
    lrv = open(os.path.join(cam, "GL010123.LRV"), "rb").read()
    assert len(rutas) == 2 and all(open(r, "rb").read() == lrv for r in rutas), rutas
    print("✓ 📷 se usan las copias ligeras que ya graba la cámara (GoPro .LRV, DJI .LRF, carpeta «Proxy») sin "
          "codificar nada")
    assert PX._camera_ok(corta, PX.camera_proxy(corta), 360, ["half"]) == [], "truncada: no sirve"
    assert PX._camera_ok(muda, PX.camera_proxy(muda), 360, ["half"]) == [], "sin audio: no sirve"
    assert PX._camera_ok(gopro, PX.camera_proxy(gopro), 2160, ["half", "quarter"]) == [], "muy pequeña para 4K"
    print("✓ 📷 una copia de cámara truncada, sin audio o demasiado pequeña no se usa (se crea la nuestra)")

    viejo = cache_dir("proxies") / "abc_half.mp4.tmp.mp4"
    nuevo = cache_dir("proxies") / "def_half.mp4.tmp.mp4"
    viejo.write_bytes(b"0")
    nuevo.write_bytes(b"0")
    t = time.time() - 3600
    os.utime(viejo, (t, t))
    assert PX.clean_leftovers() == 1 and not viejo.exists() and nuevo.exists()
    print("✓ las copias a medias de una sesión anterior se borran al abrir (las que se están haciendo, no)")

    from editoria.ui.common import fmt_tc
    for fps in (23.976, 29.97, 59.94, 24.0, 30.0):
        vistos = []
        for k in range(0, int(fps * 3600 * 2), 7):          # 2 horas, uno de cada 7 fotogramas
            vistos.append(fmt_tc(k / fps, fps))
        assert len(set(vistos)) == len(vistos), f"{fps}: códigos repetidos"
        f = [int(x.split(":")[3]) for x in (fmt_tc(k / fps, fps) for k in range(200))]
        nominal = round(fps)
        assert all((b - a) % nominal == 1 for a, b in zip(f, f[1:])), f"{fps}: salta o repite fotogramas"
    print("✓ ⏱ a 23,976 / 29,97 / 59,94 fps el código de tiempo avanza de uno en uno (2 h sin repetidos)")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    p = Project.new()
    p.fps = 29.97
    v1 = next(tr for tr in p.tracks if tr.kind == "video")
    p.media["m"] = MediaItem(id="m", path=gopro, kind=KIND_VIDEO, name="g.mp4", duration=60.0, probed=True)
    p.clips["c"] = Clip("c", "m", v1.id, 0.0, 0.0, 60.0)
    win.ctrl._replace(p, None)
    win.engine.seek(10.0)
    t0 = win.engine.time
    win.engine.step(1)
    assert abs((win.engine.time - t0) - 1 / 29.97) < 1e-6
    print("✓ ⏱ un paso (→) a 29,97 fps avanza exactamente un fotograma")

    from editoria.ui.shortcuts_dialog import ShortcutsDialog
    from PySide6.QtGui import QKeySequence
    d = ShortcutsDialog(win.shortcut_actions, win)
    clave = next(iter(win.shortcut_actions))
    d.set_shortcut(clave, QKeySequence("Ctrl+Alt+Shift+F9"), ask=False)
    ruta = d.export_file(os.path.join(_TMP, "atajos.json"))
    assert ruta and os.path.isfile(ruta)
    d._reset(clave)
    assert win.shortcut_actions[clave][0].shortcut() != QKeySequence("Ctrl+Alt+Shift+F9")
    import json
    data = json.load(open(ruta, encoding="utf-8"))
    data["atajos"]["Menú que no existe/Orden"] = "Ctrl+1"
    json.dump(data, open(ruta, "w", encoding="utf-8"))
    n = d.import_file(ruta)
    assert n >= 1 and win.shortcut_actions[clave][0].shortcut() == QKeySequence("Ctrl+Alt+Shift+F9"), n
    assert "no hay aquí" in d.msg.text(), d.msg.text()
    antes = win.shortcut_actions[clave][0].shortcut()
    json.dump({"tipo": "atajos", "atajos": {clave: "hola mundo"}}, open(ruta, "w", encoding="utf-8"))
    assert d.import_file(ruta) == 0 and win.shortcut_actions[clave][0].shortcut() == antes, "no válido: se queda"
    assert "no válidos" in d.msg.text(), d.msg.text()
    open(os.path.join(_TMP, "malo.json"), "w").write("{}")
    assert d.import_file(os.path.join(_TMP, "malo.json")) == 0 and "No pude leerlo" in d.msg.text()
    d._reset(clave)
    print("✓ ⌨ los atajos se exportan a un archivo y se importan (las órdenes que no existen se saltan)")

    acts = [a.text() for a in win.btn_scenes.menu().actions() if a.text()]
    assert len(acts) == 3 and any("marcador" in a for a in acts), acts
    pedidos = []
    win.cut_scenes = lambda ids, sens="normal", markers=False: pedidos.append((ids, sens, markers))
    win.timeline.set_selection(["c"])
    next(a for a in win.btn_scenes.menu().actions() if "marcador" in a.text()).trigger()
    assert pedidos == [(["c"], "normal", True)], pedidos
    print("✓ 🎬 Escenas en la barra: cortar, cortar también lo suave o solo un marcador en cada cambio")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
