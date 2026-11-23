"""
🎬 Clip de escena: lo que pidió la revisión.
  A1 los tramos prerenderizados del visor (zone_render.light_copy) llevan los personajes y sus medios; la clave cambia
     al editar la escena · A2 ocultar la pista del clip oculta la escena (la caché lo nota) · A3 la copia memorizada
     tiene las marcas y el nombre de ahora · A4 sin la miniatura (otro PC) se rehace al abrir, no sale «falta» y se
     puede poner desde Medios · A5 encuadre, fundido, opacidad y velocidad del clip llegan a lo desplegado · A6 clic en
     un personaje del visor elige el clip de escena real · A7 quitar la escena o deshacer «Crear» no deja el medio ni
     deja pegar · A8 recortar el clip de escena lo limita a lo que dura la escena.
Ejecutar:  .venv/Scripts/python.exe tests/test_escena_clip_revision.py <carpeta_salida>   (sin ventanas, sin sonido)
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
    Image.new("RGBA", (200, 300), color + (255,)).save(ruta)
    return ruta


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.core import escena_clip, scenes
    from editoria.core import media as M
    from editoria.core import zone_render as ZR
    from editoria.core.model import TRACK_VIDEO
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
        p.mark_in, p.mark_out = 2.0, 6.0
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        pg._añadir_actor(aid, {"x": 0.05, "y": 0.2, "w": 0.3, "h": 0.6, "fit": "contain", "bg": "none"})
        pg.escena["actores"][0]["fases"] = [{"tipo": "accion", "anim": "ninguna", "dur": 4.0, "auto": True}]
        assert pg.aplicar()
        eid = pg.escena["id"]
        nota = scenes.nota(eid)
        c = ctrl.scene_clips(p, eid)[0]
        win.go_page("edit")
        pump(app, 0.3)

        def piezas(q=None):
            q = q or escena_clip.expandir(p)
            return [x for x in q.clips.values() if x.note == nota]

        # A1 · tramos prerenderizados
        q = ZR.light_copy(p, 2.5, 4.5)
        assert aid in q.media and any(x.media_id == aid for x in q.clips.values()), "la copia ligera lleva al personaje"
        z0 = ZR.zones(escena_clip.expandir(p), heavy=True)
        esc = scenes.copia(p.scenes[eid])
        esc["actores"][0]["caja"]["x"] = 0.5
        assert ctrl.place_scene_clips([esc])
        q2 = ZR.light_copy(p, 2.5, 4.5)
        assert next(x for x in q2.clips.values() if x.media_id == aid).layout["x"] == 0.5, "la copia ve el cambio"
        _ = z0
        print("✓ A1 los tramos prerenderizados del visor llevan los personajes y ven los cambios de la escena")

        # A2 · ocultar la pista oculta la escena
        c = ctrl.scene_clips(p, eid)[0]
        q0 = escena_clip.expandir(p)
        ctrl.set_track_props(c.track_id, "ocultar", hidden=True)
        q1 = escena_clip.expandir(p)
        assert q1 is not q0 and all(q1.track(x.track_id).hidden for x in piezas(q1)), "la escena se oculta"
        ctrl.undo_stack.undo()
        assert not any(escena_clip.expandir(p).track(x.track_id).hidden for x in piezas())
        print("✓ A2 ocultar la pista del clip de escena la oculta (la caché lo nota)")

        # A3 · la copia memorizada, al día
        q0 = escena_clip.expandir(p)
        p.mark_in, p.mark_out = 1.0, 3.0
        p.name = "Otro nombre"
        q1 = escena_clip.expandir(p)
        assert (q1.mark_in, q1.mark_out, q1.name) == (1.0, 3.0, "Otro nombre"), (q1.mark_in, q1.mark_out, q1.name)
        _ = q0
        print("✓ A3 lo memorizado tiene las marcas y el nombre de ahora")

        # A5 · encuadre, fundido, opacidad y velocidad del clip de escena
        c = ctrl.scene_clips(p, eid)[0]
        c.layout = {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5, "fit": "contain"}
        c.fx = {"fade_in": 1.0}
        c.opacity = 0.5
        pz = piezas()[0]
        assert abs(pz.layout["x"] - (0.5 + 0.5 * 0.5)) < 1e-3 and abs(pz.layout["w"] - 0.3 * 0.5) < 1e-3, pz.layout
        assert (pz.fx or {}).get("fade_in") == 1.0 and abs(pz.opacity - 0.5) < 1e-6
        c.layout, c.fx, c.opacity = None, None, 1.0
        ctrl.set_speed([c.id], 2.0)
        cc = ctrl.scene_clips(p, eid)[0]
        pz = piezas()[0]
        assert abs(cc.duration - 2.0) < 1e-3 and abs(pz.duration - 2.0) < 1e-3, (cc.duration, pz.duration)
        ctrl.undo_stack.undo()
        print("✓ A5 encuadre (toda la escena en su caja), fundido, opacidad y velocidad llegan a lo desplegado")

        # A6 · clic en un personaje del visor = el clip de escena
        c = ctrl.scene_clips(p, eid)[0]
        pz = piezas()[0]
        win._pick_from_viewer(pz.id)
        assert set(win.timeline.selected) >= {c.id}, win.timeline.selected
        assert win._clip_on_track_now(pz.track_id) == c.id
        win._tf_live(pz.id, {"x": 0, "y": 0, "w": 0.5, "h": 0.5})
        win._tf_done(pz.id, None, {"x": 0, "y": 0, "w": 0.5, "h": 0.5})
        print("✓ A6 clic en un personaje del visor elige el clip de escena de verdad")

        # A8 · recortar: hasta lo que dura la escena, y por la izquierda según source_in
        lmin, _a, _b, rmax = ctrl.trim_limits(c.id)
        assert abs(rmax - (c.start + 4.0)) < 1e-3 or rmax <= c.start + 4.0 + 1e-3, (lmin, rmax)
        assert lmin >= c.start - 1e-3, "sin material antes del inicio de la escena"
        ctrl.split(4.0, [c.id])
        dcha = max(ctrl.scene_clips(p, eid), key=lambda x: x.start)
        lmin2 = ctrl.trim_limits(dcha.id, overwrite=True)[0]       # (sin la otra mitad al lado)
        assert lmin2 < dcha.start - 0.5, "la parte de la derecha se puede alargar por la izquierda (source_in)"
        ctrl.undo_stack.undo()
        print("✓ A8 recortar el clip de escena: no pasa de lo que dura la escena; por la izquierda, según source_in")

        # A7 · quitar la escena / deshacer «Crear»: fuera su medio y no se puede pegar
        win.go_page("scenes")
        pump(app, 0.3)
        pg = win._scenes_widget
        p.mark_in, p.mark_out = 6.5, 8.5
        pg._cargar(pg._nueva_desde_marcas(), True)
        pg._añadir_actor(aid)
        mid = pg.crear_escena()
        e2 = pg.escena["id"]
        win.go_page("edit")
        pump(app, 0.2)
        ctrl.undo_stack.undo()
        assert e2 not in p.scenes and mid not in p.media, "deshacer «Crear» quita su medio"
        n = len(p.clips)
        win._paste()
        assert len(p.clips) == n, "no se pega una escena que ya no existe"
        ctrl.undo_stack.redo()
        assert e2 in p.scenes and mid in p.media, "rehacer la devuelve con su medio"
        ctrl.remove_scene(e2)
        assert mid not in p.media, "quitar la escena quita su medio"
        print("✓ A7 deshacer «Crear» o quitar la escena quita su medio (y no deja pegarla); rehacer la devuelve")

        # A4 · sin la miniatura: se rehace al abrir, no «falta», se pone desde Medios
        ruta = os.path.join(_TMP, "proy.eia")
        assert ctrl.save(ruta)
        m_id = p.scenes[eid]["media_id"]
        os.remove(p.media[m_id].path)
        ctrl.load(ruta)
        pump(app, 0.4)
        p = ctrl.project
        m_id = p.scenes[eid]["media_id"]
        assert m_id not in ctrl.missing and os.path.isfile(p.media[m_id].path), "se rehizo, no falta"
        assert piezas(escena_clip.expandir(p)), "y se despliega"
        os.remove(p.media[m_id].path)
        ctrl.recheck_missing()
        assert os.path.isfile(p.media[m_id].path) and m_id not in ctrl.missing
        r = ctrl.add_media([m_id], next(t.id for t in p.tracks if t.kind == TRACK_VIDEO), 12.0)
        assert r and scenes.id_de_nota(p.clips[r[0]].note) == eid, "se pone desde Medios"
        print("✓ A4 sin la miniatura (otro PC): se rehace al abrir y al revisar, nunca «falta», se pone desde Medios")
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
