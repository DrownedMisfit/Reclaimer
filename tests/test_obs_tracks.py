"""
Prueba de las PISTAS DE AUDIO SEPARADAS de OBS (micrófono y juego):
  · una grabación con 3 pistas (1 = mezcla, 2 = juego estéreo, 3 = micrófono mono con voz): se reconocen; la mezcla
    sobra; cada pista útil sale a su archivo (copia exacta);
  · al importarla NO se separa nada sola (el usuario no lo pidió); con «⋮ → 🎵 Separar audio» quedan como audios
    del proyecto («Pistas de OBS») y al ponerla en la línea de tiempo: la imagen,
    el juego en una pista y tu voz en «🎙 Micrófono» (con mejora de voz), todo vinculado;
  · solo sonó el juego (pista 1 = 2 y la 3 en silencio): no se separa y te dice por qué;
  · como tu grabación de prueba (solo hablaste, el juego en silencio): sale tu voz sola (para transcribirla);
  · con una sola pista: como siempre.
Ejecutar:  .venv/Scripts/python.exe tests/test_obs_tracks.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402

GAME = "aevalsrc='0.3*sin(2*PI*80*t)+0.15*(random(0)-0.5)|0.3*sin(2*PI*80*t+1.3)+0.15*(random(1)-0.5)':s=48000:d=12"
MIC = "aevalsrc='0.4*sin(2*PI*700*t)*gt(sin(2*PI*1.5*t),0)':s=48000:d=12"     # voz a ratos (mono)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def make(ff, path, mode):
    v = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12"]
    if mode == "obs3":
        args = v + ["-f", "lavfi", "-i", GAME, "-f", "lavfi", "-i", MIC, "-filter_complex",
                    "[1:a]asplit=2[g1][g2];[2:a]pan=stereo|c0=c0|c1=c0,asplit=2[m1][m2];"
                    "[g1][m1]amix=inputs=2:normalize=0[mix]",
                    "-map", "0:v", "-map", "[mix]", "-map", "[g2]", "-map", "[m2]"]
    elif mode == "como_tu_prueba":
        args = v + ["-f", "lavfi", "-i", GAME, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=12",
                    "-filter_complex", "[1:a]asplit=2[a][b]", "-map", "0:v", "-map", "[a]", "-map", "[b]",
                    "-map", "2:a"]
    elif mode == "solo_voz":
        args = v + ["-f", "lavfi", "-i", MIC, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=12",
                    "-filter_complex", "[1:a]pan=stereo|c0=c0|c1=c0,asplit=2[a][b]", "-map", "0:v", "-map", "[a]",
                    "-map", "[b]", "-map", "2:a"]
    else:
        args = v + ["-f", "lavfi", "-i", GAME, "-map", "0:v", "-map", "1:a"]
    subprocess.run([ff, "-nostdin", "-v", "error", "-y"] + args + ["-c:v", "libx264", "-preset", "ultrafast",
                   "-c:a", "aac", "-t", "12", "-pix_fmt", "yuv420p", path], check=True)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import obs_tracks as OT
    from editoria.core.model import KIND_AUDIO, TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    files = {}
    for mode in ("obs3", "como_tu_prueba", "una", "solo_voz"):
        files[mode] = os.path.join(out, f"{mode}.mp4")
        make(ff, files[mode], mode)

    c = OT.classify(files["obs3"])
    assert sorted(c["keep"]) == [(1, "juego"), (2, "voz")], c
    assert "mezcla" in c["note"], c["note"]
    c2 = OT.classify(files["como_tu_prueba"])
    assert c2["keep"] == [] and "silencio" in c2["note"], c2
    c3 = OT.classify(files["solo_voz"])
    assert c3["keep"] == [(1, "voz")], c3
    print(f"✓ reconoce: pista 2 = juego, pista 3 = micrófono; la 1 es la mezcla · solo juego: «{c2['note']}» · "
          f"solo tu voz: «{c3['note']}»")

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    msgs = []
    ctrl.message.connect(msgs.append)
    ids = ctrl.import_now([files["obs3"], files["como_tu_prueba"], files["una"], files["solo_voz"]])
    while ctrl.analyzing:
        pump(app, 0.1)
    pump(app, 0.5)
    assert not any(p.media[i].audio_tracks for i in ids) and not any(
        x.category in ("🎙 Audio de micrófono", "🎮 Audio del juego") for x in p.media.values()), "se separó sola al importar"
    print("✓ al importar no se separa nada sola (solo si lo pides)")
    for i in ids:                                   # «⋮ → 🎵 Separar audio» (lo mismo, sin ventana)
        ctrl.separate_audio_tracks_now(i)
    while ctrl.analyzing:
        pump(app, 0.1)
    m = p.media[ids[0]]
    roles = sorted(t["role"] for t in m.audio_tracks)
    assert roles == ["juego", "voz"], m.audio_tracks
    extra = [p.media[t["media_id"]] for t in m.audio_tracks]
    cats = {t["role"]: p.media[t["media_id"]].category for t in m.audio_tracks}
    assert cats == {"voz": "🎙 Audio de micrófono", "juego": "🎮 Audio del juego"}, cats
    assert all(x.kind == KIND_AUDIO and os.path.exists(x.path) for x in extra)
    assert all("Pistas de OBS" in x.path for x in extra), "en la carpeta de Reclaimer, no junto a tu grabación"
    assert not p.media[ids[1]].audio_tracks and not p.media[ids[2]].audio_tracks
    assert any("no se pueden separar" in x and "silencio" in x for x in msgs), msgs
    sv = p.media[ids[3]].audio_tracks
    assert [t["role"] for t in sv] == ["voz"], sv
    voz = p.media[sv[0]["media_id"]]
    assert voz.path.endswith("Micrófono.m4a") and "Pistas de OBS" in voz.path and os.path.exists(voz.path)
    assert any("tu voz sola" in x for x in msgs), msgs
    print("✓ «Separar audio»: el micrófono en «🎙 Audio de micrófono» y el juego en «🎮 Audio del juego» (archivos en "
          "la carpeta Pistas de OBS de Reclaimer); "
          "si solo hablaste: tu voz sola")

    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    made = ctrl.add_media([ids[0]], v1.id, 0.0)
    vc = next(p.clips[i] for i in made if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    audio = [x for x in p.clips.values() if x.link == vc.link and x.id != vc.id]
    assert len(audio) == 2 and len({x.track_id for x in audio}) == 2, [(x.media_id, x.track_id) for x in audio]
    voice = next(x for x in audio if p.media[x.media_id].path.endswith("Micrófono.m4a"))
    vt = p.track(voice.track_id)
    assert vt.kind == TRACK_AUDIO and vt.role == "voz" and vt.fx, (vt.name, vt.role, vt.fx)
    assert all(abs(x.start - vc.start) < 1e-6 and abs(x.duration - vc.duration) < 1e-6 for x in audio)
    print(f"✓ en la línea de tiempo: imagen + juego + tu voz en «{vt.name}» (con mejora de voz), vinculados")
    ctrl.split_at_times(vc.id, [5.0])
    pieces = [x for x in p.clips.values() if p.media_of(x) and p.media_of(x).id in {t["media_id"] for t in m.audio_tracks}]
    assert len(pieces) == 4, "al cortar, se cortan los tres (vinculados)"
    made2 = ctrl.add_media([ids[2]], v1.id, 20.0)
    assert sum(1 for i in made2 if p.track(p.clips[i].track_id).kind == TRACK_AUDIO) == 1
    made3 = ctrl.add_media([ids[3]], v1.id, 40.0)
    assert sum(1 for i in made3 if p.track(p.clips[i].track_id).kind == TRACK_AUDIO) == 1
    print("✓ cortar corta los tres juntos; un video con una sola pista, como siempre")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
