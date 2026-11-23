"""
🔁 PRUEBA de la fase 4 + 14 de la línea de tiempo: material repetido visible y huella visual por plano.
  · huella: la lectura única la calcula de paso con las escenas (rama «huella») y se guarda por archivo;
  · dos archivos con el mismo plano (una «cinemática» y un «tráiler» que la reutiliza a otro tamaño y otra compresión)
    → los dos clips marcados (otro archivo), con el tooltip diciendo dónde está el otro; lo que no se repite, sin marca;
    dos clips del mismo archivo que se solapan → marcados;
  · «Cambiar por otro tramo no usado» deja los tramos sin solape (ni del mismo archivo ni el mismo momento de otro),
    mueve su sonido vinculado igual, un Ctrl+Z; si en el archivo no queda nada libre, toma uno de su carpeta;
  · bandejas «No usados» y «Usados 2+ veces» cuentan bien (un clip partido = 1; el sonido vinculado no cuenta aparte);
  · Autocompletar y el B-roll (registro Tomados) no usan el mismo plano desde los dos archivos;
  · el mapa con ~3000 clips se calcula rápido (se hace fuera del pintado) y MapaVivo se pone al día solo;
  · el botón, la franja y la acción del clic derecho (menú construido, nunca abierto);
  · con huellas de VIDEOS REALES (solo los hashes, tests/assets/huellas): dos videos distintos → menos del 2 % de
    trozos marcados; el mismo video recomprimido a 480p, con otro desfase, con bandas negras o con zoom → marcado;
  · las bandejas puestas de verdad en Medios (MainWindow) y su filtro; «Cambiar» con el sonido en J/L.
Ejecutar:  .venv/Scripts/python.exe tests/test_repetidos.py <carpeta_salida>
"""
from __future__ import annotations

import os
import random
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None          # (no se abre ningún menú de verdad; solo por si acaso)


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


def solapa(a, b, x, y, tol=0.02):
    return min(b, y) - max(a, x) > tol


def cubre(rangos, a, b) -> bool:
    """¿La unión de los rangos tapa entero el tramo (a, b)?"""
    from editoria.core import scene_pool as SP
    return any(x <= a + 1e-3 and y >= b - 1e-3 for x, y in SP._union(list(rangos)))


def ff(*args):
    from editoria.core import media as M
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", *args], check=True)


def seg(src: str, d: float) -> str:
    return f"{src},trim=duration={d},setpts=PTS-STARTPTS,fps=30,format=yuv420p,setsar=1"


