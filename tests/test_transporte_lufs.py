"""
Prueba de lo nuevo de la barra de transporte del visor (ui/transport_extra.py):
  · −5s / +5s (sin pasar del principio ni del final) y Mayús+←; la velocidad 1× → 2× → 4× → 8× → 1×;
  · 🔊 volumen de ESCUCHA: no cambia el proyecto y NO llega a la exportación (mismo comando de FFmpeg);
  · 📊 LUFS: measure_project = la sonoridad del archivo exportado; clips_que_suenan (ni textos ni imágenes, ni el
    video con su sonido separado en A1, ni desactivados ni pistas silenciadas); plan_ganancia / project_gain con el
    tope de 400 % por clip y lo bloqueado sin tocar (un Ctrl+Z);
  · el asistente (botón «LUFS»): ANTES de preguntar dice el resultado REAL («quedará en −18,7 LUFS: algunos clips ya
    están al máximo») y, tras aplicar, la mezcla queda en eso; con pistas bloqueadas lo dice y aplica al resto; todo
    bloqueado = sin «Aplicar»; si el proyecto cambió mientras medía, avisa y no aplica; clic en ⏳ = cancelar.
Sin ventanas (el diálogo se sustituye) y sin sonido. Usa una carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_transporte_lufs.py [carpeta_salida]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FALLOS = []


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def _num(txt: str) -> float:
    return float(txt.replace("−", "-").replace(",", "."))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_transporte_lufs")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import loudness as LN
    from editoria.core import media as media_tools
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui import transport_extra as TX
    from editoria.ui.main_window import MainWindow
    ff = media_tools.ffmpeg()
    vid, mus = os.path.join(out, "v.mp4"), os.path.join(out, "musica.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-af", "volume=-12dB", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", vid], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=12",
                    "-af", "volume=-12dB", mus], check=True)
    win = MainWindow()
    win.show()
    win.resize(1600, 950)
    pump(app, 0.6)
    ctrl, eng, pv = win.ctrl, win.engine, win.preview
    msgs = []
    ctrl.message.connect(msgs.append)
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media(ids, v1.id, 0.0)
    pump(app, 0.5)
    p = ctrl.project
    dur = p.duration()
    vclip = next(c for c in p.clips.values() if p.track(c.track_id).kind == TRACK_VIDEO)
    aclip = next(c for c in p.clips.values() if p.track(c.track_id).kind == TRACK_AUDIO)
    chk(bool(vclip.link) and abs(dur - 12.0) < 0.2, f"video con su sonido separado en A1 ({dur:.1f} s)")

    print("— −5s / +5s y velocidad —")
    eng.seek(2.0)
    QTest.mouseClick(pv.btn_back5, Qt.LeftButton)
    pump(app, 0.1)
    chk(abs(eng.time) < 1e-6, f"−5s desde 2 s → 0 ({eng.time:.2f})")
    QTest.mouseClick(pv.btn_fwd5, Qt.LeftButton)
    pump(app, 0.1)
    chk(abs(eng.time - 5.0) < 0.05, f"+5s → 5 ({eng.time:.2f})")
    eng.seek(dur - 1.0)
    QTest.mouseClick(pv.btn_fwd5, Qt.LeftButton)
    pump(app, 0.1)
    chk(eng.time <= dur + 1e-6, f"+5s cerca del final no pasa del final ({eng.time:.2f} / {dur:.2f})")
    win.timeline.setFocus()
    eng.seek(6.0)
    pump(app, 0.1)
    QTest.keyClick(win.timeline, Qt.Key_Left, Qt.ShiftModifier)
    pump(app, 0.1)
    chk(abs(eng.time - 1.0) < 0.05, f"Mayús+← = −5 s ({eng.time:.2f})")
    eng.seek(0.0)
    vs = []
    for _ in range(4):
        pv.btn_speed.click()       # (el clic del botón, nunca su flechita: así no se abre un menú de verdad)
        pump(app, 0.05)
        vs.append(eng.vel)
    chk(vs == [2.0, 4.0, 8.0, 1.0], f"clic en 1× cicla 2× → 4× → 8× → 1× ({vs})")
    eng.set_speed(4.0)
    chk(pv.btn_speed.text() == "4×", f"el botón enseña la elegida ({pv.btn_speed.text()})")
    eng.set_speed(1.0)

    print("— 🔊 escucha: no llega a la exportación —")
    e = TX.escucha()
    antes = p.to_dict()
    a0, _ = build_command(p, ExportOptions(path=os.path.join(out, "x.mp4"), width=640, height=360, fps=30,
                                           encoder="cpu"), ff, os.path.join(out, "f0.txt"))
    e.set_value(30)
    e.set_muted(True)
    pump(app, 0.2)
    a1, _ = build_command(p, ExportOptions(path=os.path.join(out, "x.mp4"), width=640, height=360, fps=30,
                                           encoder="cpu"), ff, os.path.join(out, "f1.txt"))
    s0 = open(os.path.join(out, "f0.txt"), encoding="utf-8").read()
    s1 = open(os.path.join(out, "f1.txt"), encoding="utf-8").read()
    chk(s0 == s1 and [x for x in a0 if "f0.txt" not in x] == [x for x in a1 if "f1.txt" not in x],
        "con la escucha al 30 % y silenciada, la exportación es idéntica")
    chk(p.to_dict() == antes, "el volumen de escucha no cambia el proyecto")
    st = QSettings("EditorIA", "EditorIA")
    chk(int(st.value("reproduccion/volumen_escucha")) == 30, "el volumen de escucha se recuerda (en el .ini de prueba)")
    if eng.live is not None:
        chk(eng.live.mixer.monitor == 0.0, "la mezcla en directo usa la escucha (silenciada = 0)")
    e.set_muted(False)
    e.set_value(100)

    print("— 📊 medir —")
    m = LN.measure_project(p)
    chk(m is not None and -40 < m["lufs"] < -20, f"measure_project da un valor plausible ({m})")
    wav = os.path.join(out, "mezcla.wav")
    args, _t = build_command(p, ExportOptions(path=wav, audio_only=True, loudnorm=False), ff,
                             os.path.join(out, "fa.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    m2 = LN.measure(wav, 0, dur) if r.returncode == 0 else None
    chk(m2 is not None and abs(m2["lufs"] - m["lufs"]) < 0.6, f"misma sonoridad que la exportación de verdad ({m2})")

    print("— clips que suenan —")
    chk([c.id for c in LN.clips_que_suenan(p)] == [aclip.id], "solo suena el audio (el video tiene su sonido en A1)")
    tid = ctrl.add_text(1.0, 3.0, "Hola")
    sid = ctrl.add_shape("rect", "#ff0000", 1.0)
    pump(app, 0.2)
    chk([c.id for c in LN.clips_que_suenan(p)] == [aclip.id], "un texto y una figura (imagen) no cuentan")
    ctrl.set_clip_props([aclip.id], "Desactivar", enabled=False)
    chk(not LN.clips_que_suenan(p), "un clip desactivado no cuenta")
    ctrl.undo_stack.undo()
    ctrl.set_track_props(aclip.track_id, "Silenciar", muted=True)
    chk(not LN.clips_que_suenan(p), "una pista silenciada no cuenta")
    ctrl.undo_stack.undo()
    pump(app, 0.1)

    print("— plan_ganancia / project_gain —")
    plan = LN.plan_ganancia(p, 20.0)
    chk(plan["cambios"] == {aclip.id: 4.0} and plan["topados"] == [aclip.id] and not plan["bloqueados"],
        f"+20 dB: el clip se queda en su tope de 400 % ({plan})")
    i0 = ctrl.undo_stack.index()
    n = ctrl.project_gain(20.0, plan)
    chk(n == 1 and p.clips[aclip.id].volume == 4.0 and p.clips[vclip.id].volume == 1.0 and
        p.clips[tid].volume == p.clips[tid].volume and ctrl.undo_stack.index() == i0 + 1,
        "project_gain: solo el que suena, con tope, en un Ctrl+Z")
    ctrl.undo_stack.undo()
    chk(p.clips[aclip.id].volume == 1.0, "Ctrl+Z lo devuelve")
    ctrl.delete_clips([tid, sid])
    pump(app, 0.2)

    asis = eng.loudness
    dichos = []
    respuesta = {"v": True}
    asis.ask = lambda w, db, texto: (dichos.append((db, texto)), respuesta["v"])[1]

    def medir_con_boton(antes_de_esperar=None):
        dichos.clear()
        QTest.mouseClick(pv.btn_lufs, Qt.LeftButton)
        if antes_de_esperar:
            antes_de_esperar()
        t0 = time.time()
        while asis.job is not None and time.time() - t0 < 120:
            pump(app, 0.05)
        pump(app, 0.1)

    print("— asistente: el resultado REAL antes de preguntar —")
    ocupado = {}
    medir_con_boton(lambda: ocupado.update(t=pv.btn_lufs.text(), on=pv.btn_lufs.isEnabled(),
                                           tip=pv.btn_lufs.toolTip()))
    chk(ocupado.get("t") == "⏳" and ocupado.get("on") and "cancelar" in ocupado.get("tip", ""),
        f"midiendo: «⏳», activo y «clic = cancelar» ({ocupado})")
    chk(pv.btn_lufs.text() == "LUFS" and "⏳" not in pv.btn_lufs.toolTip(), "al acabar vuelve «LUFS» con su ayuda")
    chk(len(dichos) == 1 and dichos[0][0] is not None, "pregunta con «Aplicar»")
    texto = dichos[0][1] if dichos else ""
    mt = re.search(r"quedará en <b>(−?\d+,\d) LUFS", texto)
    chk(bool(mt) and "al máximo" in texto, "dice el resultado real y que algún clip ya está al máximo")
    real = _num(mt.group(1)) if mt else None
    print("   dice:", re.sub(r"<[^>]+>", "", texto.split("<br><br>")[2]) if texto.count("<br><br>") >= 2 else texto)
    m3 = LN.measure_project(p)
    chk(real is not None and m3 is not None and abs(m3["lufs"] - real) < 0.3,
        f"tras aplicar queda en lo que dijo ({m3 and m3['lufs']} vs {real})")
    chk(p.clips[aclip.id].volume == 4.0 and p.clips[vclip.id].volume == 1.0, "volúmenes aplicados (con tope)")
    ctrl.undo_stack.undo()
    pump(app, 0.1)

    print("— pistas bloqueadas —")
    a_tracks = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    otra = next((t for t in a_tracks if t.id != aclip.track_id), None)
    if otra is None:
        ctrl.add_track(TRACK_AUDIO) if hasattr(ctrl, "add_track") else None
        otra = next(t for t in p.tracks if t.kind == TRACK_AUDIO and t.id != aclip.track_id)
    mids = ctrl.import_paths([mus])
    while ctrl.analyzing:
        pump(app, 0.05)
    ctrl.add_media(mids, otra.id, 0.0)
    pump(app, 0.3)
    mclip = next(c for c in p.clips.values() if c.track_id == otra.id)
    ctrl.set_clip_props([aclip.id, mclip.id], "Bajar", volume=0.5)
    ctrl.set_track_props(otra.id, "Bloquear", locked=True)
    medir_con_boton()
    texto = dichos[0][1] if dichos else ""
    chk(len(dichos) == 1 and dichos[0][0] is not None and "🔒 1 clip(s)" in texto and "se aplica al resto" in texto,
        "con una pista bloqueada: lo dice y ofrece aplicar al resto")
    chk(p.clips[mclip.id].volume == 0.5 and p.clips[aclip.id].volume > 0.5, "lo bloqueado no se toca; el resto sí")
    mt = re.search(r"quedará en <b>(−?\d+,\d) LUFS", texto)
    m4 = LN.measure_project(p)
    chk(bool(mt) and m4 is not None and abs(m4["lufs"] - _num(mt.group(1))) < 0.3,
        f"…y queda en lo que dijo ({m4 and m4['lufs']} vs {mt and mt.group(1)})")
    ctrl.undo_stack.undo()
    ctrl.set_track_props(aclip.track_id, "Bloquear", locked=True)
    medir_con_boton()
    chk(len(dichos) == 1 and dichos[0][0] is None and "todo el sonido está bloqueado" in dichos[0][1],
        "todo bloqueado: lo dice y no ofrece «Aplicar»")
    chk(p.clips[aclip.id].volume == 0.5 and p.clips[mclip.id].volume == 0.5, "…y no cambia nada")
    ctrl.set_track_props(aclip.track_id, "Desbloquear", locked=False)
    ctrl.set_track_props(otra.id, "Desbloquear", locked=False)

    print("— el proyecto cambia mientras mide —")
    medir_con_boton(lambda: ctrl.set_clip_props([mclip.id], "Cambiar", volume=0.25))
    chk(len(dichos) == 2 and dichos[0][0] is not None and dichos[1][0] is None and "cambió" in dichos[1][1],
        "pregunta, y al aplicar avisa de que el proyecto cambió y no aplica")
    chk(p.clips[aclip.id].volume == 0.5 and p.clips[mclip.id].volume == 0.25, "…sin tocar nada (solo tu cambio)")

    print("— cancelar la medición —")
    n_msgs = len(msgs)
    medir_con_boton(lambda: QTest.mouseClick(pv.btn_lufs, Qt.LeftButton))
    chk(not dichos, "cancelada: no pregunta nada")
    chk(any("cancelada" in x for x in msgs[n_msgs:]), "avisa de que se canceló")
    chk(pv.btn_lufs.text() == "LUFS" and asis.job is None, "el botón vuelve a «LUFS»")
    chk(p.clips[aclip.id].volume == 0.5 and p.clips[mclip.id].volume == 0.25, "…y no cambia nada")
    respuesta["v"] = False
    medir_con_boton()
    chk(len(dichos) == 1 and p.clips[aclip.id].volume == 0.5, "tras cancelar vuelve a medir; «Solo informar» no toca")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
