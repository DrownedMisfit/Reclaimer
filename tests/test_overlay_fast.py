"""
Prueba de las imágenes encima de un video (editoria/core/overlay.py + controller.add_image_overlay / set_image_style):
  · soltar una imagen en V2, encima de V1, en un momento con voz → dura hasta que termina la frase («El combate se siente
    bastante lento»); estilo por defecto (centrada al 70 % del alto, sombra, entrada con escala 92 %→100 % y
    fundido, salida con fundido); el video de V1 se desenfoca SOLO en ese tramo (V1 se corta ahí);
  · «Esquina superior derecha», «Pantalla completa» y «Sin animación» cambian la colocación y quitan el desenfoque;
  · ⏱ Ajustar a la frase vuelve a calcular la duración; sin transcripción, 5 s; sin video debajo, como siempre;
  · Ctrl+Z deshace el paso completo y Ctrl+Y/rehacer lo devuelve;
  · exportar un tramo corto con FFmpeg funciona y la imagen sale en pantalla durante la frase.
Sin ventanas visibles. Ejecutar:  .venv/Scripts/python.exe tests/test_overlay_fast.py <carpeta_salida>
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H = 640, 360
FRASE = (7.1, 9.72)            # «El combate se siente bastante lento.» (en el archivo de prueba)


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def wait(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def red_share(rgb: np.ndarray) -> float:
    return float(((rgb[..., 0] > 160) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)).mean())


def frame(ff: str, path: str, t: float) -> np.ndarray:
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3)


def setup(app, out: str, tag: str, with_words: bool = True):
    """Proyecto nuevo: V1 = video de fondo con la narración en A1 (con su transcripción); V2 = la imagen roja."""
    from editoria.core import media as M
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    ff = M.ffmpeg()
    words = json.load(open(os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json"),
                           encoding="utf-8"))["words"]
    wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    d = os.path.join(out, tag)
    os.makedirs(d, exist_ok=True)
    vid = os.path.join(d, "fondo.mp4")
    png = os.path.join(d, "rojo.png")
    if not os.path.exists(vid):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=30",
                        "-pix_fmt", "yuv420p", vid], check=True)
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180",
                        "-frames:v", "1", png], check=True)
    ctrl = ProjectController()
    ctrl.project.width, ctrl.project.height = W, H
    while len([t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO]) < 2:
        ctrl.add_track(TRACK_VIDEO)
    bid, nid, iid = ctrl.import_now([vid, wav, png])
    wait(app, ctrl)
    p = ctrl.project
    if with_words:
        p.transcripts[nid] = {"words": words}
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    top, bot = vids[0], vids[-1]
    audio = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([bid], bot.id, 0.0)
    ctrl.add_media([nid], audio.id, 0.0)
    return ctrl, ff, bot, top, iid


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    atexit.register(shutil.rmtree, out, True)
    app = QApplication.instance() or QApplication(sys.argv)

    from editoria.core import overlay
    from editoria.core.model import KIND_IMAGE
    from editoria.export.ffmpeg_export import ExportOptions, build_command

    # ------------------------------------------------ reglas puras de la frase
    words = json.load(open(os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json"),
                           encoding="utf-8"))["words"]
    run = overlay.phrase_run(words, 8.0)
    check(run is not None and abs(run[0] - FRASE[0]) < 1e-6 and abs(run[1] - FRASE[1]) < 1e-6,
          f"la frase de 8 s es «El combate se siente bastante lento» ({run})")
    check(overlay.phrase_run(words, 5.5) is None, "en una pausa larga (5,5 s) no hay frase")
    check(overlay.phrase_run(words, 3.8) is not None, "pausa corta tras «análisis.» sigue en la frase")

    # ------------------------------------------------ A) imagen encima de V1 con voz
    ctrl, ff, bot, top, iid = setup(app, out, "a")
    i0 = ctrl.undo_stack.index()
    ids = ctrl.add_image_overlay([iid], top.id, 8.0)
    check(bool(ids), "la imagen se coloca encima del video")
    p = ctrl.project
    ov_id = ids[0]
    ov = p.clips[ov_id]
    check(ov.track_id == top.id, "la imagen queda en V2")
    check(abs(ov.duration - max(1.5, FRASE[1] - 8.0)) < 0.02,
          f"dura hasta que termina la frase, desde donde se soltó ({ov.duration:.2f} s)")
    check(ov.layout is not None and abs(ov.layout["w"] - 0.9) < 1e-6 and abs(ov.layout["h"] - 0.7) < 1e-6,
          "estilo por defecto: centrada, caja del 70 % del alto")
    check(len(ov.layout_kf) == 2 and abs(ov.layout_kf[0]["w"] - 0.9 * 0.92) < 1e-3 and ov.layout_kf[0]["t"] == 0,
          "entra con escala 92 % → 100 %")
    check(ov.fx.get("enter", {}).get("from") == "fade" and abs(ov.fx["enter"]["dur"] - 0.25) < 1e-6,
          "fundido de entrada de 0,25 s")
    check("shadow" in ov.fx, "con sombra")
    check(ov.op_kf and ov.op_kf[-1]["v"] == 0.0, "sale con fundido")
    blurred = [c for c in p.clips_on(bot.id) if (c.fx or {}).get("blur")]
    check(len(p.clips_on(bot.id)) == 3, f"V1 se corta en el tramo de la imagen ({len(p.clips_on(bot.id))} clips)")
    check(len(blurred) == 1 and abs(blurred[0].start - ov.start) < 1e-3 and abs(blurred[0].end - ov.end) < 1e-3,
          "el video de V1 se desenfoca SOLO mientras dura la imagen")
    check(abs(blurred[0].fx["blur"] - overlay.BLUR) < 1e-9, "desenfoque por el efecto de siempre (sin tocar el resto)")

    # estilos: colocación y desenfoque
    ctrl.set_image_style([ov_id], "corner")
    ov = ctrl.project.clips[ov_id]
    check(abs(ov.layout["x"] - 0.62) < 1e-3 and not ov.layout_kf, "«Esquina superior derecha»: colocación de esquina")
    check(not any((c.fx or {}).get("blur") for c in ctrl.project.clips_on(bot.id)),
          "al cambiar de estilo, el video de debajo vuelve a verse nítido")
    ctrl.set_image_style([ov_id], "left")
    check(abs(ctrl.project.clips[ov_id].layout["x"] - 0.03) < 1e-3, "«Costado izquierdo» cambia la colocación")
    ctrl.set_image_style([ov_id], "full")
    ov = ctrl.project.clips[ov_id]
    check(ov.layout is None and not ov.op_kf and "shadow" not in ov.fx, "«Pantalla completa»: sin marco ni sombra")
    ctrl.set_image_style([ov_id], "none")
    ov = ctrl.project.clips[ov_id]
    check("enter" not in ov.fx and "shadow" not in ov.fx and not ov.layout_kf, "«Sin animación»: sin entrada ni sombra")
    ctrl.set_image_style([ov_id], "auto")
    check(any((c.fx or {}).get("blur") for c in ctrl.project.clips_on(bot.id)), "volver al estilo automático desenfoca otra vez")

    # ⏱ Ajustar a la frase: se recalcula después de cambiar la duración a mano
    ctrl.set_clip_props([ov_id], "Duración", duration=1.0)
    ctrl.set_image_style([ov_id], "phrase")
    ov = ctrl.project.clips[ov_id]
    check(abs(ov.duration - max(1.5, FRASE[1] - ov.start)) < 0.02,
          f"⏱ Ajustar a la frase: hasta que termina la frase → {ov.duration:.2f} s")

    # Ctrl+Z deshace solo el último paso (⏱ Ajustar a la frase); rehacer lo devuelve
    ctrl.undo_stack.undo()
    check(abs(ctrl.project.clips[ov_id].duration - 1.0) < 1e-6, "Ctrl+Z deshace solo el último paso")
    ctrl.undo_stack.redo()
    ovr = ctrl.project.clips[ov_id]
    check(abs(ovr.duration - max(1.5, FRASE[1] - ovr.start)) < 0.02, "rehacer lo devuelve")
    i_end = ctrl.undo_stack.index()
    ctrl.undo_stack.setIndex(i0)        # deshacer todo el paso de soltar la imagen (un solo paso de Ctrl+Z)
    check(ov_id not in ctrl.project.clips and len(ctrl.project.clips_on(bot.id)) == 1,
          "deshacer el paso de soltar quita la imagen y devuelve V1 a un solo clip")
    ctrl.undo_stack.setIndex(i_end)
    check(ov_id in ctrl.project.clips and len(ctrl.project.clips_on(bot.id)) == 3, "rehacer todo la devuelve")

    # exportar un tramo corto: la imagen sale durante la frase y no hay fallo de FFmpeg
    vid = os.path.join(out, "salida.mp4")
    args, _ = build_command(ctrl.project, ExportOptions(path=vid, width=W, height=H, fps=30.0, encoder="cpu",
                                                        bitrate_mbps=4, subtitles=False, loudnorm=False,
                                                        duration=12.0),
                            ff, os.path.join(out, "lista.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    check(r.returncode == 0 and os.path.exists(vid), "exportar 12 s con la imagen encima funciona")
    if r.returncode != 0:
        print(r.stderr[-800:])
    # (el fondo de prueba tiene rojos de por sí: se compara con el mismo fotograma del video sin imagen)
    base = red_share(frame(ff, os.path.join(out, "a", "fondo.mp4"), 11.6))
    s_in = red_share(frame(ff, vid, 9.0)) - base
    s_out = red_share(frame(ff, vid, 11.6)) - base
    check(s_in > 0.2, f"en la exportación, la imagen se ve durante la frase (+{s_in:.2f})")
    check(abs(s_out) < 0.02, f"y ya no se ve al terminar la frase ({s_out:+.3f})")

    # ------------------------------------------------ B) sin transcripción → 5 s y el mismo estilo
    ctrl, ff, bot, top, iid = setup(app, out, "b", with_words=False)
    ids = ctrl.add_image_overlay([iid], top.id, 8.0)
    ov = ctrl.project.clips[ids[0]]
    check(abs(ov.duration - 5.0) < 1e-6, "sin transcripción, la duración por defecto (5 s)")
    check(ov.layout is not None and "shadow" in ov.fx, "sin transcripción, el mismo estilo")

    # ------------------------------------------------ C) sin video debajo → se añade como siempre
    ctrl, ff, bot, top, iid = setup(app, out, "c")
    ids = ctrl.add_image_overlay([iid], bot.id, 20.0)     # V1 es la de abajo: no hay nada debajo
    ov = ctrl.project.clips[ids[0]]
    check(abs(ov.duration - 5.0) < 1e-6 and "ovl" not in (ov.fx or {}) and "shadow" not in (ov.fx or {}),
          "sin video debajo: se añade como siempre (5 s, sin estilo)")
    check(not any((c.fx or {}).get("blur") for c in ctrl.project.clips.values()), "y no desenfoca nada")

    print("TODO OK")


if __name__ == "__main__":
    main()
