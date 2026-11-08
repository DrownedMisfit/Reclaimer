"""
Prueba de «🔑 Palabras clave»: TODO en UNA sola pista de video (sin ventanas, QT_QPA_PLATFORM=offscreen).
  1) «Añadir en la palabra clave» con 3 marcas muy juntas (10.0, 11.0, 12.5), en modo «entero» y en «partes»:
     todos los clips de video en UNA pista (encima de la principal), ninguno se solapa, cada uno empieza en su
     marca, en silencio y sin clip de audio nuevo; un solo Ctrl+Z.
  2) Una segunda tanda en una marca que cae DENTRO de un clip ya puesto: va a la MISMA pista y corta al anterior
     (el anterior termina donde empieza el nuevo).
  3) Las imágenes también van a esa pista (en una mezcla de imagen y vídeo).
  4) Un solo Ctrl+Z deshace cada tanda.
  5) «📍 Poner donde lo dices» (place_clip_at) usa la misma pista.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_keyword_one_track.py
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project  # noqa: E402

EPS = 1e-3


def _proyecto() -> Project:
    """Pistas V2, V1 (principal) y A1. Una base en V1 de 0 a 60 s (fija el final de la línea de tiempo)."""
    p = Project.new()
    p.media["vid"] = MediaItem(id="vid", path=os.path.join(_TMP, "broll.mp4"), kind=KIND_VIDEO, name="broll.mp4",
                               duration=20.0, width=1920, height=1080, fps=60.0, probed=True)
    p.media["fondo"] = MediaItem(id="fondo", path=os.path.join(_TMP, "fondo.mp4"), kind=KIND_VIDEO,
                                 name="fondo.mp4", duration=120.0, width=1920, height=1080, fps=60.0, probed=True)
    p.media["img"] = MediaItem(id="img", path=os.path.join(_TMP, "foto.png"), kind=KIND_IMAGE, name="foto.png",
                               width=1920, height=1080, probed=True)
    v2, v1, a1 = p.tracks
    p.clips["base"] = Clip("base", "fondo", v1.id, 0.0, 0.0, 60.0)
    return p


def _ctrl() -> ProjectController:
    ctrl = ProjectController()
    ctrl.project = _proyecto()
    return ctrl


def _ids(ctrl) -> set:
    return set(ctrl.project.clips)


def _nuevos(ctrl, antes: set) -> list[Clip]:
    return sorted((c for cid, c in ctrl.project.clips.items() if cid not in antes), key=lambda c: c.start)


def _sin_solape(ctrl, tid: str):
    cs = ctrl.project.clips_on(tid)
    for x, y in zip(cs, cs[1:]):
        assert x.end <= y.start + EPS, ("se solapan en la misma pista", x.start, x.end, y.start, y.end)


def _solo_video_nuevo(ctrl, nuevos: list[Clip]):
    for c in nuevos:
        m = ctrl.project.media[c.media_id]
        assert m.kind != KIND_AUDIO, "no debe entrar ningún audio"
        assert c.volume == 0.0, ("debe ir en silencio", c.volume)
        assert c.link == "", ("no debe ir vinculado a un clip de audio", c.link)
        assert ctrl.project.track(c.track_id).kind == TRACK_VIDEO


def prueba_tanda(modo: str):
    ctrl = _ctrl()
    v2, v1, a1 = ctrl.project.tracks
    antes = _ids(ctrl)
    pila = ctrl.undo_stack.index()
    ids = ctrl.add_media_at_times(["vid"], [10.0, 11.0, 12.5], modo=modo)
    assert ctrl.undo_stack.index() == pila + 1, "debe ser UN solo paso de deshacer"
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 3 and len(ids or []) == 3, (modo, len(nuevos), ids)
    tids = {c.track_id for c in nuevos}
    assert len(tids) == 1, ("los clips se han repartido en pistas distintas", tids)
    tid = tids.pop()
    assert tid != v1.id and ctrl.project.track_index(tid) < ctrl.project.track_index(v1.id), "debe ir encima de V1"
    assert [round(c.start, 3) for c in nuevos] == [10.0, 11.0, 12.5], [c.start for c in nuevos]
    _sin_solape(ctrl, tid)
    _solo_video_nuevo(ctrl, nuevos)
    assert ctrl.project.clips["base"].track_id == v1.id and ctrl.project.clips["base"].duration == 60.0
    print(f"✓ modo «{modo}»: 3 clips en una sola pista, sin solape, en sus marcas, en silencio, sin audio")


def prueba_segunda_tanda():
    ctrl = _ctrl()
    v2, v1, a1 = ctrl.project.tracks
    ctrl.add_media_at_times(["vid"], [10.0, 11.0, 12.5], modo="entero")
    primera = _nuevos(ctrl, {"base"})
    tid = primera[0].track_id
    a1_clip, a2_clip, a3_clip = primera
    antes = _ids(ctrl)
    ctrl.add_media_at_times(["vid"], [10.5], modo="entero")       # cae DENTRO del primer clip
    nuevo = _nuevos(ctrl, antes)
    assert len(nuevo) == 1 and nuevo[0].track_id == tid, ("la segunda tanda debe ir a la misma pista", nuevo)
    _sin_solape(ctrl, tid)
    assert abs(nuevo[0].start - 10.5) < EPS, nuevo[0].start
    assert abs(ctrl.project.clips[a1_clip.id].end - 10.5) < EPS, ("el anterior debe acabar donde empieza el nuevo",
                                                                  ctrl.project.clips[a1_clip.id].end)
    assert a2_clip.id not in ctrl.project.clips, "el clip de 11 s cae del todo dentro del nuevo: se quita"
    assert abs(ctrl.project.clips[a3_clip.id].start - nuevo[0].end) < EPS, (
        "el clip de 12.5 s debe quedar detrás del nuevo", ctrl.project.clips[a3_clip.id].start, nuevo[0].end)
    assert ctrl.project.clips[a3_clip.id].source_in > 0, "el resto del clip cortado debe seguir su trozo del archivo"
    print("✓ segunda tanda dentro de un clip: misma pista, corta al anterior, el resto queda detrás")


def prueba_imagenes_y_undo():
    ctrl = _ctrl()
    v2, v1, a1 = ctrl.project.tracks
    ctrl.add_media_at_times(["vid"], [10.0, 11.0], modo="entero")
    tid = _nuevos(ctrl, {"base"})[0].track_id
    antes = _ids(ctrl)
    pila = ctrl.undo_stack.index()
    ctrl.add_media_at_times(["img", "vid"], [50.0, 52.0], modo="entero")   # una imagen y un vídeo
    assert ctrl.undo_stack.index() == pila + 1, "la mezcla debe ser UN solo paso de deshacer"
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 2, [c.media_id for c in nuevos]
    assert {c.track_id for c in nuevos} == {tid}, ("las imágenes deben ir a la misma pista", [c.track_id for c in nuevos])
    _sin_solape(ctrl, tid)
    img = next(c for c in nuevos if c.media_id == "img")
    assert abs(img.start - 50.0) < EPS and img.duration > 0.5, (img.start, img.duration)
    _solo_video_nuevo(ctrl, nuevos)
    print("✓ imágenes y vídeo juntos: una sola pista, en su marca, sin audio")

    # un solo Ctrl+Z deshace la tanda entera
    ctrl.undo_stack.undo()
    assert _ids(ctrl) == antes, "un Ctrl+Z debe quitar toda la tanda"
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == {"base"}, ("el segundo Ctrl+Z debe deshacer la tanda anterior", set(ctrl.project.clips))
    print("✓ un solo Ctrl+Z por tanda")


def prueba_poner_donde_lo_dices():
    ctrl = _ctrl()
    v2, v1, a1 = ctrl.project.tracks
    ctrl.add_media_at_times(["vid"], [10.0], modo="entero")
    tid = _nuevos(ctrl, {"base"})[0].track_id
    antes = _ids(ctrl)
    res = ctrl.place_clip_at("vid", [30.0, 33.0], [2.0, 2.0], 0.0)
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 2 and len(res) == 2, (len(nuevos), res)
    assert {c.track_id for c in nuevos} == {tid}, ("«Poner donde lo dices» debe usar la misma pista",
                                                   [c.track_id for c in nuevos], tid)
    _sin_solape(ctrl, tid)
    _solo_video_nuevo(ctrl, nuevos)
    assert all(c.note.startswith("🔑") for c in nuevos), [c.note for c in nuevos]
    print("✓ «📍 Poner donde lo dices» usa la misma pista de palabras clave")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    prueba_tanda("entero")
    prueba_tanda("partes")
    prueba_segunda_tanda()
    prueba_imagenes_y_undo()
    prueba_poner_donde_lo_dices()
    app.processEvents()
    print("TODO OK")


if __name__ == "__main__":
    main()
