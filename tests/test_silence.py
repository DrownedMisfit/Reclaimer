"""
Prueba de «✂ Eliminar silencio» (como el de DaVinci Resolve): detección por umbral con márgenes, ajustes
guardados del usuario, vista previa en naranja, cortar en todas las pistas o solo en el clip, fundido cruzado,
deshacer y la barra de acciones rápidas del visor.
Ejecutar:  .venv/Scripts/python.exe tests/test_silence.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import silence as S  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    voz = os.path.join(out, "voz.wav")
    vid = os.path.join(out, "video.mp4")
    # voz de 12 s con silencios: 2–3.5 (1,5 s), 6–6.3 (0,3 s) y 9–11 (2 s)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=12", "-af",
                    "volume='if(between(t,2,3.5)+between(t,6,6.3)+between(t,9,11),0,1)':eval=frame", voz], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    st = QSettings("EditorIA", "EditorIA")
    saved = {k: st.value(k) for k in ("silencio/ultimo", "silencio/ajustes", "silencio/mas_opciones")}
    try:
        # --- detección con los ajustes del usuario (30 fps)
        db = S.frame_levels(voz, 30)
        p1 = S.PRESETS["Equilibrado (-26.8 dB · 2 / 4 · mín. 14)"]
        r1 = S.silent_ranges(db, 30, **p1)
        assert len(r1) == 2, r1                                  # 0,3 s (9 fotogramas) < mínimo 14: se respeta
        assert abs(r1[0][0] - (2 + 4 / 30)) < 0.05 and abs(r1[0][1] - (3.5 - 2 / 30)) < 0.05, r1
        p3 = S.PRESETS["Rápido y dinámico (-32 dB · 1 / 10 · mín. 2)"]
        assert len(S.silent_ranges(db, 30, **p3)) == 2
        print(f"✓ detección como Resolve: {[(round(a, 2), round(b, 2)) for a, b in r1]} "
              "(con 4 fotogramas después y 2 antes; la pausa corta se respeta)")

        app = QApplication(sys.argv)
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        c = win.ctrl
        p = c.project
        p.fps = 30.0
        vm, am = c.import_now([vid, voz])
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        nar = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
        c.add_media([vm], v1.id, 0.0)
        aid = c.add_media([am], nar.id, 0.0)[0]
        dur0 = p.duration()

        # --- botón de la barra rápida → ventana (con la narración aunque no haya selección)
        from editoria.ui.silence_dialog import SilenceDialog, targets
        ids, note = targets(win)
        assert ids == [aid] and "«A1»" in note, (ids, note)
        assert win.preview.quick["silence"].isVisible()
        st.setValue("silencio/mas_opciones", "false")         # (plegado, como al empezar)
        dlg = SilenceDialog(win, ids)
        dlg.show()
        # --- disposición: lo esencial visible y «Más opciones» plegado
        assert not dlg.more_box.isVisibleTo(dlg), "«Más opciones» debe empezar plegado"
        for w in (dlg.ctl["threshold_db"][1], dlg.ctl["before"][1], dlg.ctl["after"][1], dlg.ctl["min_frames"][1],
                  dlg.crossfade, dlg.info, dlg.b_ok, dlg.more_btn):
            assert w.isVisibleTo(dlg), w
        assert not dlg.mode.isVisibleTo(dlg) and not dlg.clicks.isVisibleTo(dlg)
        dlg.more_btn.click()
        pump(app, 0.1)
        assert dlg.more_box.isVisibleTo(dlg) and dlg.mode.isVisibleTo(dlg), "al pulsar, se ve «Detección»"
        assert str(st.value("silencio/mas_opciones")).lower() == "true", "el plegado queda guardado"
        dlg.more_btn.click()
        pump(app, 0.1)
        assert not dlg.more_box.isVisibleTo(dlg)
        dlg.more_btn.click()                                  # (abierto: así lo recuerda la próxima vez)
        pump(app, 0.1)
        print("✓ «Eliminar silencio»: lo esencial a la vista; «⚙ Más opciones» plegado y recordado")
        t0 = time.time()
        while not dlg._ready and time.time() - t0 < 30:
            pump(app, 0.05)
        dlg.preset.setCurrentIndex(dlg.preset.findData("Equilibrado (-26.8 dB · 2 / 4 · mín. 14)"))
        dlg._load_preset(dlg.preset.currentIndex())
        pump(app, 0.4)
        assert len(dlg.regions) == 2 and win.timeline.preview_regions == dlg.regions
        pistas = {win.ctrl.project.clips[i].track_id for i in dlg.clip_ids if i in win.ctrl.project.clips}
        assert set(win.timeline.preview_tracks or []) == pistas, (win.timeline.preview_tracks, pistas)
        print("✓ vista previa como Resolve: se oscurece solo en la pista que se corta")
        assert "2" in dlg.info.text()
        win.grab().save(os.path.join(out, "vista_previa.png"))
        removed = sum(b - a for a, b in dlg.regions)
        dlg.crossfade.setChecked(True)
        idx = c.undo_stack.index()
        dlg._apply()
        assert win.timeline.preview_regions == []
        assert abs(p.duration() - (dur0 - removed)) < 1e-3, (p.duration(), dur0, removed)
        # el video también se recortó (todas las pistas): siguen juntos
        assert abs(max(x.end for x in p.clips_on(v1.id)) - p.duration()) < 1e-3
        assert c.undo_stack.index() == idx + 1
        fades = [x for x in p.clips_on(nar.id) if (x.fx or {}).get("fade_in") or (x.fx or {}).get("fade_out")]
        assert fades, "fundido cruzado"
        print(f"✓ «Eliminar»: quitó {removed:.2f} s en voz y video (sincronizados), con fundidos; un solo Ctrl+Z")
        c.undo_stack.undo()
        assert abs(p.duration() - dur0) < 1e-6

        # --- solo en el clip: el video no se toca
        regs = S.plan(p, [p.clips[aid]], 30.0, p1)
        c.remove_silence([aid], regs, scope="track")
        assert abs(max(x.end for x in p.clips_on(v1.id)) - dur0) < 1e-6
        # (lo quitado según ESTE plan: el del diálogo puede llevar además lo aprendido de tus retoques reales)
        assert abs(max(x.end for x in p.clips_on(nar.id)) - (12 - sum(b - a for a, b in regs))) < 1e-3
        c.undo_stack.undo()
        print("✓ «Solo en estos clips»: la voz se acorta y el video se queda igual")

        # --- exportar: la voz dura lo que debe
        from editoria.export.ffmpeg_export import ExportOptions, build_command
        regs = S.plan(p, [p.clips[aid]], 30.0, p1)
        c.remove_silence([aid], regs, scope="all")
        wav = os.path.join(out, "sin_silencios.wav")
        args, total = build_command(p, ExportOptions(path=wav, audio_only=True, loudnorm=False), ff,
                                    os.path.join(out, "f.txt"))
        assert subprocess.run(args, capture_output=True).returncode == 0
        x = media_tools.decode_mono(wav, 16000)
        assert abs(len(x) / 16000 - (12 - sum(b - a for a, b in regs))) < 0.1
        print(f"✓ exportado: {len(x) / 16000:.2f} s (antes 12 s)")

        # --- guardar un ajuste propio
        from editoria.ui import silence_dialog as SD
        st.setValue(SD.KEY, '{"Mío": {"threshold_db": -40, "before": 3, "after": 3, "min_frames": 10}}')
        assert "Mío" in SD.saved_presets() and len(SD.saved_presets()) == len(S.PRESETS) + 1
        print("✓ tus ajustes (los 3 de Resolve y el de ritmo de Shorts) vienen guardados y puedes guardar más")
        dlg.close()
        win.analyzer.shutdown()
        c.undo_stack.setClean()
        c._media_dirty = False
        win.close()
    finally:
        for k, v in saved.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
