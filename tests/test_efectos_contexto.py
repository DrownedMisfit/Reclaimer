"""
Prueba de «✨ Efectos según lo que dices» (Efectos → ✨ Lo que dices, y clic derecho en la selección):
  · una frase triste sobre un clip y otra neutra sobre otro → 🖤 gris solo en el triste (con su motivo);
  · «👤 Solo cuando nombro a alguien» respeta que se nombre a alguien;
  · una foto con una cara (detector SIMULADO: no se descarga nada) → 🔍 zoom hacia ella, una sola vez (caché);
  · aplicar = UN Ctrl+Z; 🩶 desaturado con «⚡ Aplicar sin preguntar»; clip largo = solo el tramo de la frase;
  · el clic derecho en la selección tiene la opción y la lanza.
Usa una carpeta de datos TEMPORAL. Ejecutar:  .venv/Scripts/python.exe tests/test_efectos_contexto.py <salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import context_effects as CE  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core import transform  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def silence_wav(path, secs):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * secs))


def words_of(text, t0, step=0.4):
    out, t = [], t0
    for w in text.split():
        out.append([round(t, 3), round(t + step - 0.05, 3), w])
        t += step
    return out


CALLS = []


def fake_detector(img):
    """Detector simulado: una cara arriba a la derecha (lo que diría OpenCV en una foto con una persona)."""
    CALLS.append(img.shape)
    assert max(img.shape[:2]) <= CE.MAX_LADO, img.shape      # se mira PEQUEÑA
    return [(0.6, 0.2, 0.15, 0.2, 0.95)]


def wait_job(app, panel, secs=30):
    t0 = time.time()
    pump(app, 0.05)
    while panel._ctx_job is not None and time.time() - t0 < secs:
        pump(app, 0.05)
    assert panel._ctx_job is None, "la búsqueda no terminó"


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    CE.DETECTOR = fake_detector

    # --- 0) El léxico solo (instantáneo): negaciones y tipos
    hits = CE.tone_hits([(0, .3, "No"), (.4, .7, "murió"), (.8, 1.1, "nadie."), (2, 2.3, "Fue"), (2.4, 2.7, "una"),
                         (2.8, 3.1, "tragedia.")])
    assert [h["word"] for h in hits] == ["tragedia"], hits
    hits = CE.tone_hits([(0, .3, "Hubo"), (.4, .7, "despidos"), (.8, 1.1, "masivos.")])
    assert hits and hits[0]["cat"] == "dificil", hits
    assert not CE.tone_hits([(0, .3, "El"), (.4, .7, "juego"), (.8, 1.1, "es"), (1.2, 1.5, "divertido.")])
    print("✓ léxico: «no murió nadie» no cuenta, «tragedia» triste, «despidos» tema difícil, lo neutro nada")

    # --- Material: dos videos de 4 s, una foto y una narración en silencio
    ff = media_tools.ffmpeg()
    vids = []
    for name, src in (("ctx_a.mp4", "testsrc2=s=640x360:r=30:d=4"), ("ctx_b.mp4", "smptebars=s=640x360:r=30:d=4")):
        path = os.path.join(out, name)
        if not os.path.exists(path):
            r = subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "4",
                                "-c:v", "libx264", "-preset", "ultrafast", path], capture_output=True)
            assert r.returncode == 0, r.stderr
        vids.append(path)
    import cv2
    foto = os.path.join(out, "ctx_foto.png")
    img = np.full((960, 1280, 3), 150, np.uint8)
    cv2.circle(img, (860, 300), 110, (180, 200, 230), -1)          # (una «cara» dibujada)
    cv2.imencode(".png", img)[1].tofile(foto)
    narr = os.path.join(out, "ctx_narracion.wav")
    silence_wav(narr, 14.0)

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    ctrl, panel, tl = win.ctrl, win.effects, win.timeline
    p = ctrl.project
    ids = ctrl.import_paths(vids + [foto, narr])
    while ctrl.analyzing:
        pump(app, 0.1)
    by = {p.media[i].name: i for i in ids}
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is None)
    for k, name in enumerate(("ctx_a.mp4", "ctx_b.mp4", "ctx_foto.png")):
        ctrl.add_media([by[name]], v1.id, 4.0 * k)
        c = max(p.clips_on(v1.id), key=lambda x: x.start)
        ctrl.set_clip_props([c.id], "dur", duration=4.0)
    for c in list(p.clips.values()):           # sin el sonido de los videos (más simple)
        if c.track_id != v1.id:
            ctrl.delete_clips([c.id])
    ctrl.add_media([by["ctx_narracion.wav"]], a1.id, 0.0)
    clip = {p.media[c.media_id].name: c.id for c in p.clips_on(v1.id)}
    A, B, F = clip["ctx_a.mp4"], clip["ctx_b.mp4"], clip["ctx_foto.png"]

    def say(sad_text):
        w = words_of(sad_text, 0.4) + words_of("Ahora vamos con el modo historia.", 4.8)
        ctrl.set_transcript(by["ctx_narracion.wav"], {"language": "es", "words": w})

    say("Lamentablemente el creador falleció ayer.")
    panel.ctx_mode.setCurrentIndex(panel.ctx_mode.findData("bw"))
    panel.ctx_name.setChecked(False)
    panel.ctx_zoom.setChecked(True)
    panel.ctx_star.setChecked(False)
    panel.ctx_direct.setChecked(False)

    # --- 1) Clic derecho en la selección → «✨ Efectos según lo que digo…» → propuestas
    tl.set_selection([A, B, F])
    found = {}
    menu = tl.build_clip_menu(p.clips[A], tl.mapToGlobal(QPoint(300, 200)))    # (armado, sin enseñarlo)
    for act in menu.actions():
        if act.text().startswith("✨ Efectos según lo que digo"):
            found["act"] = act
            found["tip"] = act.toolTip()
    assert "act" in found, "falta la opción en el clic derecho"
    assert "gris" in found["tip"] and "zoom" in found["tip"]
    found["act"].trigger()
    wait_job(app, panel)
    props = panel.ctx_props
    grises = [x for x in props if x["kind"] == "gris"]
    zooms = [x for x in props if x["kind"] == "zoom"]
    assert [x["clip_id"] for x in grises] == [A], props
    assert "falleció" in grises[0]["reason"] and "triste" in grises[0]["reason"], grises[0]["reason"]
    assert panel.ctx_tree.topLevelItemCount() == len(props)
    assert "falleció" in panel.ctx_tree.topLevelItem(0).toolTip(2)
    assert [x["clip_id"] for x in zooms] == [F], zooms
    kf = zooms[0]["zoom_kf"]
    assert kf[0]["z"] == 1.0 and kf[-1]["z"] > 1.15 and abs(kf[-1]["x"] - 0.675) < 0.01 and kf[-1]["y"] < 0.4, kf
    assert len(CALLS) == 1, CALLS
    print(f"✓ clic derecho → propuestas: 🖤 gris solo en el clip triste («{grises[0]['reason']}») y 🔍 zoom hacia "
          "la cara de la foto")

    # --- 2) «👤 Solo cuando nombro a alguien»
    panel.ctx_name.setChecked(True)
    panel.propose_context_fx([A, B, F])
    wait_job(app, panel)
    assert not [x for x in panel.ctx_props if x["kind"] == "gris"], panel.ctx_props
    assert len(CALLS) == 1, "la foto se volvió a analizar (debía salir de la caché)"
    say("Lamentablemente Pedro Gómez falleció ayer.")
    panel.propose_context_fx([A, B, F])
    wait_job(app, panel)
    grises = [x for x in panel.ctx_props if x["kind"] == "gris"]
    assert [x["clip_id"] for x in grises] == [A] and "Pedro" in grises[0]["reason"], panel.ctx_props
    print(f"✓ «solo cuando nombro a alguien»: sin nombre no propone; con nombre sí («{grises[0]['reason']}»); "
          "la foto sale de la caché")

    # --- 3) Aplicar = un Ctrl+Z
    n0 = ctrl.undo_stack.index()
    panel.ctx_apply()
    assert ctrl.undo_stack.index() == n0 + 1
    assert (p.clips[A].fx or {}).get("bw") == 1.0 and not (p.clips[B].fx or {}).get("bw")
    assert transform.is_zoomed(p.clips[F].zoom_kf) and p.clips[F].zoom_kf[-1]["x"] > 0.6
    assert not panel.ctx_props and panel.ctx_tree.topLevelItemCount() == 0
    ctrl.undo_stack.undo()
    assert not (p.clips[A].fx or {}).get("bw") and not transform.is_zoomed(p.clips[F].zoom_kf)
    print("✓ «✓ Aplicar las marcadas»: gris + zoom en un solo paso; un Ctrl+Z lo quita todo")

    # --- 4) 🩶 Desaturado + «⚡ Aplicar sin preguntar» (y desmarcar una propuesta)
    panel.ctx_name.setChecked(False)
    panel.ctx_mode.setCurrentIndex(panel.ctx_mode.findData("desat"))
    panel.ctx_direct.setChecked(True)
    n0 = ctrl.undo_stack.index()
    tl.set_selection([A, B])
    panel.propose_context_fx()                 # (la selección del momento)
    wait_job(app, panel)
    assert ctrl.undo_stack.index() == n0 + 1
    assert abs(float(p.clips[A].color["saturation"]) - CE.DESAT) < 1e-6 and not (p.clips[A].fx or {}).get("bw")
    assert not (p.clips[B].color or {}).get("saturation")
    assert not transform.is_zoomed(p.clips[F].zoom_kf), "la foto no estaba elegida"
    ctrl.undo_stack.undo()
    assert not (p.clips[A].color or {}).get("saturation")
    panel.ctx_direct.setChecked(False)
    panel.ctx_mode.setCurrentIndex(panel.ctx_mode.findData("bw"))
    tl.set_selection([A, B, F])
    panel.propose_context_fx()
    wait_job(app, panel)
    for i, x in enumerate(panel.ctx_props):
        if x["kind"] == "zoom":
            panel.ctx_tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
    panel.ctx_apply()
    assert (p.clips[A].fx or {}).get("bw") and not transform.is_zoomed(p.clips[F].zoom_kf)
    assert [x["kind"] for x in panel.ctx_props] == ["zoom"]
    panel.ctx_reject()
    assert not panel.ctx_props
    ctrl.undo_stack.undo()
    print("✓ 🩶 desaturado con «⚡ Aplicar sin preguntar» (un Ctrl+Z); solo se aplican las marcadas; ✗ descartar")

    # --- 5) Clip largo: solo el tramo de la frase (se corta al aplicar)
    ctrl.add_track(TRACK_VIDEO)
    v2 = [t for t in p.tracks if t.kind == TRACK_VIDEO][0]       # (la nueva va arriba)
    assert v2.id != v1.id
    ctrl.add_media([by["ctx_foto.png"]], v2.id, 20.0)
    largo = max(p.clips_on(v2.id), key=lambda x: x.start)
    ctrl.set_clip_props([largo.id], "dur", duration=20.0)
    largo = p.clips[largo.id]
    # (narración de partida o ficción: palabras ambiguas sueltas no bastan)
    for frase in ("El personaje muere en la guerra.", "Fue una pérdida de tiempo.", "Llegamos al cierre del video.",
                  "Lo hice por accidente."):
        assert not CE.tone_proposals(p, [largo], [tuple(w) for w in words_of(frase, 30.0)]), frase
    words = [tuple(w) for w in words_of("Hoy hablamos del juego.", 22.0) + words_of("Hubo una ola de despidos.", 30.0)]
    props = CE.tone_proposals(p, [largo], words)
    assert len(props) == 1 and props[0]["span"], props
    a, b = props[0]["span"]
    assert 29.5 <= a <= 30.1 and 31.4 <= b <= 32.6, props[0]["span"]
    # foto larga cortada por el gris: sin zoom de toda la foto (ni en la propuesta ni al aplicar)
    zoom = CE.zoom_proposals(p, [largo], {p.media[largo.media_id].path: {"x": .6, "y": .2, "w": .15, "h": .2,
                                                                         "kind": "cara"}})
    assert len(zoom) == 1 and not [x for x in CE.merge(props, zoom, []) if x["kind"] == "zoom"]
    n0 = ctrl.undo_stack.index()
    ctrl.apply_context_effects(props + zoom)
    assert ctrl.undo_stack.index() == n0 + 1
    piezas = sorted(p.clips_on(v2.id), key=lambda c: c.start)
    assert len(piezas) == 3, piezas
    assert [bool((c.fx or {}).get("bw")) for c in piezas] == [False, True, False]
    assert not any(transform.is_zoomed(c.zoom_kf) for c in piezas)
    ctrl.undo_stack.undo()
    assert len(p.clips_on(v2.id)) == 1
    print(f"✓ clip largo: solo el tramo de la frase ({a:.1f}–{b:.1f} s) se pone gris (se corta en 3, un Ctrl+Z), "
          "sin zoom partido; «muere en la guerra», «pérdida de tiempo», «cierre del video» no cuentan")

    # --- 6) Elegiste solo sonido: aviso, sin mirar toda la línea de tiempo
    snd = [c.id for c in p.clips.values() if p.track(c.track_id).kind == TRACK_AUDIO]
    assert snd
    tl.set_selection(snd)
    panel.ctx_props = []
    panel.propose_context_fx()
    assert panel._ctx_job is None and not panel.ctx_props
    assert "Elige clips de video o imagen" in panel.ctx_status.text(), panel.ctx_status.text()
    print("✓ con solo sonido elegido avisa «Elige clips de video o imagen» (no analiza todo)")

    ctrl.undo_stack.setClean()                 # (sin «¿guardar los cambios?» al cerrar)
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("\nTODO OK")


if __name__ == "__main__":
    main()
