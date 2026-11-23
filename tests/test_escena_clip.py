"""
🎬 Clip de escena: una escena en la línea de tiempo = UN clip en UNA pista, sin cocinar (core/escena_clip.py).
  · «✓ Aplicar» → un solo clip; el proyecto desplegado (el que pintan el visor y la exportación) tiene el personaje en
    su pista encima y nada más con «Sin fondo» (por defecto); la exportación: un píxel del personaje es su color y uno
    de una zona vacía es el video de debajo (nada de negro); con «Desenfocado» hay capa de ajuste.
  · El visor usa el proyecto desplegado (sus pistas temporales); cortar el clip da dos que enseñan tramos distintos
    de la escena (source_in); «🎬 Crear escena» la pone en Medios ▸ Escenas y la deja copiada: Ctrl+V la pega en el
    cabezal (un Ctrl+Z la quita); arrastrar el medio a la línea = clip de lo que dura con su nota; guardar y abrir el
    proyecto la conserva; «Deshacer clip compuesto» la despliega en clips sueltos.
Ejecutar:  .venv/Scripts/python.exe tests/test_escena_clip.py <carpeta_salida>   (sin ventanas, sin sonido)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

sys.stdout.reconfigure(line_buffering=True)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def png(nombre, color):
    from PIL import Image
    ruta = os.path.join(_TMP, nombre)
    Image.new("RGBA", (200, 300), color + (255,)).save(ruta)       # (opaco: el píxel del centro es su color)
    return ruta


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.core import escena_clip, scenes
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    azul = png("azul.png", (40, 80, 230))
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ctrl = win.ctrl
        win.workspaces.switch("youtube")
        pump(app, 0.2)
        p = ctrl.project
        p.width, p.height = 640, 360
        rojo = os.path.join(_TMP, "rojo.mp4")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:d=10",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", rojo], check=True,
                       creationflags=M.NO_WINDOW)
        (rid,) = ctrl.import_now([rojo])
        while ctrl.analyzing:
            pump(app, 0.1)
        v_abajo = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([rid], v_abajo.id, 0.0)
        aid = ctrl.media_for_path(azul, "Escenas")

        # ------------------------------------------------ ✓ Aplicar → un clip; desplegado; exportación
        p.mark_in, p.mark_out = 2.0, 6.0
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        assert pg.escena.get("fondo") == "nada" and pg.fondo.currentData() == "nada", "«Sin fondo» por defecto"
        assert pg.fondo.itemText(0).startswith("Sin fondo")
        pg._añadir_actor(aid, {"x": 0.05, "y": 0.2, "w": 0.3, "h": 0.6, "fit": "contain", "bg": "none"})
        act = pg.escena["actores"][0]
        act["fases"] = [{"tipo": "accion", "anim": "ninguna", "dur": 4.0, "auto": True}]     # (quieto: para medir)
        n0 = len(p.clips)
        assert pg.aplicar()
        eid = pg.escena["id"]
        suyos = ctrl.scene_clips(p, eid)
        assert len(suyos) == 1 and len(p.clips) == n0 + 1, ("un solo clip", len(suyos))
        c = suyos[0]
        assert escena_clip.escena_del_clip(p, c) is not None and abs(c.start - 2.0) < 1e-6 and abs(c.duration - 4) < 1e-6
        q = escena_clip.expandir(p)
        cl = [x for x in q.clips.values() if x.note == scenes.nota(eid)]
        assert len(cl) == 1 and cl[0].media_id == aid, [x.media_id for x in cl]
        assert q.track_index(cl[0].track_id) < q.track_index(c.track_id), "encima de la pista del clip"
        assert c.id not in q.clips and c.id in p.clips, "el de verdad no cambia"
        exp = os.path.join(_TMP, "exp.mp4")
        args, _t = build_command(p, ExportOptions(path=exp, width=640, height=360, fps=30, encoder="cpu",
                                                  loudnorm=False), M.ffmpeg(), os.path.join(_TMP, "f.txt"))
        subprocess.run(args, check=True, capture_output=True, creationflags=M.NO_WINDOW)
        fr = M.frame_rgb(exp, 4.0, 640).astype(int)
        cx, cy = int((0.05 + 0.15) * 640), int(0.5 * 360)
        assert fr[cy, cx][2] > 180 and fr[cy, cx][0] < 100, ("se ve el personaje", fr[cy, cx])
        vac = fr[int(0.2 * 360), int(0.8 * 640)]
        assert vac[0] > 180 and vac[1] < 70 and vac[2] < 70, ("zona vacía = el video de debajo (rojo)", vac)
        fuera = M.frame_rgb(exp, 1.0, 640).astype(int)[cy, cx]
        assert fuera[0] > 180 and fuera[2] < 70, "antes de la escena no está"
        print(f"✓ «✓ Aplicar» = un solo clip; desplegado encima; exportado: personaje {tuple(fr[cy, cx])}, zona vacía "
              f"{tuple(vac)} (el video de debajo, nada de negro)")

        # 🖥 el visor pinta el proyecto desplegado
        win.go_page("edit")
        pump(app, 0.3)
        win.engine.seek(3.0)
        pump(app, 0.3)
        assert win.engine._proj() is q or any(x.note == scenes.nota(eid) for x in win.engine._proj().clips.values())
        capas = win.preview.canvas.layers
        assert cl[0].track_id in capas, "el visor tiene la capa del personaje desplegado"

        # con «Desenfocado»: capa de ajuste en el desplegado
        esc = scenes.copia(p.scenes[eid])
        esc["fondo"] = "blur"
        assert ctrl.place_scene_clips([esc])
        assert len(ctrl.scene_clips(p, eid)) == 1, "se actualiza, no se duplica"
        from editoria.core import generators
        q2 = escena_clip.expandir(p)
        assert any(generators.is_adjust(p.media.get(x.media_id)) for x in q2.clips.values()
                   if x.note == scenes.nota(eid)), "fondo desenfocado = capa de ajuste sobre lo de debajo"
        ctrl.undo_stack.undo()
        assert p.scenes[eid]["fondo"] == "nada"
        print("✓ el visor usa lo desplegado; «Desenfocado» pone su capa de ajuste; volver a aplicar no duplica")

        # ------------------------------------------------ ✂ cortar el clip de escena
        c = ctrl.scene_clips(p, eid)[0]
        ctrl.split(3.5, [c.id])
        dos = sorted(ctrl.scene_clips(p, eid), key=lambda x: x.start)
        assert len(dos) == 2 and abs(dos[1].source_in - 1.5) < 1e-3 and abs(dos[0].source_in) < 1e-6, \
            [(x.start, x.source_in) for x in dos]
        q3 = escena_clip.expandir(p)
        piezas = sorted((x for x in q3.clips.values() if x.note == scenes.nota(eid)), key=lambda x: x.start)
        assert len(piezas) == 2 and abs(piezas[0].start - 2.0) < 1e-3 and abs(piezas[1].start - 3.5) < 1e-3
        assert abs(piezas[0].duration + piezas[1].duration - 4.0) < 1e-3
        ctrl.undo_stack.undo()
        assert len(ctrl.scene_clips(p, eid)) == 1
        print("✓ cortar el clip de escena: dos clips con tramos distintos de la misma escena")

        # ------------------------------------------------ 🎬 Crear escena → Medios + Ctrl+V
        win.go_page("scenes")
        pump(app, 0.3)
        pg = win._scenes_widget
        p.mark_in, p.mark_out = 6.5, 8.5
        pg._cargar(pg._nueva_desde_marcas(), True)
        pg._añadir_actor(aid)
        mid = pg.crear_escena()
        assert mid and mid in p.media and p.media[mid].category == escena_clip.CATEGORIA
        e2 = pg.escena["id"]
        assert not ctrl.scene_clips(p, e2), "crear no la pone en la línea de tiempo"
        assert ctrl.clipboard and ctrl.clipboard[0][0]["media_id"] == mid and win._copia_externa is False
        assert "Escenas" in win.statusBar().currentMessage()
        lib = getattr(win, "library", None)
        if lib is not None and hasattr(lib, "_rebuild"):
            lib._rebuild()
            nombres = [lib.tree.topLevelItem(i).text(0) for i in range(lib.tree.topLevelItemCount())]
            assert any(n.startswith(escena_clip.CATEGORIA) for n in nombres), nombres
        win.go_page("edit")
        pump(app, 0.2)
        win.engine.seek(8.0)
        n1 = len(p.clips)
        win._paste()
        pegados = ctrl.scene_clips(p, e2)
        assert len(pegados) == 1 and abs(pegados[0].start - 8.0) < 1e-3 and len(p.clips) == n1 + 1, \
            [(x.start, x.media_id) for x in pegados]
        ctrl.undo_stack.undo()
        assert not ctrl.scene_clips(p, e2) and len(p.clips) == n1, "un Ctrl+Z la quita"
        # arrastrar desde Medios (= añadir el medio): un clip de lo que dura, con su nota
        ids = ctrl.add_media([mid], next(t.id for t in p.tracks if t.kind == TRACK_VIDEO), 1.0)
        cc = p.clips[ids[0]]
        assert abs(cc.duration - scenes.largo(p.scenes[e2])) < 1e-3 and scenes.id_de_nota(cc.note) == e2
        print("✓ «🎬 Crear escena»: Medios ▸ Escenas y copiada; Ctrl+V la pega en el cabezal (Ctrl+Z la quita); "
              "desde Medios entra con lo que dura")

        # ------------------------------------------------ guardar y abrir · deshacer clip compuesto
        ruta = os.path.join(_TMP, "proyecto.eia")
        assert ctrl.save(ruta)
        ctrl.load(ruta)
        pump(app, 0.3)
        p = ctrl.project
        assert len(ctrl.scene_clips(p, eid)) == 1 and escena_clip.escena_del_clip(p, ctrl.scene_clips(p, eid)[0])
        c = ctrl.scene_clips(p, eid)[0]
        assert ctrl.is_compound(c.id)
        sueltos = ctrl.break_compound(c.id)
        assert sueltos and c.id not in p.clips and all(p.clips[i].media_id == aid for i in sueltos)
        assert all(scenes.id_de_nota(p.clips[i].note) == eid for i in sueltos)
        print("✓ guardar/abrir conserva el clip de escena; «Deshacer clip compuesto» la despliega en clips sueltos")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        pg = getattr(win, "_scenes_widget", None)
        if pg is not None:
            pg.sucia = False
        win.close()
        pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