def fabricar(out: str) -> dict:
    """cine.mp4 (12 s, 4 planos), trailer.mp4 (otro tamaño y compresión: su plano del medio es el 2.º plano de la
    cinemática), otro.mp4 (en la misma carpeta, sin usar) y musica.wav."""
    rutas = {k: os.path.join(out, k) for k in ("cine.mp4", "trailer.mp4", "otro.mp4", "musica.wav")}
    if not os.path.exists(rutas["cine.mp4"]):
        ff("-f", "lavfi", "-i", seg("testsrc2=s=640x360:r=30", 3),
           "-f", "lavfi", "-i", seg("life=s=32x18:r=6:seed=7:ratio=0.4:mold=10,scale=640:360:flags=neighbor", 3),
           "-f", "lavfi", "-i", seg("mandelbrot=s=640x360:r=30", 3),
           "-f", "lavfi", "-i", seg("cellauto=s=64x36:r=10:rule=110:random_fill_ratio=0.5:random_seed=3,"
                                    "scale=640:360:flags=neighbor", 3),
           "-f", "lavfi", "-i", "sine=f=330:d=12",
           "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]", "-map", "[v]", "-map", "4:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac", "-shortest", rutas["cine.mp4"])
    if not os.path.exists(rutas["trailer.mp4"]):
        ff("-f", "lavfi", "-i", seg("gradients=s=640x360:r=30:speed=0.03:seed=5", 2),
           "-ss", "3.6", "-t", "2.2", "-i", rutas["cine.mp4"],
           "-f", "lavfi", "-i", seg("colorchart=rate=30:patch_size=64x64,scale=640:360", 2),
           "-f", "lavfi", "-i", "sine=f=550:d=6.2",
           "-filter_complex", "[1:v]scale=640:360,fps=30,format=yuv420p,setsar=1,setpts=PTS-STARTPTS[b];"
                              "[0:v][b][2:v]concat=n=3:v=1:a=0,scale=480:270[v]",
           "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac",
           "-shortest", rutas["trailer.mp4"])
    if not os.path.exists(rutas["otro.mp4"]):
        ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=4", "-f", "lavfi", "-i", "sine=f=660:d=4",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", rutas["otro.mp4"])
    if not os.path.exists(rutas["musica.wav"]):
        ff("-f", "lavfi", "-i", "sine=f=220:d=5", rutas["musica.wav"])
    return rutas


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "repetidos")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import broll_selection as BS
    from editoria.ai import lectura_unica as LU
    from editoria.core import autocompletar as AC
    from editoria.core import huella_plano as HP
    from editoria.core import repetidos as R
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, new_id
    from editoria.ui import repetidos_ui as RU

    rutas = fabricar(out)

    # ---------------------------------------------------------------- 1) la huella, de paso con las escenas
    for k in ("cine.mp4", "trailer.mp4"):
        LU.asegurar(rutas[k], 0, ["escenas"], extras=[])
        assert HP.hecho(rutas[k]), f"la lectura única calcula la huella con las escenas ({k})"
    assert HP.calcular(rutas["otro.mp4"]) is not None
    hc, ht = HP.cargar(rutas["cine.mp4"]), HP.cargar(rutas["trailer.mp4"])
    assert hc is not None and abs(len(hc) - 96) <= 3, len(hc)            # 12 s a 8 por segundo
    assert hc.ok.mean() > 0.8, "casi ningún fotograma liso"
    pc = HP.planos(rutas["cine.mp4"], 12.0)
    pt = HP.planos(rutas["trailer.mp4"], 6.2)
    print("planos cine:", pc, "· tráiler:", pt)
    assert any(abs(a - 3.0) < 0.2 for a, _b in pc) and any(abs(a - 6.0) < 0.2 for a, _b in pc), pc
    assert any(abs(a - 2.0) < 0.2 for a, _b in pt) and any(abs(a - 4.2) < 0.2 for a, _b in pt), pt
    # el plano del medio del tráiler casa con el 2.º de la cinemática con desfase constante (+1,6 s)
    import numpy as np
    tc_, hc_ = hc.de(hc.ok)
    ind = HP.Indice(np.zeros(len(tc_), np.int64), tc_, hc_)
    tq, hq = ht.tramo(2.2, 4.0)
    qi, dj = HP.coincidencias(ind, hq)
    v, a0, a1 = HP.votar(tq[qi], ind.t[dj])
    print(f"votos tráiler→cine: {v} de {len(tq)} fotogramas ({a0:.2f}–{a1:.2f})")
    assert v >= HP.votos_necesarios(len(tq), len(tq)), v
    tq2, hq2 = ht.tramo(0.2, 1.8)                                     # degradado: no está en la cinemática
    qi2, dj2 = HP.coincidencias(ind, hq2)
    v2 = HP.votar(tq2[qi2], ind.t[dj2])[0]
    assert v2 < HP.votos_necesarios(len(tq2), len(tq2)), f"falso parecido: {v2}"

    # ---------------------------------------------------------------- 1b) huellas de videos REALES
    from editoria.core.model import KIND_VIDEO, MediaItem, Project
    dir_h = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "huellas")
    reales = {}
    for k in ("video_a", "video_b", "video_a_480p", "video_a_desfase", "video_a_bandas", "video_a_zoom90"):
        z = np.load(os.path.join(dir_h, f"{k}.npz"))
        ruta = os.path.join(out, f"{k}.mp4")
        open(ruta, "wb").close()                      # (el archivo da igual: la huella se guarda por su ruta)
        HP.guardar(ruta, HP.Huella(z["t"], z["h"], z["ok"], z["hc"]))
        reales[k] = (ruta, float(z["t"][-1]) + HP.STEP)

    def proyecto_real(trozos):
        """trozos = [(video, inicio en el archivo)] de 2 s cada uno, uno detrás de otro en la línea de tiempo."""
        q = Project.new(minimal=True)
        vt = [t for t in q.tracks if t.kind == TRACK_VIDEO][-1]
        mids = {}
        for k, (ruta, dur) in reales.items():
            m = MediaItem(new_id(), ruta, KIND_VIDEO, f"{k}.mp4", duration=dur, probed=True)
            q.media[m.id] = m
            mids[k] = m.id
        cl = []
        for i, (k, src) in enumerate(trozos):
            c = Clip(new_id(), mids[k], vt.id, i * 2.5, float(src), 2.0)
            q.clips[c.id] = c
            cl.append((k, c.id))
        return q, cl

    def paso(k, cada=3.0):
        return [(k, x) for x in np.arange(0.0, reales[k][1] - 2.5, cada)]
    q, cl = proyecto_real(paso("video_a") + paso("video_b"))
    t0 = time.perf_counter()
    mq = R.mapa(q)
    falsos = sum(1 for _k, cid in cl if any(r.otro_archivo for r in mq.get(cid, [])))
    print(f"huellas reales: {falsos} de {len(cl)} trozos de dos videos DISTINTOS marcados "
          f"({100 * falsos / len(cl):.1f} %, {1000 * (time.perf_counter() - t0):.0f} ms)")
    assert falsos / len(cl) < 0.02, (falsos, len(cl))
    ha = HP.cargar(reales["video_a"][0])
    ta_, ha_ = ha.de(ha.ok)
    ia = HP.Indice(np.zeros(len(ta_), np.int64), ta_, ha_)
    # (la misma escena: recomprimida, desfasada, con bandas negras y con zoom al 90 %)
    for k, minimo in (("video_a_480p", 0.9), ("video_a_desfase", 0.7), ("video_a_bandas", 0.8),
                      ("video_a_zoom90", 0.25)):
        hk = HP.cargar(reales[k][0])
        tk_, hk_ = hk.de(hk.ok)
        qi, dj = HP.coincidencias(ia, hk_)
        desfase = float(np.median(ia.t[dj] - tk_[qi]))              # (dónde está esa copia dentro del video A)
        tr = paso(k)
        q, cl = proyecto_real(tr + [("video_a", x + desfase) for _k, x in tr])
        mq = R.mapa(q)
        bien = sum(1 for kk, cid in cl if kk == k and any(r.otro_archivo for r in mq.get(cid, [])))
        print(f"huellas reales: {k}: {bien} de {len(tr)} trozos encontrados en el original (desfase {desfase:.2f} s)")
        assert bien / len(tr) >= minimo, (k, bien, len(tr))

    # ---------------------------------------------------------------- 2) el proyecto (en la ventana de verdad)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.5)
    ctrl = win.ctrl
    ctrl.project.width, ctrl.project.height = 640, 360
    ids = ctrl.import_now([rutas["cine.mp4"], rutas["trailer.mp4"], rutas["otro.mp4"], rutas["musica.wav"]])
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        pump(app, 0.1)
    cine, trailer, otro, musica = ids
    p = ctrl.project
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    v1, v2 = vids[-1], vids[0] if len(vids) > 1 else None
    if v2 is None or v2.id == v1.id:
        v2 = v1
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)

    def poner(mid, tid, start, src, dur, link=""):
        c = Clip(new_id(), mid, tid, start, src, dur, link=link)
        p.clips[c.id] = c
        return c
    A = poner(cine, v1.id, 0.0, 3.4, 2.0)                  # el plano «life» de la cinemática
    C = poner(cine, v1.id, 2.0, 0.5, 2.0)                  # testsrc2: no se repite
    lk = new_id()
    B = poner(trailer, v1.id, 10.0, 2.2, 1.8, link=lk)     # el mismo momento, desde el tráiler (con su sonido)
    Bs = poner(trailer, a1.id, 10.0, 2.2, 1.8, link=lk)
    D = poner(trailer, v1.id, 12.0, 0.2, 1.6)              # degradado: no se repite
    E = poner(cine, v2.id, 20.0, 9.5, 1.5)                 # E y F: mismo archivo, se solapan 1 s
    F = poner(cine, v2.id, 22.0, 10.0, 1.5)
    ctrl._bump_rev()
    mp = R.mapa(p, ctrl.missing)
    print("repetidos:", {p.media[p.clips[k].media_id].name + f"@{p.clips[k].start:g}": [r.otro_archivo for r in v]
                         for k, v in mp.items()})
    assert A.id in mp and B.id in mp, "los dos clips del mismo plano (de archivos distintos), marcados"
    assert any(r.otro == B.id and r.otro_archivo for r in mp[A.id])
    assert any(r.otro == A.id and r.otro_archivo for r in mp[B.id])
    assert C.id not in mp and D.id not in mp and Bs.id not in mp, "lo que no se repite (y el sonido), sin marca"
    assert E.id in mp and F.id in mp and not mp[E.id][0].otro_archivo, "mismo archivo solapado, marcado"
    rb = next(r for r in mp[B.id] if r.otro == A.id)
    t0b, t1b = R.tramo_en_linea(B, rb.a, rb.b)
    assert B.start - 1e-6 <= t0b < t1b <= B.end + 1e-6 and t1b - t0b > 0.8, (t0b, t1b)
    tip = R.texto_tooltip(p, B.id, mp[B.id])
    assert "cine" in tip and "otro archivo" in tip and R.NOMBRE_CAMBIAR in tip, tip
    assert "Halo" not in tip and "Gears" not in tip

    # ---------------------------------------------------------------- 3) bandejas
    S1 = poner(otro, v2.id, 30.0, 0.0, 1.0)                # otro.mp4 partido en dos: cuenta UNA vez
    S2 = poner(otro, v2.id, 31.0, 1.0, 1.0)
    ctrl._bump_rev()
    bj = R.bandejas(p, ctrl.missing)
    print("bandejas:", bj)
    assert bj["no_usados"] == [musica], bj
    assert dict(bj["usados_2"]) == {cine: 4, trailer: 2}, bj           # A, C, E, F · B (+ su sonido), D
    assert [m for m, _n in bj["usados_2"]] == [cine, trailer], "de más veces a menos"
    w = getattr(win.library, "_bandejas_repetidos", None)
    assert isinstance(w, RU.Bandejas), "las bandejas, puestas en Medios al arrancar"
    w.refrescar()
    assert w.btn_no.text() == "No usados · 1" and w.btn_dos.text() == "Usados 2+ veces · 2", \
        (w.btn_no.text(), w.btn_dos.text())
    vistos = []
    w.filtro.connect(lambda ids_, n: vistos.append((ids_, n)))
    w.btn_dos.setChecked(True)
    assert win.library._filtro_ids == {cine, trailer}, "Medios enseña solo esos"
    w.btn_no.setChecked(True)
    assert win.library._filtro_ids == {musica}
    w.btn_no.setChecked(False)
    assert win.library._filtro_ids is None, "y otra vez todo"
    assert vistos == [({cine, trailer}, "Usados 2+ veces"), ({musica}, "No usados"), (None, "")], vistos
    for b in (w.btn_no, w.btn_dos):
        assert b.width() >= b.sizeHint().width() or b.minimumWidth() >= b.sizeHint().width(), "texto entero"
    del p.clips[S1.id], p.clips[S2.id]
    ctrl._bump_rev()

    # ---------------------------------------------------------------- 4) la huella en Autocompletar y en el B-roll
    solo_b = {k: v for k, v in p.clips.items()}
    for k in (A.id, C.id, E.id, F.id):
        del p.clips[k]
    ctrl._bump_rev()
    us = R.usados_con_huella(p, cine, missing=ctrl.missing)
    print("usado de la cinemática (por el tráiler):", us)
    assert cubre(us, 3.8, 5.6), "sus planos enteros cuentan como usados"
    mat = AC.material(pc, us, 12.0)
    assert not any(solapa(a, b, 3.6, 5.8) for a, b in mat), mat
    items, _f = AC.plan(cine, mat, [(0.0, 12.0)], 2.0, 3.0, [], "video")
    assert items and not any(solapa(i["source_in"], i["source_in"] + i["duration"], 3.6, 5.8) for i in items), items
    tom = R.Tomados(p, ctrl.missing, con_linea=False)
    rng = BS.claim(tom, trailer, 2.2, 1.8)
    assert cubre(tom.get(cine, []), 3.9, 5.5), tom
    src = BS.find_free(tom, cine, 4.0, 1.5, 12.0)
    assert src is not None and not solapa(src, src + 1.5, 3.6, 5.8), src
    BS.release(tom, trailer, rng)
    assert not tom.get(cine), "soltar quita también lo reservado en el otro archivo"
    tom2 = R.Tomados(p, ctrl.missing)                      # empieza con la línea de tiempo (B) y su equivalente
    assert cubre(tom2.get(cine, []), 3.9, 5.5), tom2
    p.clips.clear()
    p.clips.update(solo_b)
    ctrl._bump_rev()

    # ---------------------------------------------------------------- 5) «Cambiar por otro tramo no usado»
    def sin_solapes():
        mp_ = R.mapa(p, ctrl.missing)
        por = {}
        for c in p.clips.values():
            if p.track(c.track_id).kind == TRACK_VIDEO:
                por.setdefault(c.media_id, []).append((c.source_in, c.source_in + c.src_len, c.id))
        malos = [(x, y) for lst in por.values() for i, x in enumerate(lst) for y in lst[i + 1:]
                 if solapa(x[0], x[1], y[0], y[1])]
        return malos, mp_

    antes = (B.media_id, B.source_in, Bs.source_in)
    msg = R.cambiar_por_no_usado(ctrl, B.id)
    print("cambiar B:", msg)
    assert msg.startswith("✓"), msg
    assert B.media_id == trailer and abs(B.source_in - 2.2) > 1.0, (B.media_id, B.source_in)
    assert Bs.source_in == B.source_in and Bs.media_id == B.media_id, "su sonido vinculado, igual"
    assert not solapa(B.source_in, B.source_in + B.src_len, D.source_in, D.source_in + D.src_len)
    assert not solapa(B.source_in, B.source_in + B.src_len, 2.0, 4.2, 0.15), "tampoco el plano que repite la cinemática"
    malos, mp2 = sin_solapes()
    assert B.id not in mp2 and A.id not in mp2, mp2
    assert all(c.id in (E.id, F.id) for c in [p.clips[k] for k in mp2]), "solo quedan E y F"
    ctrl.undo_stack.undo()
    B, Bs = p.clips[B.id], p.clips[Bs.id]
    assert (B.media_id, B.source_in, Bs.source_in) == antes, "un Ctrl+Z lo devuelve"
    ctrl.undo_stack.redo()
    msg = R.cambiar_por_no_usado(ctrl, p.clips[F.id].id)
    print("cambiar F:", msg)
    malos, mp3 = sin_solapes()
    assert not malos, malos
    assert E.id not in mp3 and F.id not in mp3, mp3
    # J/L: su sonido empieza 0,4 s antes; al principio del archivo no cabría (se desincronizaba): un tramo con sitio
    lj = new_id()
    J1 = poner(otro, v2.id, 90.0, 2.0, 1.5, link=lj)
    J1s = poner(otro, a1.id, 89.6, 1.6, 1.9, link=lj)
    K1 = poner(otro, v2.id, 95.0, 3.5, 0.5)
    J1.zoom_kf = [{"t": 2.5, "x": 0.5, "y": 0.5, "z": 1.5}]
    ctrl._bump_rev()
    msg = R.cambiar_por_no_usado(ctrl, J1.id)
    print("cambiar J1 (J/L):", msg)
    J1, J1s = p.clips[J1.id], p.clips[J1s.id]
    assert msg.startswith("✓") and J1.media_id == otro and J1s.media_id == otro, msg
    assert abs((J1s.source_in - J1.source_in) + 0.4) < 1e-6, "el sonido sigue 0,4 s por delante"
    assert J1s.source_in >= 0 and J1s.source_in + J1s.src_len <= p.media[otro].duration + 1e-6, J1s.source_in
    assert not solapa(J1.source_in, J1.source_in + J1.src_len, 3.5, 4.0), "ni pisa lo usado"
    assert abs(J1.zoom_kf[0]["t"] - (2.5 + J1.source_in - 2.0)) < 1e-6, "la clave de zoom, con su tramo"
    for k in (J1.id, J1s.id, K1.id):
        del p.clips[k]
    ctrl._bump_rev()
    # con su sonido en OTRO archivo (pista de OBS de la grabación): se mueve con él y solo vale su mismo archivo
    lo = new_id()
    O1 = poner(trailer, v2.id, 100.0, 4.3, 1.5, link=lo)
    O1s = poner(musica, a1.id, 100.0, 1.0, 1.5, link=lo)     # (el «audio de OBS», otro archivo, mismo tiempo)
    ctrl._bump_rev()
    msg = R.cambiar_por_no_usado(ctrl, O1.id)
    print("cambiar O1 (sonido de OBS):", msg)
    O1, O1s = p.clips[O1.id], p.clips[O1s.id]
    if msg.startswith("✓"):
        assert O1.media_id == trailer and O1s.media_id == musica, "mismo archivo; su sonido de OBS, con él"
        assert abs((O1s.source_in - O1.source_in) - (1.0 - 4.3)) < 1e-6, "y con el mismo desfase"
    else:
        assert O1.source_in == 4.3 and O1s.source_in == 1.0, "si no puede llevárselo, no cambia nada"
    elegido = R.elegir_otro_tramo(p, O1.id, ctrl.missing)      # (sin pasarle los vinculados: los busca él)
    assert elegido is None or elegido[0] == trailer, elegido
    for k in (O1.id, O1s.id):
        del p.clips[k]
    ctrl._bump_rev()
    # sin nada libre en su archivo: uno de su carpeta (otro.mp4)
    G = poner(cine, v2.id, 40.0, 0.0, 11.8)
    H = poner(cine, v2.id, 52.0, 1.0, 2.0)
    ctrl._bump_rev()
    msg = R.cambiar_por_no_usado(ctrl, H.id)
    print("cambiar H:", msg)
    H = p.clips[H.id]
    assert H.media_id == otro and "misma carpeta" in msg, (H.media_id, msg)
    malos, mp4 = sin_solapes()                             # (G se solapa a propósito con los demás de la cinemática)
    assert not [x for x in malos if H.id in (x[0][2], x[1][2])] and H.id not in mp4, (malos, mp4)
    # nada libre en ningún sitio: avisa y no toca nada
    I_ = poner(otro, v2.id, 60.0, 0.0, 4.0)
    J = poner(cine, v2.id, 70.0, 0.5, 3.0)
    ctrl._bump_rev()
    n_hist = ctrl.undo_stack.count()
    msg = R.cambiar_por_no_usado(ctrl, J.id)
    print("cambiar J (sin sitio):", msg)
    assert msg.startswith("No queda") and ctrl.undo_stack.count() == n_hist and p.clips[J.id].source_in == 0.5
    for k in (G.id, H.id, I_.id, J.id):
        del p.clips[k]
    ctrl._bump_rev()

    # ---------------------------------------------------------------- 6) rapidez con ~3000 clips (fuera del pintado)
    rnd = random.Random(3)
    guardados = dict(p.clips)
    for k in range(3000):
        mid = rnd.choice([cine, trailer, otro])
        dur = rnd.uniform(0.6, 2.0)
        m = p.media[mid]
        poner(mid, v2.id, 100.0 + k * 2.5, rnd.uniform(0, max(0.0, m.duration - dur)), dur)
    ctrl._bump_rev()
    t0 = time.perf_counter()
    big = R.mapa(p, ctrl.missing)
    t_mapa = (time.perf_counter() - t0) * 1000
    R.mapa(p, ctrl.missing, (ctrl.rev, 1))                 # (la 1.ª vez lo calcula y lo memoriza)
    t0 = time.perf_counter()
    R.mapa(p, ctrl.missing, (ctrl.rev, 1))
    t_memo = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    R.bandejas(p, ctrl.missing)
    t_band = (time.perf_counter() - t0) * 1000
    print(f"mapa con {len(p.clips)} clips: {t_mapa:.0f} ms ({len(big)} marcados) · memorizado: {t_memo:.2f} ms · "
          f"bandejas: {t_band:.0f} ms")
    assert t_mapa < 400, t_mapa
    assert t_memo < 5, t_memo
    assert t_band < 60, t_band
    p.clips.clear()
    p.clips.update(guardados)
    ctrl._bump_rev()

    # ---------------------------------------------------------------- 7) interfaz: MapaVivo, franja, botón, menú
    vivo = RU.MapaVivo(ctrl)
    avisos = []
    vivo.cambio.connect(lambda: avisos.append(1))
    pump(app, 0.6)
    assert set(vivo.mapa) == set(R.mapa(p, ctrl.missing)), "MapaVivo al día tras el cambio"
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    img = QImage(400, 80, QImage.Format_ARGB32)
    img.fill(0)
    pa = QPainter(img)
    r = QRectF(10, 5, 300, 60)
    trz = RU.tramos_px(E, vivo.de(E.id), lambda t: r.left() + (t - E.start) * 100) if vivo.de(E.id) else [(20, 200)]
    RU.pintar_franja(pa, r, trz)
    br = RU.pintar_boton(pa, r)
    pa.end()
    assert br is not None and r.contains(br), br
    assert RU.rect_boton(QRectF(0, 0, 30, 60)) is None, "en un clip pequeño no hay botón"
    assert img.pixelColor(int(trz[0][0]) + 3, int(r.bottom()) - 3).alpha() > 0, "la franja se pinta"
    # clic derecho: la acción solo en un clip repetido (A y B volvieron a repetirse tras el redo? → miramos el mapa)
    menu = QMenu()
    rep_id = next(iter(vivo.mapa), None)
    if rep_id is None:                                     # (si nada se repite ahora, se fabrica uno)
        X = poner(cine, v2.id, 80.0, E.source_in, E.src_len)
        ctrl._bump_rev()
        vivo.recalcular()
        rep_id = X.id
    act = RU.poner_en_menu(menu, ctrl, rep_id, vivo)
    assert act is not None and act.text() == R.NOMBRE_CAMBIAR and act.toolTip()
    assert RU.poner_en_menu(QMenu(), ctrl, D.id, vivo) is None, "en un clip que no se repite, no sale"
    n0 = ctrl.undo_stack.count()
    act.trigger()
    assert ctrl.undo_stack.count() == n0 + 1, "la acción del menú cambia el tramo (un Ctrl+Z)"
    pump(app, 0.6)
    assert rep_id not in vivo.mapa, vivo.mapa
    print("✓ test_repetidos: todo bien")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    app.quit()


if __name__ == "__main__":
    main()
