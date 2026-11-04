"""
Prueba de las pistas sencillas «¿gameplay o cinemática? ¿primera o tercera persona?» (sin modelos pesados):
HUD fijo en los bordes → gameplay; arma fija abajo en el centro → primera persona; barras negras → cinemática.
Ejecutar:  .venv/Scripts/python.exe tests/test_shot_cues.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.ai import clip_analysis as CA
    from editoria.ai import shot_cues as SC
    from editoria.core import media as M
    ff = M.ffmpeg()

    def mk(name, graph):
        p = os.path.join(out, name)
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", graph, "-t", "12",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p], check=True)
        return p
    hud = ("drawbox=x=20:y=20:w=180:h=22:color=red:t=fill,drawbox=x=20:y=20:w=180:h=22:color=white:t=3,"
           "drawbox=x=520:y=250:w=100:h=90:color=white:t=4,drawbox=x=540:y=270:w=20:h=20:color=yellow:t=fill")
    gp = mk("gameplay.mp4", "mandelbrot=s=640x360:r=30," + hud)
    fp = mk("primera.mp4", "mandelbrot=s=640x360:r=30," + hud + ",drawbox=x=270:y=240:w=110:h=120:color=gray:t=fill,"
            "drawbox=x=270:y=240:w=110:h=120:color=white:t=4,drawbox=x=300:y=260:w=50:h=60:color=black:t=4")
    cn = mk("cine.mp4", "mandelbrot=s=640x360:r=30,drawbox=x=0:y=0:w=640:h=46:color=black:t=fill,"
            "drawbox=x=0:y=314:w=640:h=46:color=black:t=fill")
    times = CA.sample_times(12.0)
    g, f, c = SC.cues(gp, times), SC.cues(fp, times), SC.cues(cn, times)
    assert g["type"] == "Gameplay", g
    assert f["type"] == "Gameplay" and f["view"] == "primera persona", f
    assert c["type"] == "Cinemáticas" and c["view"] is None, c
    print(f"✓ HUD fijo → gameplay · arma abajo al centro → primera persona · barras negras → cinemática "
          f"(hud {g['hud']}, primera {f['first']}, barras {c['letterbox']})")
    # se guarda: la segunda vez no se vuelve a calcular
    cu = CA.simple_cues(fp, 12.0)
    assert cu["view"] == "primera persona"
    assert any(n.endswith(".json") for n in os.listdir(os.path.join(os.environ["EDITORIA_DATOS"], "cache", "pistas")))
    print("✓ el resultado se guarda (la próxima vez es instantáneo)")
    print("TODO OK")


if __name__ == "__main__":
    main()
