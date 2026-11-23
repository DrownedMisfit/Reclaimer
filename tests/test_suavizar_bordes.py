"""
Prueba de 🌗 «Suavizar bordes» (22/11): lo recortado se desvanece a transparente en vez de un corte seco.
  · Miniatura: el PNG de la capa recortada con bordes suaves tiene un alfa que baja poco a poco en el borde, y el
    contorno no se pinta mientras haya desvanecido;
  · editor: al exportar, una imagen recortada con «suavizar» pasa del negro del fondo a su color en un degradado.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_suavizar_bordes.py <carpeta>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else _TMP
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from editoria.core import media as M
    from editoria.core import thumbnail as T
    ruta = os.path.join(out, "rojo.png")
    Image.fromarray(np.full((180, 320, 3), (230, 20, 20), np.uint8)).save(ruta)

    # --- Miniatura: capa recortada con bordes suaves → alfa en degradado; el contorno no se pinta
    doc = T.new_doc("youtube")
    lay = T.image_layer(ruta, doc)
    lay["crop"] = [0.2, 0.0, 1.0, 1.0]
    lay["feather"] = 0.2
    img, cw, ch = T.render_layer(lay)
    rgba = T.qimage_to_rgba(img)
    fila = rgba[rgba.shape[0] // 2, :, 3].astype(int)
    medios = [a for a in fila if 10 < a < 245]
    assert len(set(medios)) >= 5 and fila.max() == 255, ("el alfa baja poco a poco", fila[:40])
    pos = fila[: len(fila) // 2]
    assert all(b >= a - 1 for a, b in zip(pos, pos[1:])), "sube sin saltos desde el borde"
    con_contorno = dict(lay, outline=dict(lay["outline"], on=True, width=12, color="#00ff00"))
    img2, _w, _h = T.render_layer(con_contorno)
    assert img2.size() == img.size(), "con bordes suaves el contorno no se pinta (ni ocupa sitio)"
    print(f"✓ Miniatura: alfa del borde en degradado ({len(set(medios))} niveles); el contorno no se pinta")

    # --- Editor: exportar una imagen recortada con «suavizar»
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ctrl = ProjectController()
    p = ctrl.project
    p.width, p.height = 320, 180
    (mid,) = ctrl.import_now([ruta])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    (cid,) = [i for i in ctrl.add_media([mid], v1.id, 0.0) if p.clips[i].media_id == mid]
    c = p.clips[cid]
    c.duration = 1.0
    c.layout = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "contain", "crop": {"l": 0.25}}
    c.fx = {"suavizar": 0.1}
    mp4 = os.path.join(out, "suave.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                              loudnorm=False), M.ffmpeg(), os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    fr = M.frame_rgb(mp4, 0.5, 320).astype(int)
    rojo = fr[90, :, 0]
    assert rojo[70] < 40 and rojo[200] > 180, ("fuera del recorte negro, dentro rojo", rojo[60:110])
    rampa = [v for v in rojo[80:110] if 40 < v < 180]
    assert len(rampa) >= 6, ("del negro al rojo en un degradado, no de golpe", rojo[75:110])
    print(f"✓ exportar: el borde recortado pasa a negro en un degradado de {len(rampa)} px")
    print("TODO OK")


if __name__ == "__main__":
    main()
