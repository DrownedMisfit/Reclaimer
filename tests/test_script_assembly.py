"""
Prueba de «📜 Montaje desde el guion».
  1) Sin ventanas: parseo de etiquetas, alineación con una transcripción sintética (toma incompleta + toma buena,
     línea que falta, frase improvisada) y elección de tomas.
  2) Proyecto real (sin ventanas, QT_QPA_PLATFORM=offscreen): narración de ensayo hecha con tests/assets/
     narracion_prueba.wav (con una toma mala a propósito), «Montar» quita la toma mala en un solo paso de Ctrl+Z,
     pone marcadores y coloca un [CLIP: fortnite] desde una carpeta por palabra temporal.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_script_assembly.py _pruebas_tmp/test_script_assembly
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import script_assembly as SA  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def parte_1_sin_ventanas():
    guion = ("Bienvenidos a este canal.\n"
             "\n"
             "Hoy hablamos del combate de la demo. [CLIP: Fortnite]\n"
             "Este juego tiene un ritmo muy lento.\n"
             "La historia engancha desde el primer minuto.\n"
             "[NOTA: revisar la intro]\n")
    lines = SA.parse_script(guion)
    assert [ln["i"] for ln in lines] == [0, 1, 2, 3, 4], lines
    assert lines[1]["text"] == "Hoy hablamos del combate de la demo.", lines[1]
    assert lines[1]["tags"] == [{"kind": "clip", "value": "Fortnite"}], lines[1]
    assert lines[4]["text"] == "" and lines[4]["tags"] == [{"kind": "nota", "value": "revisar la intro"}]
    mus = SA.parse_script("Hola [MÚSICA: tensa] que tal")
    assert mus[0]["tags"] == [{"kind": "music", "value": "tensa"}] and mus[0]["text"] == "Hola que tal", mus
    print("✓ parse_script: una oración por línea, etiquetas [CLIP/IMG/MÚSICA/NOTA] fuera del texto")

    # Transcripción sintética: la línea 2 se dice DOS veces (la primera a medias), la 4 no se dice y hay una frase
    # improvisada de 4 s.
    words = [
        [0.5, 0.8, "Bienvenidos", 0.9], [0.8, 0.9, "a", 1], [0.9, 1.1, "este", 1], [1.1, 1.6, "canal.", 1],
        [3.0, 3.4, "Hoy", 0.9], [3.4, 3.8, "hablamos", 0.9], [3.8, 3.9, "del", 0.9],
        [5.5, 5.8, "Hoy", 0.9], [5.8, 6.2, "hablamos", 0.9], [6.2, 6.4, "del", 1], [6.4, 6.7, "combate", 1],
        [6.7, 6.8, "de", 1], [6.8, 6.9, "la", 1], [6.9, 7.6, "demo.", 1],
        [10.0, 10.4, "Eh,", 0.1], [10.4, 10.8, "pues", 0.9], [10.8, 11.2, "no", 1], [11.2, 11.5, "sé", 1],
        [11.5, 12.0, "qué", 1], [12.0, 12.6, "más", 1], [12.6, 13.2, "decir", 1], [13.2, 13.8, "aquí.", 1],
        [15.0, 15.4, "Este", 1], [15.4, 15.8, "juego", 1], [15.8, 16.1, "tiene", 1], [16.1, 16.3, "un", 1],
        [16.3, 16.8, "ritmo", 1], [16.8, 17.1, "muy", 1], [17.1, 17.9, "lento.", 1],
    ]
    aligned, impro = SA.align_script(lines, words)
    assert aligned[0] and aligned[0][0]["score"] >= 0.9, aligned[0]
    assert len(aligned[1]) == 2, aligned[1]                       # las dos tomas de la línea 2
    assert not aligned[1][0]["complete"] and aligned[1][1]["complete"], aligned[1]
    assert aligned[3] == [] and aligned[4] is None, aligned
    assert len(impro) == 1 and impro[0]["text"].startswith("Eh, pues no sé"), impro
    ch = SA.choose_takes(aligned)
    assert ch[1]["chosen"] is aligned[1][1], ch[1]                # la 2.ª toma (la entera)
    assert len(ch[1]["discarded"]) == 1 and ch[1]["discarded"][0] is aligned[1][0]
    assert ch[2]["missing"] is False and ch[3]["missing"] is True, ch
    assert ch[4]["empty"] is True and ch[4]["missing"] is False, ch[4]
    a, b = SA.cut_span(words, aligned[1][0]["a_idx"], aligned[1][0]["b_idx"])
    assert 2.9 < a < 3.05 and 3.9 < b < 4.2, (a, b)
    print("✓ alinea: la línea 2 tiene 2 tomas y elige la 2.ª (entera); la línea 4 falta; «Eh, pues no sé…» es "
          "improvisado")
    return words, lines


def hacer_narracion(out, src_wav, src_words):
    """Narración de ensayo: frase A · [toma a medias] · [toma buena] · improvisado · frase D, con pausas de 1,5 s.
    Los tiempos de las palabras salen de la transcripción real del archivo de prueba."""
    ff = media_tools.ffmpeg()
    segs = [("Hola a todos, bienvenidos a este análisis.", 0.0, 4.0),
            ("El combate se siente (a medias)", 7.1, 8.74),
            ("El combate se siente bastante lento.", 7.1, 9.8),
            ("Eh, este, las cinemáticas están muy bien trabajadas.", 19.24, 24.34),
            ("Y el problema de la narrativa es que no tiene ritmo.", 26.72, 30.6)]
    gap = 1.5
    parts, words, t = [], [], 0.0
    for i, (_txt, a, b) in enumerate(segs):
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=mono[s{i}]")
        for w in src_words:
            if w[0] >= a - 0.01 and w[1] <= b + 0.01:
                off = t - a
                words.append([round(w[0] + off, 3), round(w[1] + off, 3), w[2], w[3]])
        t += (b - a) + gap
        parts.append(f"anullsrc=r=44100:cl=mono,atrim=0:{gap},asetpts=PTS-STARTPTS[g{i}]")
    order = []
    for i in range(len(segs)):
        order += [f"[s{i}]", f"[g{i}]"]
    fc = ";".join(parts) + ";" + "".join(order) + f"concat=n={len(order)}:v=0:a=1[out]"
    wav = os.path.join(out, "narracion_montaje.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", src_wav, "-filter_complex", fc, "-map", "[out]",
                    wav], check=True)
    return wav, words, segs


def parte_2_proyecto(out, lines, src_wav, src_words):
    from editoria.ui.main_window import MainWindow
    from editoria.ui.script_dialog import ScriptDialog

    ff = media_tools.ffmpeg()
    wav, words, segs = hacer_narracion(out, src_wav, src_words)
    clips_root = os.path.join(out, "carpetas")
    fort = os.path.join(clips_root, "Fortnite")
    os.makedirs(fort, exist_ok=True)
    vid = os.path.join(fort, "combate.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("clips/carpeta_raiz", clips_root)

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    c = win.ctrl
    p = c.project
    p.fps = 30.0
    aid = c.import_now([wav])[0]
    nar = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    c.add_media([aid], nar.id, 0.0)
    # transcripción ya afinada (así no se lanza la alineación pesada en segundo plano)
    c.set_transcript(aid, {"language": "es", "model": "prueba", "aligned": True, "words": words})
    dur0 = p.duration()
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    n_clips0 = len(p.clips)

    dlg = ScriptDialog(win)
    dlg.show()
    pump(app, 0.1)
    idx = dlg.media.findData(aid)
    assert idx >= 0, "la narración con transcripción debe salir en la lista"
    dlg.media.setCurrentIndex(idx)
    dlg.script.setPlainText("Hola a todos, bienvenidos a este análisis.\n"
                            "El combate se siente bastante lento. [CLIP: fortnite]\n"
                            "Cambiemos de tema por completo ahora mismo.\n"
                            "Y el problema de la narrativa es que no tiene ritmo. [MÚSICA: tensa]\n"
                            "[NOTA: revisar la intro]\n")
    dlg.analyze()
    st_ = dlg.state
    assert st_ is not None and st_["choice"][1] is not None and len(st_["aligned"][1]) == 2, st_
    assert st_["choice"][2] is None, "«Cambiemos de tema…» debe faltar"
    assert len(st_["impro"]) == 1, st_["impro"]
    assert dlg.btn_montar.isEnabled()
    print("✓ diálogo: analiza la narración (toma 2 de la línea 2, falta la 3, 1 improvisado)")

    idx_undo = c.undo_stack.index()
    cuts = [SA.cut_span(st_["words"], t["a_idx"], t["b_idx"]) for t in st_["aligned"][1][:1]]
    removed = sum(b - a for a, b in cuts)
    dlg.montar()
    assert c.undo_stack.index() == idx_undo + 1, "«Montar» debe ser UN solo paso de deshacer"
    assert abs((dur0 - p.duration()) - removed) < 0.1, (dur0 - p.duration(), removed)
    labels = [m.label for m in p.markers]
    assert any(x.startswith("⚠ Falta") for x in labels), labels
    assert any(x.startswith("✎ Improvisado") for x in labels), labels
    assert any(x.startswith("♪ Música") for x in labels) and any(x.startswith("📝 Nota") for x in labels), labels
    fmid = next(m.id for m in p.media.values() if os.path.normcase(m.path) == os.path.normcase(vid))
    assert any(cl.media_id == fmid for cl in p.clips.values()), "el [CLIP: fortnite] debe estar colocado"
    print(f"✓ «Montar»: quitó la toma mala ({removed:.2f} s) en UN paso de Ctrl+Z; marcadores: "
          f"{len(labels)}; [CLIP: fortnite] colocado")
    c.undo_stack.undo()
    assert abs(p.duration() - dur0) < 1e-6, (p.duration(), dur0)
    assert len(p.clips) == n_clips0, (len(p.clips), n_clips0)
    assert not any(m.label.startswith("⚠") or m.label.startswith("✎") for m in p.markers)
    print("✓ Ctrl+Z: vuelve exactamente al estado de antes del montaje")
    assert v1 is not None
    dlg.close()
    win.analyzer.shutdown()
    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp",
                                                                         "test_script_assembly"))
    os.makedirs(out, exist_ok=True)
    words, lines = parte_1_sin_ventanas()
    src_wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    src_words = json.load(open(os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json"),
                               encoding="utf-8"))["words"]
    parte_2_proyecto(out, lines, src_wav, src_words)
    print("TODO OK")


if __name__ == "__main__":
    main()
