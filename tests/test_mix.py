"""
Prueba de 🎛 ANALIZAR Y PROPONER MEZCLA:
  · con transcripción: «hola amigos» → la música baja lo normal; «lo siento hermano» → casi desaparece (y sigue baja
    en el silencio de después); «¡corre, cuidado!» → baja poco; sin voz → a tope;
  · un marcador «música» quita la bajada de ese tramo; una pista bloqueada no se toca;
  · sin transcripción, encuentra la voz por el volumen;
  · la ventana: analizar, quitar un tramo, «Aplicar lo marcado» = un paso de Ctrl+Z; la curva se oye en el visor
    (curves.gain) y «Quitar la mezcla de la IA» devuelve el volumen de antes.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_mix.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import curves as CV
    from editoria.core import media as M
    from editoria.core import mix_plan as MX
    from editoria.core.model import TRACK_AUDIO, Marker, new_id
    from editoria.ui.main_window import MainWindow
    from editoria.ui.mix_dialog import MixDialog
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    song = os.path.join(out, "cancion.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=20", song], check=True)
    voice = os.path.join(out, "voz.wav")       # suena solo en 2–3 s, 8–9,5 s y 14–15 s
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=700:d=20", "-af",
                    "volume='if(between(t,2,3)+between(t,8,9.5)+between(t,14,15),0.8,0)':eval=frame", voice],
                   check=True)
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    p = ctrl.project
    sid, vid = ctrl.import_now([song, voice])
    while ctrl.analyzing:
        pump(app, 0.1)
    ctrl.add_track(TRACK_AUDIO)
    at = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    mt, vt = at[-1], at[0]
    mt.role, mt.name = "musica", "Música"
    sc = ctrl.add_media([sid], mt.id, 0.0)[0]
    ctrl.add_media([vid], vt.id, 0.0)
    assert p.clips[sc].track_id == mt.id and all(c.track_id == vt.id for c in p.clips.values() if c.media_id == vid)
    p.transcripts[vid] = {"language": "es", "words": [
        [2.0, 2.5, "hola", 0.9], [2.5, 3.0, "amigos", 0.9],
        [8.0, 8.5, "lo", 0.9], [8.5, 9.0, "siento", 0.9], [9.0, 9.5, "hermano", 0.9],
        [14.0, 14.5, "¡corre!", 0.9], [14.5, 15.0, "cuidado", 0.9]], "segments": []}
    o = dict(MX.DEFAULTS, song_shape=False)
    res = MX.propose(p, o)
    kinds = {x["kind"] for x in res["items"]}
    assert {"normal", "emotivo", "accion", "silencio"} <= kinds, res["items"]
    lv = {t: MX.level_db(res["items"], t, o) for t in (2.5, 9.0, 10.5, 14.5, 5.5, 18.0)}
    assert abs(lv[2.5] + 12) < 0.5 and abs(lv[9.0] + 22) < 0.5 and abs(lv[14.5] + 6) < 0.5, lv
    assert lv[10.5] <= -11.5, ("el silencio tras la frase emotiva sigue bajo", lv)
    assert lv[5.5] > -0.5 and lv[18.0] > -0.5, lv
    print(f"✓ según lo que se dice: normal {lv[2.5]:.0f} dB · emotivo {lv[9.0]:.0f} dB (y {lv[10.5]:.0f} dB en el "
          f"silencio de después) · acción {lv[14.5]:.0f} dB · sin voz {lv[5.5]:.0f} dB")
    p.markers.append(Marker(new_id(), 13.5, "música", end=16.0))
    res2 = MX.propose(p, o)
    assert not any(x["kind"] == "accion" for x in res2["items"]), res2["items"]
    p.markers.clear()
    mt.locked = True
    res3 = MX.propose(p, o)
    assert not res3["tracks"] and res3["locked"] == [mt.id]
    mt.locked = False
    print("✓ un marcador «música» manda en su tramo · una pista bloqueada no se toca")
    tr = p.transcripts.pop(vid)
    res4 = MX.propose(p, o)
    blocks = [(x["a"], x["b"]) for x in res4["items"] if x["kind"] == "normal"]
    assert res4["source"] == "volumen de la voz" and len(blocks) == 3, blocks
    assert all(any(abs(a - e) < 0.35 for a, _b in blocks) for e in (2.0, 8.0, 14.0)), blocks
    p.transcripts[vid] = tr
    print(f"✓ sin transcripción, encuentra la voz por el volumen: {[(round(a, 1), round(b, 1)) for a, b in blocks]}")

    dlg = MixDialog(win)
    dlg.shape.setChecked(False)
    assert dlg.track_checks[mt.id].isChecked() and not dlg.track_checks[vt.id].isChecked()
    dlg.analyze()
    t0 = time.time()
    while dlg.result is None and time.time() - t0 < 60:
        pump(app, 0.1)
    assert dlg.result and dlg.list.count() == len(dlg.result["items"])
    for i in range(dlg.list.count()):                    # quito el tramo de acción
        if "acción" in dlg.list.item(i).text():
            dlg.list.item(i).setCheckState(Qt.Unchecked)
    n0 = ctrl.undo_stack.count()
    dlg.apply()
    pump(app, 0.2)
    c = p.clips[sc]
    assert ctrl.undo_stack.count() == n0 + 1 and c.vol_kf and (c.fx or {}).get("mix_orig") == []
    g = {t: CV.gain(c, t) for t in (2.5, 9.0, 14.5, 5.5)}
    assert abs(g[9.0] - 10 ** (-22 / 20)) < 0.02 and abs(g[2.5] - 10 ** (-12 / 20)) < 0.03, g
    assert g[14.5] > 0.95 and g[5.5] > 0.95, ("el tramo quitado no baja", g)
    print(f"✓ «Aplicar lo marcado» (sin el tramo quitado): un paso de Ctrl+Z; la música suena a {g[2.5]:.2f} · "
          f"{g[9.0]:.2f} · {g[14.5]:.2f}")
    ctrl.remove_mix()
    assert not p.clips[sc].vol_kf and "mix_orig" not in (p.clips[sc].fx or {})
    ctrl.undo_stack.undo()
    assert p.clips[sc].vol_kf
    print("✓ «Quitar la mezcla de la IA» devuelve el volumen de antes (y Ctrl+Z la vuelve a poner)")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
