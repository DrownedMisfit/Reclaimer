"""
🎓 Proyecto de ejemplo (sin ventanas visibles y sin internet: las descargas de Pexels son falsas):
  · se crea con la narración que trae el programa, la música propia (con drop) y los clips «descargados»;
  · cada clip lleva sus créditos al lado y salen en el texto de la descripción;
  · los clips cubren toda la narración, sin su sonido; la música va debajo, más baja;
  · lo ya descargado no se vuelve a bajar; sin internet avisa y no deja nada a medias;
  · desde el menú Ayuda se abre el proyecto y la guía en su lección.
Ejecutar:  .venv/Scripts/python.exe tests/test_proyecto_ejemplo.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()                       # (antes de cambiar LOCALAPPDATA: FFmpeg de winget se busca ahí)
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_ejemplo_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.core import credits  # noqa: E402
from editoria.core import example_project as EX  # noqa: E402
from editoria.core.model import Project  # noqa: E402

FUENTE = os.path.join(_TMP, "fuente.mp4")
subprocess.run([_FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=9", "-c:v", "libx264",
                "-preset", "ultrafast", FUENTE], check=True, creationflags=M.NO_WINDOW)
bajadas: list[str] = []
SIN_INTERNET = False


def _bajar_falso(url, destino, avisar, cancelled):
    if SIN_INTERNET:
        raise OSError("sin conexión")
    bajadas.append(url)
    avisar(1.0)
    shutil.copyfile(FUENTE, destino)


_BAJAR_REAL = EX._bajar
EX._bajar = _bajar_falso


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    dest = os.path.join(_TMP, "Videos", "Reclaimer", "Proyecto de ejemplo")
    pasos = []
    ruta, fallos = EX.build(dest, progress=lambda f, t="": pasos.append((f, t)))
    assert not fallos, fallos
    d = json.load(open(ruta, encoding="utf-8"))
    p = Project.from_dict(d)
    assert len(bajadas) == len(EX.CLIPS) == 5, bajadas
    nombres = sorted(m.name for m in p.media.values())
    assert "narración de ejemplo.m4a" in nombres and "música de ejemplo.m4a" in nombres, nombres
    print("✓ se crea con la narración del programa, la música propia y los 5 clips de Pexels")

    texto = credits.text(credits.collect(p))
    for c in EX.CLIPS:
        assert c["author"] in texto and c["page"] in texto, (c["author"], texto)
    print("✓ cada clip lleva sus créditos (autor y página de Pexels) y salen en la descripción")

    narr = next(m for m in p.media.values() if m.name.startswith("narración"))
    vids = sorted((c for c in p.clips.values() if p.media[c.media_id].kind == "video"), key=lambda c: c.start)
    assert vids and abs(vids[0].start) < 1e-6 and abs(vids[-1].start + vids[-1].duration - narr.duration) < 0.05
    assert all(abs(a.start + a.duration - b.start) < 1e-3 for a, b in zip(vids, vids[1:])), "sin huecos"
    assert all(c.volume == 0 for c in vids), "los clips, sin su sonido"
    mus = next(c for c in p.clips.values() if p.media[c.media_id].name.startswith("música"))
    pista = next(t for t in p.tracks if t.id == mus.track_id)
    assert mus.volume < 1 and pista.role == "musica", (mus.volume, pista.role)
    print(f"✓ {len(vids)} clips cubren los {narr.duration:.0f} s de narración sin huecos ni sonido; la música, debajo "
          "y más baja")

    from editoria.ai import rhythm
    r = rhythm.analyze(os.path.join(dest, "música de ejemplo.m4a"), force=True)
    assert r["drop"] and 15 < r["drop"] < 17 and len(r["beats"]) > 40, (r["drop"], len(r["beats"]))
    print(f"✓ la música tiene ritmo para 🥁: {r['tempo']:.0f} golpes por minuto y el drop en el segundo {r['drop']:.0f}")

    os.remove(ruta)
    bajadas.clear()
    EX.build(dest)
    assert not bajadas, "lo ya descargado no se vuelve a bajar"
    print("✓ lo ya descargado no se vuelve a bajar")

    # reabrir con un clip borrado: se repone sin reescribir el proyecto
    ruta, _ = EX.build(dest)
    antes = os.path.getmtime(ruta)
    os.remove(os.path.join(dest, EX.CLIPS[2]["file"]))
    assert EX.missing(dest)
    bajadas.clear()
    assert EX.repair(dest) == [] and len(bajadas) == 1 and not EX.missing(dest)
    assert os.path.getmtime(ruta) == antes, "repair no toca el .eia"
    print("✓ si falta un clip, se baja solo ese y el proyecto (lo que practicaste) no se toca")

    # un clip dañado de antes (no es un video): se borra y se baja otra vez
    malo = os.path.join(dest, EX.CLIPS[0]["file"])
    with open(malo, "wb") as f:
        f.write(b"<html>" + b"x" * 20000)
    bajadas.clear()
    assert EX.repair(dest) == [] and len(bajadas) == 1 and EX._es_video(malo)
    print("✓ un clip dañado (una página HTML guardada como .mp4) se borra y se baja otra vez")

    # la descarga de verdad (con una conexión falsa): cortada, HTML, error a mitad y cancelada → sin restos
    import urllib.request as UR

    class _Resp:
        def __init__(self, datos, total, error_a_mitad=False):
            self.datos, self.total, self.err, self.leido = datos, total, error_a_mitad, 0
            self.headers = {"Content-Length": str(total)}

        def read(self, n):
            if self.err and self.leido > 0:
                raise ConnectionResetError("se cayó la red")
            t = self.datos[self.leido:self.leido + n]
            self.leido += len(t)
            return t

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    video = open(FUENTE, "rb").read()
    casos = [("cortada", _Resp(video[:300000], len(video)), RuntimeError),
             ("HTML", _Resp(b"<html>" + b"x" * 30000, 30006), RuntimeError),
             ("error a mitad", _Resp(video, len(video), error_a_mitad=True), ConnectionResetError)]
    destino = os.path.join(_TMP, "prueba.mp4")
    for nombre, resp, error in casos:
        UR.urlopen = lambda req, timeout=30, r=resp: r
        try:
            _BAJAR_REAL("https://x/y.mp4", destino, lambda f: None, None)
            raise AssertionError(nombre)
        except error:
            pass
        assert not os.path.exists(destino) and not os.path.exists(destino + ".part"), nombre
    UR.urlopen = lambda req, timeout=30: _Resp(video, len(video))
    from editoria.ai.base import Cancelled
    try:
        _BAJAR_REAL("https://x/y.mp4", destino, lambda f: None, lambda: True)
        raise AssertionError("cancelar")
    except Cancelled:
        pass
    assert not os.path.exists(destino + ".part")
    _BAJAR_REAL("https://x/y.mp4", destino, lambda f: None, None)
    assert EX._es_video(destino)
    print("✓ descarga cortada, página HTML, red caída a mitad o cancelada: no queda nada; completa: se guarda")

    global SIN_INTERNET
    SIN_INTERNET = True
    otro = os.path.join(_TMP, "otro")
    try:
        EX.build(otro)
        raise AssertionError("sin internet debería avisar")
    except RuntimeError as exc:
        assert "internet" in str(exc), exc
    assert not os.path.exists(os.path.join(otro, EX.NOMBRE + ".eia"))
    assert os.path.isfile(os.path.join(otro, "no descargados.txt"))
    assert not [f for f in os.listdir(otro) if f.endswith(".part")]
    print("✓ sin internet avisa («¿sin internet?») y no deja un proyecto a medias")
    SIN_INTERNET = False

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.example_dir = lambda: dest
    win.open_example()
    for _ in range(300):
        pump(app, 0.05)
        if getattr(win, "_example_job", None) is None:
            break
    assert os.path.normcase(win.ctrl.path or "") == os.path.normcase(ruta), win.ctrl.path
    assert win.guide.lesson and win.guide.lesson[0] == "proyecto_ejemplo", win.guide.lesson
    assert any(m.name.startswith("narración") for m in win.ctrl.project.media.values())
    print("✓ Ayuda → «🎓 Proyecto de ejemplo» abre el proyecto y la guía en su lección")
    r = subprocess.run(["git", "-C", _RAIZ, "check-ignore", "-q", EX.NARRACION], creationflags=M.NO_WINDOW)
    assert r.returncode == 1, "la narración del ejemplo tiene que poder subirse (no ignorada en .gitignore)"
    print("✓ la narración del ejemplo no está ignorada por git (va con el programa)")
    nombres_menu = [a.text() for a in win.menuBar().actions() if "Ay" in a.text()]
    ayuda = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Ayuda")
    assert any("Proyecto de ejemplo" in a.text() for a in ayuda.actions()), nombres_menu
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
