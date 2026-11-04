"""
Prueba de la FLUIDEZ de los edits y de la exportación:
  · la canción se divide por frases (nada de «subida-drop-subida» cada compás = cortes que se aceleran de la nada);
  · cada estilo respeta su ritmo de cortes (Emocional/Cine nunca bajan de 2 golpes por plano);
  · transiciones musicales (en cambios de parte o al empezar una frase, durando 1 o ½ golpe);
  · velocity con rampa y cámara lenta fluida; movimiento suave en los planos;
  · 60 FPS por defecto; la ventana Exportar abre (antes fallaba sin tramo marcado), botones YouTube / TikTok /
    Windows con el códec correcto, y si la tarjeta gráfica falla se reintenta sola con el procesador.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_fluidez.py <carpeta_salida>
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "exportar/destino", "exportar/carpeta")}
    spec = importlib.util.spec_from_file_location("t_e2", os.path.join(ROOT, "tests", "test_edits2.py"))
    e2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2)
    from editoria.ai import edit_engine, edit_maker, music_analysis
    from editoria.ai import song_structure as SS
    from editoria.core import media as media_tools

    # 1) Partes por frases: los compases sueltos no cambian la parte
    tags = ["break"] * 6 + ["drop"] + ["break"] * 5 + ["build"] * 2 + ["drop"] * 8 + ["build"] + ["drop"] * 7
    rel = np.array([0.2] * 6 + [0.8] + [0.2] * 5 + [0.5] * 2 + [0.9] * 8 + [0.55] + [0.9] * 7)
    sm = SS._smooth_tags(tags, rel)
    runs = [len(list(g)) for _k, g in __import__("itertools").groupby(sm)]
    assert min(runs) >= 4 and sm[6] == "break" and sm[23] == "drop", (sm, runs)
    print(f"✓ partes por frases: {runs} compases (sin picos sueltos de un compás)")

    song_path = os.path.join(out, "cancion.wav")
    e2.make_song(song_path)
    song = edit_maker.analyze_song(song_path)
    edit_engine.enrich(song, media_tools.decode_mono(song_path, music_analysis.SR), music_analysis.SR)
    beat = 60 / song["tempo"]
    bar = 4 * beat
    mid = [s for s in song["sections"][1:-1]]
    assert all(s["b"] - s["a"] >= 4 * bar - 0.05 for s in mid), [(round(s["a"], 1), s["kind"]) for s in song["sections"]]

    ff = media_tools.ffmpeg()
    clips = []
    for name, src in (("a.mp4", "testsrc2=s=640x360:r=30:d=60"), ("b.mp4", "mandelbrot=s=640x360:r=30")):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "60",
                            "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", p], check=True)
        clips.append(p)
    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})

    # 2) Cada estilo con su ritmo de cortes
    # Más pausado (2026-10): ningún plano más corto que el mínimo de su estilo, salvo la ÚNICA ráfaga (y solo con
    # canción enérgica), que va justo antes del drop y nunca baja de ¼ de golpe.
    for style, fastest in (("emocional", 2), ("cine", 2), ("phonk", 0.5), ("hype", 0.25)):
        plan = edit_engine.plan_v2(song, srcs, style=style, length=None)
        shots: dict[int, tuple] = {}
        for c in plan["clips"]:
            a0, d0 = shots.get(c["shot"], (c["start"], 0.0))
            shots[c["shot"]] = (a0, d0 + c["duration"])
        inner = sorted(shots.items())[1:-1]              # sin el primero (antes del golpe) ni el último
        st_ = edit_engine.settings_for(style)
        drop_t = plan.get("drop")
        burst = [d for _k, (a0, d) in inner if drop_t is not None and
                 drop_t - edit_engine.BURST_BEATS * beat - 0.05 <= a0 < drop_t and
                 d < edit_engine.MIN_SHOT[st_["density"]] * 0.9]
        rest = [d for _k, (a0, d) in inner if not (drop_t is not None and
                drop_t - edit_engine.BURST_BEATS * beat - 0.05 <= a0 < drop_t)]
        shortest = min(d for _k, (_a, d) in inner)
        assert shortest >= 0.25 * beat - 0.03, (style, round(shortest, 3))
        assert len(burst) <= edit_engine.BURST_BEATS * 4, (style, len(burst))
        assert style not in ("emocional", "cine") or not burst, (style, "con «Tranquilo» nunca hay ráfaga")
        short_rest = [d for d in rest if d < edit_engine.MIN_SHOT[st_["density"]] * 0.9]
        assert len(short_rest) <= 2, (style, [round(d, 2) for d in short_rest])
        if style in ("emocional", "cine"):
            total = plan["music"]["duration"]
            assert len(shots) <= total / (2 * beat) + 2, (style, len(shots))
        # transiciones musicales: duran 1 o ½ golpe (o menos si el plano es corto), nunca a ciegas
        for c in plan["clips"]:
            t = c.get("trans")
            if t:
                assert 0.12 <= t["dur"] <= min(1.0, beat) + 1e-3, (style, t)
        if style == "phonk":
            vel = [c for c in plan["clips"] if c["speed"] == 0.35]
            assert vel and all(c["smooth"] for c in vel), "cámara lenta fluida en el velocity"
            assert any(abs(c["speed"] - 1.0) < 1e-6 for c in plan["clips"]), "rampa lento → normal → rápido"
        print(f"✓ {style}: {len(shots)} planos, el más corto {shortest:.2f} s (mín. {fastest:g} golpe/s)")
    emo = edit_engine.plan_v2(song, srcs, style="emocional", length=None)
    n_tr = sum(1 for c in emo["clips"] if c.get("trans"))
    moving = sum(1 for c in emo["clips"] if c.get("zoom"))
    assert n_tr >= 1 and moving >= len(emo["clips"]) * 0.6, (n_tr, moving, len(emo["clips"]))
    print(f"✓ emocional: {n_tr} transiciones en cambios de parte/frases, {moving} de {len(emo['clips'])} planos con "
          "movimiento suave")

    # 3) 60 FPS por defecto y ventana Exportar
    app = QApplication(sys.argv)
    from editoria.export import ffmpeg_export as FX
    from editoria.ui.export_dialog import ExportDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        assert ctrl.project.fps == 60.0, ctrl.project.fps
        ctrl.set_project_format("edit")
        p = ctrl.project
        assert (p.width, p.height, p.fps) == (1080, 1920, 60.0)
        ctrl.import_paths([song_path] + clips)
        while ctrl.analyzing:
            pump(app, 0.1)
        by_name = {m.name: m.id for m in p.media.values()}
        plan = edit_engine.plan_v2(song, srcs, style="phonk", length=8.0)
        for c in plan["clips"]:
            c["media_id"] = by_name[c["media_id"]]
        plan["music"]["media_id"] = by_name["cancion.wav"]
        ctrl.apply_edit_plan(plan, layout="auto")
        assert p.marked_range() is None
        dlg = ExportDialog(ctrl, win)                    # antes: «fmt_time» → la ventana ni abría
        dlg.show()
        pump(app, 0.2)
        dlg._apply_target("youtube")
        o = dlg._options()
        assert (o.width, o.height, o.fps, o.codec, o.target) == (1080, 1920, 60.0, "h264", "youtube"), o
        assert dlg.bitrate.value() == 24 and "YouTube" in dlg.target_info.text() and not dlg.advanced.isVisible()
        assert dlg.out.text().endswith(" - YouTube.mp4"), dlg.out.text()
        dlg._apply_target("windows")
        assert "Windows" in dlg.target_info.text() and dlg.out.text().endswith(f"{p.name}.mp4")
        dlg._apply_target("custom")
        assert dlg.advanced.isVisible()
        dlg.grab().save(os.path.join(out, "exportar_personalizado.png"))
        dlg._apply_target("tiktok")
        assert FX.target_size("tiktok", 1920, 1080) == (1080, 1920), "TikTok: siempre vertical"
        pump(app, 0.2)
        dlg.grab().save(os.path.join(out, "exportar.png"))
        print("✓ 60 FPS por defecto · Exportar abre · ▶ YouTube / ♪ TikTok / ⧉ Windows / ⚙ Personalizado")

        # 4) Exportar de verdad (pequeño, para ir rápido); la «tarjeta gráfica» falla a propósito → procesador
        dlg._apply_target("youtube")
        dlg.width_box.setValue(270)
        dlg.height_box.setValue(480)
        dlg.encoder.setCurrentIndex(dlg.encoder.findData("gpu"))
        mp4 = os.path.join(out, "edit_youtube.mp4")
        if os.path.exists(mp4):
            os.remove(mp4)
        dlg.out.setText(mp4)
        real = FX.ENCODERS[("h264", "gpu")]
        FX.ENCODERS[("h264", "gpu")] = "codificador_que_no_existe"
        try:
            dlg._start()
            t0 = time.time()
            while (dlg.proc is not None or not dlg._retried_cpu) and time.time() - t0 < 240:
                pump(app, 0.2)
                if dlg._retried_cpu and dlg.proc is None:
                    break
        finally:
            FX.ENCODERS[("h264", "gpu")] = real
        assert dlg._retried_cpu, "se reintentó con el procesador"
        assert os.path.exists(mp4) and "Listo" in dlg.status.text(), (dlg.status.text(), dlg._log[-8:])
        info = json.loads(subprocess.run([media_tools.ffprobe(), "-v", "error", "-show_streams", "-of", "json", mp4],
                                         capture_output=True, text=True).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert v["codec_name"] == "h264" and v["profile"] == "High" and v["pix_fmt"] == "yuv420p", v
        assert v["r_frame_rate"] == "60/1" and v.get("color_space") == "bt709", (v["r_frame_rate"], v.get("color_space"))
        assert a["codec_name"] == "aac" and a["sample_rate"] == "48000" and a["channels"] == 2, a
        print(f"✓ exportado para YouTube: H.264 High · 60 FPS · yuv420p · BT.709 · AAC 48 kHz estéreo "
              f"(la tarjeta «falló» y siguió con el procesador)")
        dlg.close()
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
