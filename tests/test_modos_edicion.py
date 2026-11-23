"""
🎬 PRUEBA de la fase 6 de la línea de tiempo: modos de edición como Resolve, desde Medios.
  · F9 insertar · F10 sobrescribir · Mayús+F11 reemplazar · F12 poner encima · Mayús+F12 al final, cada uno con un
    video con su sonido vinculado y la narración debajo: nada se desincroniza ni se pisa sin querer (la narración no
    cambia salvo el hueco del insertar, con su contenido entero), un Ctrl+Z cada uno;
  · el canal elegido es el destino; Mayús al soltar = inserción inteligente (en el corte más cercano);
  · los atajos nuevos no chocan con ninguno.
Sin ventanas visibles (offscreen), datos aislados. Ejecutar:  .venv/Scripts/python.exe tests/test_modos_edicion.py <c>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None


def _vigilante(segundos: float = 420.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "modos_edicion")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    rutas = {}
    for nombre, src, d in (("base.mp4", "testsrc2=s=320x180:r=30", 10), ("nuevo.mp4", "smptebars=s=320x180:r=30", 6),
                           ("largo.mp4", "rgbtestsrc=s=320x180:r=30", 14), ("corto.mp4", "testsrc=s=320x180:r=30", 2)):
        rutas[nombre] = os.path.join(out, nombre)
        if not os.path.exists(rutas[nombre]):
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}:d={d}", "-f", "lavfi",
                            "-i", f"sine=f=500:d={d}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                            "-shortest", rutas[nombre]], check=True)
    voz = os.path.join(RAIZ, "tests", "assets", "narracion_prueba.wav")
    musica = os.path.join(out, "musica.wav")
    if not os.path.exists(musica):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=20", musica], check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.6)
    ctrl, tl = win.ctrl, win.timeline
    ctrl.project.fps = 30.0
    vid_base, vid_nuevo, vid_largo, vid_corto, nid, mus = ctrl.import_now(
        [rutas["base.mp4"], rutas["nuevo.mp4"], rutas["largo.mp4"], rutas["corto.mp4"], voz, musica])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a_voz = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([nid], a_voz.id, 0.0)                 # la narración, debajo
    ctrl.add_media([vid_base], v1.id, 0.0)               # un video con su sonido vinculado, en 0–10 s
    p = ctrl.project
    largo_voz = p.media[nid].duration
    p.transcripts[nid] = {"words": __import__("json").load(open(os.path.join(
        RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json"), encoding="utf-8"))["words"]}

    def voz():
        return sorted((round(c.start, 3), round(c.source_in, 3), round(c.duration, 3))
                      for c in p.clips.values() if c.media_id == nid)

    def foto():
        return sorted((c.id, round(c.start, 4), round(c.duration, 4), round(c.source_in, 4), c.track_id, c.media_id)
                      for c in p.clips.values())

    def desfases():
        porl = {}
        for c in p.clips.values():
            if c.link:
                porl.setdefault(c.link, []).append(c)
        return [[(round(c.start, 4), round(c.source_in, 4)) for c in cs] for cs in porl.values()
                if len({(round(c.start, 4), round(c.duration, 4), round(c.source_in, 4)) for c in cs}) > 1]

    def vinculos_malos():
        porl = {}
        for c in p.clips.values():
            if c.link:
                porl.setdefault(c.link, []).append(c)
        return [[(p.track(c.track_id).name, round(c.start, 3), round(c.end, 3)) for c in cs] for cs in porl.values()
                if len(cs) > 2 or sum(1 for c in cs if p.track(c.track_id).kind == TRACK_VIDEO) > 1]

    def solapes():
        malos = []
        for tr in p.tracks:
            cs = sorted(p.clips_on(tr.id), key=lambda c: c.start)
            malos += [(tr.name, a.start, b.start) for a, b in zip(cs, cs[1:]) if a.end > b.start + 1e-6]
        return malos

    voz0, foto0 = voz(), foto()
    assert len(voz0) == 1 and not desfases() and not solapes()
    T = 4.0
    win.engine.user_seek(T)
    tl.set_playhead(T)
    pump(app, 0.2)

    def nuevos(antes_ids):
        return [c for c in p.clips.values() if c.id not in antes_ids]

    def deshacer():
        n0 = ctrl.undo_stack.index()
        ctrl.undo_stack.undo()
        assert ctrl.undo_stack.index() == n0 - 1
        assert foto() == foto0, "un Ctrl+Z lo deja como estaba"

    # ---------------------------------------------------------------- F9 insertar
    ids0 = set(p.clips)
    creados = win._modo_edicion("insertar", ids=[vid_nuevo])
    p = ctrl.project
    nv = nuevos(ids0)
    vn = next(c for c in nv if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    assert abs(vn.start - T) < 1e-6 and abs(vn.duration - 6.0) < 0.05 and vn.track_id == v1.id, (vn.start, vn.duration)
    assert any(c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_AUDIO and c.link == vn.link for c in nv)
    vz = voz()
    assert len(vz) == 2 and vz[0][0] == 0.0 and abs(vz[0][2] - T) < 1e-6, vz
    assert abs(vz[1][0] - (T + 6.0)) < 0.05 and abs(vz[1][1] - T) < 1e-6, "la narración sigue entera tras el hueco"
    assert abs(sum(d for _s, _i, d in vz) - largo_voz) < 0.02
    assert not desfases() and not solapes(), (desfases(), solapes())
    assert set(creados) >= {vn.id}
    print("✓ F9 insertar: hueco en todas las pistas, narración entera y nada desfasado")
    deshacer()

    # ---------------------------------------------------------------- F10 sobrescribir
    ids0 = set(p.clips)
    win._modo_edicion("sobrescribir", ids=[vid_nuevo])
    p = ctrl.project
    assert voz() == voz0, "la narración no se toca"
    nv = nuevos(ids0)
    vn = next(c for c in nv if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    an = next(c for c in nv if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_AUDIO)
    assert vn.track_id == v1.id and abs(vn.start - T) < 1e-6 and an.track_id != a_voz.id
    base_audio = [c for c in p.clips.values() if c.media_id == vid_base and p.track(c.track_id).kind == TRACK_AUDIO]
    assert not any(c.start < T + 6.0 - 1e-6 and c.end > T + 1e-6 for c in base_audio), \
        "el sonido del video tapado se quita en ese tramo (no queda bajo la imagen nueva)"
    assert not desfases() and not solapes(), (desfases(), solapes())
    assert not vinculos_malos(), vinculos_malos()
    print("✓ F10 sobrescribir: tapa solo el destino (y su sonido vinculado); la narración intacta")
    deshacer()
    # F10 en MEDIO de un clip vinculado: la pieza izquierda y la derecha quedan con vínculos distintos (como al dividir)
    ids0 = set(p.clips)
    win._modo_edicion("sobrescribir", ids=[vid_corto])
    p = ctrl.project
    izq = [c for c in p.clips.values() if c.media_id == vid_base and c.end <= T + 1e-6]
    der = [c for c in p.clips.values() if c.media_id == vid_base and c.start >= T + 2.0 - 1e-6]
    assert len(izq) == 2 and len(der) == 2, (izq, der)
    assert izq[0].link == izq[1].link and der[0].link == der[1].link and izq[0].link != der[0].link, "vínculos"
    assert not vinculos_malos() and not desfases() and not solapes(), (vinculos_malos(), desfases())
    assert voz() == voz0
    print("✓ F10 en medio de un clip vinculado: izquierda y derecha con su propio vínculo")
    deshacer()
    # un AUDIO sin canal elegido: a una pista de audio libre, nunca a la de la narración
    ids0 = set(p.clips)
    win._modo_edicion("sobrescribir", ids=[mus])
    p = ctrl.project
    mc = next(c for c in nuevos(ids0) if c.media_id == mus)
    assert mc.track_id != a_voz.id and voz() == voz0, "la música no pisa la voz"
    assert not solapes()
    deshacer()
    n0 = ctrl.undo_stack.index()
    tl.set_selection([])
    win._modo_edicion("reemplazar", ids=[mus])           # (sin canal ni clip elegido: pide elegir, no toca nada)
    assert ctrl.undo_stack.index() == n0 and voz() == voz0
    print("✓ un audio sin canal va a una pista libre (la narración, intacta); reemplazar sin elegir no toca nada")

    # ---------------------------------------------------------------- Mayús+F11 reemplazar
    base = next(c for c in p.clips.values() if c.media_id == vid_base and c.track_id == v1.id)
    sitio = (base.start, base.duration)
    tl.set_selection([base.id])                          # (el clip elegido marca la pista de destino)
    win._modo_edicion("reemplazar", ids=[vid_largo])
    p = ctrl.project
    base = p.clips[base.id]
    assert base.media_id == vid_largo and (base.start, base.duration) == sitio and base.source_in == 0.0
    sonido = [c for c in p.clips.values() if c.link and c.link == base.link and c.id != base.id]
    assert len(sonido) == 1 and sonido[0].media_id == vid_largo and sonido[0].start == base.start
    assert not any(c.media_id == vid_base for c in p.clips.values()), "su sonido viejo ya no está"
    assert voz() == voz0 and not desfases() and not solapes()
    n0 = ctrl.undo_stack.index()
    win._modo_edicion("reemplazar", ids=[vid_nuevo])      # (6 s no alcanza para un clip de 10 s: avisa, no toca)
    assert ctrl.undo_stack.index() == n0
    print("✓ Mayús+F11 reemplazar: mismo sitio y largo, su sonido cambiado; si no alcanza, no toca nada")
    deshacer()
    # varios archivos: el primero, y lo dice
    tl.set_selection([base.id])
    win._modo_edicion("reemplazar", ids=[vid_largo, vid_nuevo, vid_corto])
    assert "Se usó el primero de 3" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
    assert p.clips[base.id].media_id == vid_largo
    deshacer()
    # un B-roll MUDO (volumen 0) reemplazado por un video con sonido: sigue mudo
    ctrl.set_clip_props(ctrl.linked_ids([base.id]), "vol", volume=0.0)
    p = ctrl.project
    foto_mudo = foto()
    tl.set_selection([base.id])
    win._modo_edicion("reemplazar", ids=[vid_largo])
    p = ctrl.project
    b2 = p.clips[base.id]
    sonando = [c for c in p.clips.values() if c.media_id == vid_largo and c.volume > 0]
    assert b2.media_id == vid_largo and not sonando, "ningún sonido nuevo encima de la narración"
    ctrl.undo_stack.undo()
    p = ctrl.project
    assert foto() == foto_mudo
    ctrl.undo_stack.undo()
    p = ctrl.project
    assert foto() == foto0
    # «separar audio» apagado: el video lleva el sonido DENTRO (sin vinculados); reemplazarlo conserva su volumen
    msgs = []
    ctrl.message.connect(msgs.append)
    tl.set_selection([base.id])
    ctrl.edit_mode([vid_largo, vid_nuevo], "reemplazar", T, v1.id)
    assert any("Se usó el primero de 2" in m_ for m_ in msgs), msgs
    ctrl.undo_stack.undo()
    p = ctrl.project
    viejo_split = ctrl.split_av
    ctrl.split_av = False
    ids0 = set(p.clips)
    ctrl.edit_mode([vid_nuevo], "encima", 20.0, v1.id)      # (sin separar: un solo clip con su sonido dentro)
    p = ctrl.project
    dentro = next(c for c in nuevos(ids0) if c.media_id == vid_nuevo)
    assert len(nuevos(ids0)) == 1 and not dentro.link and dentro.volume > 0
    vol0 = dentro.volume
    ctrl.edit_mode([vid_largo], "reemplazar", dentro.start + 1.0, dentro.track_id)
    p = ctrl.project
    assert p.clips[dentro.id].media_id == vid_largo and p.clips[dentro.id].volume == vol0, \
        "con el sonido dentro, conserva su volumen (no se queda mudo sin avisar)"
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    ctrl.split_av = viejo_split
    p = ctrl.project
    assert foto() == foto0
    print("✓ reemplazar con varios usa el primero (y avisa, también desde el controlador); un B-roll mudo sigue mudo; "
          "con el sonido dentro conserva su volumen")

    # ---------------------------------------------------------------- F12 encima
    ids0 = set(p.clips)
    win._modo_edicion("encima", ids=[vid_nuevo])
    p = ctrl.project
    vn = next(c for c in nuevos(ids0) if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    assert vn.track_id != v1.id and p.track_index(vn.track_id) < p.track_index(v1.id), "encima de la de destino"
    assert abs(vn.start - T) < 1e-6
    assert voz() == voz0 and not desfases() and not solapes()
    assert any(c.media_id == vid_base and c.track_id == v1.id and c.start == 0.0 and c.duration == 10.0
               for c in p.clips.values()), "lo de debajo, entero"
    print("✓ F12 poner encima: en una pista por encima, sin tocar nada")
    deshacer()

    # ---------------------------------------------------------------- Mayús+F12 al final
    ids0 = set(p.clips)
    win._modo_edicion("al_final", ids=[vid_nuevo])
    p = ctrl.project
    vn = next(c for c in nuevos(ids0) if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    assert vn.track_id == v1.id and abs(vn.start - 10.0) < 1e-6, vn.start
    assert voz() == voz0 and not desfases() and not solapes()
    print("✓ Mayús+F12 al final: detrás del último clip de la pista")
    deshacer()

    # ---------------------------------------------------------------- canal elegido = destino
    v_otra = next(t for t in p.tracks if t.kind == TRACK_VIDEO and t.id != v1.id)
    tl.channels = {v_otra.id}
    ids0 = set(p.clips)
    win._modo_edicion("sobrescribir", ids=[vid_nuevo])
    p = ctrl.project
    vn = next(c for c in nuevos(ids0) if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    assert vn.track_id == v_otra.id, "el canal elegido es el destino"
    tl.channels = set()
    print("✓ el canal elegido es la pista de destino")
    deshacer()

    # ---------------------------------------------------------------- Mayús al soltar = inserción inteligente
    # cortes del video en 6,0 s (pausa de la narración: entre «análisis.» 3,71 y «El» 7,1) y en 7,4 s (dentro de «El»)
    base_id = next(c.id for c in p.clips.values() if c.media_id == vid_base and c.track_id == v1.id)
    ctrl.split(7.4, ctrl.linked_ids([base_id]))
    p = ctrl.project
    ctrl.split(6.0, ctrl.linked_ids([next(c.id for c in p.clips.values() if c.media_id == vid_base and
                                          c.track_id == v1.id and c.start == 0.0)]))
    p = ctrl.project
    assert tl._en_palabra(7.4) and not tl._en_palabra(6.0)
    foto0 = foto()
    voz0 = voz()
    ids0 = set(p.clips)
    tl.insercion_inteligente([vid_nuevo], 7.3, v1.id)
    p = ctrl.project
    vn = next(c for c in nuevos(ids0) if c.media_id == vid_nuevo and p.track(c.track_id).kind == TRACK_VIDEO)
    assert abs(vn.start - 6.0) < 1e-6, f"en el corte de la pausa (6 s), no en el de 7,4 s (en una palabra): {vn.start}"
    assert not desfases() and not solapes() and not vinculos_malos()
    print("✓ Mayús al soltar: inserta en el corte cercano que cae en una pausa de la narración")
    deshacer()

    # ---------------------------------------------------------------- atajos sin choques
    from PySide6.QtGui import QAction, QKeySequence
    acts = [a for a in win.findChildren(QAction) if not a.shortcut().isEmpty()]
    for k in ("F9", "F10", "Shift+F11", "F12", "Shift+F12"):
        con = [a.text() for a in acts if a.shortcut() == QKeySequence(k)]
        assert len(con) == 1, (k, con)
    print("✓ F9 / F10 / Mayús+F11 / F12 / Mayús+F12 sin choques")
    print("TODO OK")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    main()
