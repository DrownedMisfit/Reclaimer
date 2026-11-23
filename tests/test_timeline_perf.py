"""
Prueba de RENDIMIENTO con muchos clips (el «cada vez se pone más lento»): con ~800 clips en la línea de tiempo,
mover el cabezal (lo que pasa en cada fotograma al reproducir), redibujar la línea de tiempo y hacer una edición
deben seguir siendo rápidos. Y el resaltado naranja: solo contorno y solo cuando algo está bloqueado.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline_perf.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui import nudge as NG
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Resaltado naranja: solo cuando algo está bloqueado
    assert NG.is_blocking("Selecciona antes el clip donde quieres desenfocar una zona.")
    assert NG.is_blocking("Primero transcribe tu narración (pestaña «Limpieza»).")
    assert not NG.is_blocking("Añadido en el cabezal de la línea de tiempo.")
    assert not NG.is_blocking("La IA puso 5 clips en la timeline.")
    print("✓ el contorno naranja solo sale cuando algo está bloqueado (no con mensajes que solo informan)")

    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        pump(app, 0.4)
        ctrl, tl = win.ctrl, win.timeline
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        n = 400
        ctrl.insert_ranges([{"media_id": mid, "start": i * 1.0, "duration": 1.0, "source_in": (i % 18) * 1.0}
                            for i in range(n)], v1.id, "muchos")
        for i in range(n // 10):
            ctrl.add_text(i * 10.0, 2.0, f"T{i}")
        pump(app, 1.0)
        tl.fit()
        pump(app, 0.5)
        clips = len(ctrl.project.clips)

        def avg(fn, reps=6):
            t0 = time.perf_counter()
            for _ in range(reps):
                fn()
                app.processEvents()
            return (time.perf_counter() - t0) / reps * 1000
        k = {"t": 100.0}

        def seek():
            k["t"] += 0.04
            win.engine.seek(k["t"])
        t_seek = avg(seek)
        t_paint = avg(lambda: tl.repaint())
        cid = next(c.id for c in ctrl.project.clips_on(v1.id))
        vol = {"v": 1.0}

        def edit():
            vol["v"] = 0.9 if vol["v"] == 1.0 else 1.0
            ctrl.set_clip_props([cid], "vol", volume=vol["v"])
        t_edit = avg(edit)
        print(f"  {clips} clips: mover el cabezal {t_seek:.0f} ms · redibujar {t_paint:.0f} ms · editar {t_edit:.0f} ms")
        # (antes: ~226, ~217 y ~272 ms) — con margen para PCs más lentos
        assert t_seek < 90, t_seek
        assert t_paint < 110, t_paint
        assert t_edit < 200, t_edit
        print(f"✓ con {clips} clips sigue fluido (antes se volvía lento con cada clip añadido)")

        # 🔁 material repetido (fases 4 + 14): aquí los 400 clips repiten el mismo archivo (cada 18 s) → todos llevan
        #   franja y botón. Pintar con las marcas no puede costar más de un 10 % que sin ellas (el mapa se calcula
        #   fuera del pintado: al pintar solo se mira un diccionario). Se mide alejado (todo el video) y de cerca.
        tl.repetidos.recalcular()
        marcados = sum(1 for c in ctrl.project.clips_on(v1.id) if tl.repetidos.de(c.id))
        assert marcados >= 300, marcados

        import statistics
        rep_vivo = tl.repetidos

        def con_sin(medir, poner_con, poner_sin, vueltas=7):
            """Mediana de «con» y de «sin», medidos ALTERNANDO (el ruido del PC cae igual en los dos)."""
            con, sin = [], []
            for _ in range(vueltas):
                poner_con()
                con.append(medir())
                poner_sin()
                sin.append(medir())
            poner_con()
            return statistics.median(con), statistics.median(sin)
        res = []
        for pps in (None, 70.0):
            if pps is not None:
                tl.pps, tl.scroll = pps, 100.0
                tl.update()
                pump(app, 0.2)
            avg(lambda: tl.repaint())                     # (calentar: miniaturas y tira en caché)
            t_con, t_sin = con_sin(lambda: avg(lambda: tl.repaint(), 3),
                                   lambda: setattr(tl, "repetidos", rep_vivo), lambda: setattr(tl, "repetidos", None))
            res.append((pps, t_con, t_sin))
        tl.repaint()                                      # (la última medida fue sin marcas: se pintan otra vez)
        botones = len(tl._rep_btns)
        print("  🔁 pintar con / sin marcas de repetido: " + " · ".join(
            f"{'alejado' if pps is None else 'de cerca'} {a_:.1f} / {b_:.1f} ms" for pps, a_, b_ in res)
            + f" ({marcados} clips marcados, {botones} botones a la vista)")
        assert botones > 0, "de cerca, los clips repetidos llevan su botón"
        for pps, t_con, t_sin in res:
            assert t_con <= t_sin * 1.10 + 0.5, (pps, t_con, t_sin)
        tl.fit()
        pump(app, 0.3)
        print("✓ las marcas de material repetido no empeoran el pintado más de un 10 %")

        # ⏱ arrastrar y recortar con ~2500 clips (20/11: el banco pesado subió de ~144 a ~380 ms porque los fundidos
        #   automáticos buscaban la pareja de cada audio recorriendo todos los clips)
        ctrl.insert_ranges([{"media_id": mid, "start": 400.0 + i * 1.0, "duration": 1.0,
                             "source_in": (i % 18) * 1.0} for i in range(1100)], v1.id, "más")
        pump(app, 0.5)
        assert ctrl.fundidos_auto, "la regla de fundidos encendida (como la usa el usuario)"
        t0 = time.perf_counter()
        ctrl._fundidos_auto(ctrl.project)
        t_fund = (time.perf_counter() - t0) * 1000
        # ⚡ una edición pequeña (el volumen de un clip) con ~3000 clips: los fundidos solo se rehacen en las pistas de
        #   audio que toca la edición (Fable, 21/11: con todas, de 26 a 37 ms)
        aud = next(c.id for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_AUDIO)
        vol2 = {"v": 1.0}

        def edit_vol():
            vol2["v"] = 0.8 if vol2["v"] == 1.0 else 1.0
            ctrl.set_clip_props([aud], "vol", volume=vol2["v"])
        edit_vol()
        # (solo para medir: sin tocar los fundidos ya puestos; alternando, por la mediana)
        t_on, t_off = con_sin(lambda: avg(edit_vol, 3), lambda: setattr(ctrl, "fundidos_auto", True),
                              lambda: setattr(ctrl, "fundidos_auto", False))
        print(f"  edición pequeña con {len(ctrl.project.clips)} clips: {t_on:.1f} ms con fundidos automáticos · "
              f"{t_off:.1f} ms sin ellos (medianas)")
        assert t_on <= t_off * 1.15 + 3.0, (t_on, t_off)
        tl.pps, tl.scroll = 30.0, 900.0
        tl._update_scrollbar()
        tl.repaint()
        cand = [c for c in ctrl.project.clips_on(v1.id) if 900 < c.start < 1000][:8]
        arr, rec = [], []
        for c in cand:
            t0 = time.perf_counter()
            ctrl.move_clips({c.id: (c.start + 0.2, v1.id)})
            tl.repaint()
            arr.append((time.perf_counter() - t0) * 1000)
            app.processEvents()
            cc = ctrl.project.clips[c.id]
            t0 = time.perf_counter()
            ctrl.trim_clip(cc.id, "right", cc.end - 0.3)
            tl.repaint()
            rec.append((time.perf_counter() - t0) * 1000)
            app.processEvents()
        m_arr, m_rec = sorted(arr)[len(arr) // 2], sorted(rec)[len(rec) // 2]
        print(f"  {len(ctrl.project.clips)} clips: arrastrar {m_arr:.0f} ms · recortar {m_rec:.0f} ms · fundidos "
              f"automáticos {t_fund:.1f} ms")
        assert t_fund < 25, f"los fundidos automáticos no pueden recorrer todo por cada clip: {t_fund:.1f} ms"
        assert m_arr < 150 and m_rec < 150, (m_arr, m_rec)
        print("✓ arrastrar y recortar con muchos clips: sin la subida de los fundidos automáticos")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k2, v in keep.items():
            if v is None:
                st.remove(k2)
            else:
                st.setValue(k2, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
