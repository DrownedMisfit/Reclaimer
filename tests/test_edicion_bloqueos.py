"""
Prueba SIN ventana (controlador en memoria) de los arreglos de edición con bloqueos y casos raros:
  1) 🧲 Supr / recorte magnético no mueven clips de una pista BLOQUEADA (se borra o recorta, sin juntar, y avisa);
  2) partir (insertar espacio, mover con el texto) no parte la pareja vinculada de una pista bloqueada;
     cortar con S y «slide» se saltan la pareja bloqueada en vez de fallar enteros;
  3) cambiar el tipo de proyecto no pisa los fotogramas por segundo;
  4) ni cambia la disposición de los clips de pistas bloqueadas (ni falla si una pista ya no existe);
  5) los generadores (color sólido, degradado) siguen llenando la pantalla tras cambiar de formato;
  6) las claves de animación de una imagen (zoom, caja, opacidad) siguen en su sitio al dividir y al recortar
     el borde izquierdo (recorte normal, ripple, roll, slide, sobrescribir);
  7) pegar un texto en otro proyecto (sin su pista) no falla ni deja clips sin paso de deshacer;
  8) relleno vertical y efectos de sonido a la mitad por TODOS los caminos (no solo «añadir»); el relleno solo a lo
     que no tapa nada de debajo;
  9) Ctrl+D en un clip al revés no pasa del material del archivo.
  + dos pasos seguidos del mismo tipo en clips DISTINTOS no se juntan en un solo Ctrl+Z.
Ejecutar:  .venv/Scripts/python.exe tests/test_edicion_bloqueos.py [carpeta_salida]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import (KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_TEXT,  # noqa: E402
                                 TRACK_VIDEO, MediaItem, Project, new_id)

EPS = 1e-6
SALIDA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                            "_pruebas_tmp", "test_edicion_bloqueos")


def nuevo(minimal=False) -> ProjectController:
    c = ProjectController()
    try:                                   # (sin ventana: nada de picos de onda en segundo plano)
        c.project_changed.disconnect(c._queue_timeline_peaks)
    except Exception:
        pass
    c.project = Project.new(minimal=minimal)
    c.avisos = []
    c.message.connect(c.avisos.append)
    return c


def medio(c, kind=KIND_VIDEO, dur=20.0, w=1920, h=1080, audio=True, nombre="video.mp4", cat="Sin clasificar"):
    m = MediaItem(new_id(), os.path.join("X:\\", "no_existe", nombre), kind, nombre, category=cat,
                  duration=dur if kind != KIND_IMAGE else 0.0, width=w, height=h, fps=30, has_audio=audio,
                  probed=True)
    c.project.media[m.id] = m
    return m


def pistas(c, kind):
    return [t for t in c.project.tracks if t.kind == kind]


def relleno(c, cid) -> bool:
    return bool(((c.project.clips[cid].fx or {}).get("relleno")))


def prueba_iman_bloqueado():
    # Supr magnético: la música de una pista bloqueada no se mueve
    c = nuevo()
    mv = medio(c, audio=False, dur=10)
    mus = medio(c, kind=KIND_AUDIO, dur=5, w=0, h=0, nombre="musica.mp3")
    v1, a1 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_AUDIO)[0]
    x = c.add_media([mv.id], v1.id, 0.0)[0]
    y = c.add_media([mv.id], v1.id, 10.0)[0]
    z = c.add_media([mus.id], a1.id, 15.0)[0]
    c.project.track(a1.id).locked = True
    r = c.magnetic_delete([x], v1.id)
    p = c.project
    assert x not in p.clips, "el clip se borra"
    assert r is False, r
    assert abs(p.clips[z].start - 15.0) < EPS, ("la música bloqueada no se mueve", p.clips[z].start)
    assert abs(p.clips[y].start - 10.0) < EPS, ("sin juntar: lo de detrás se queda", p.clips[y].start)
    assert any("bloquead" in a for a in c.avisos), c.avisos
    print("✓ 1) 🧲 Supr con una pista bloqueada detrás: borra, no junta y avisa")

    # recorte magnético: igual
    c = nuevo()
    mv = medio(c, audio=False, dur=30)
    mus = medio(c, kind=KIND_AUDIO, dur=5, w=0, h=0, nombre="musica.mp3")
    v1, a1 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_AUDIO)[0]
    x = c.add_media([mv.id], v1.id, 0.0)[0]
    c.trim_clip(x, "right", 10.0)
    y = c.add_media([mv.id], v1.id, 10.0)[0]
    z = c.add_media([mus.id], a1.id, 15.0)[0]
    c.project.track(a1.id).locked = True
    c.avisos.clear()
    c.magnetic_trim(x, "right", 6.0)
    p = c.project
    assert abs(p.clips[x].end - 6.0) < 1e-3, p.clips[x].end
    assert abs(p.clips[z].start - 15.0) < EPS and abs(p.clips[y].start - 10.0) < EPS, \
        ("nada se adelanta", p.clips[z].start, p.clips[y].start)
    assert any("bloquead" in a for a in c.avisos), c.avisos
    # sin el candado, sí junta todas las pistas
    c.undo_stack.undo()
    c.project.track(a1.id).locked = False
    c.magnetic_trim(x, "right", 6.0)
    p = c.project
    assert abs(p.clips[y].start - 6.0) < 1e-3 and abs(p.clips[z].start - 11.0) < 1e-3, \
        (p.clips[y].start, p.clips[z].start)
    print("✓ 1) 🧲 recorte magnético con una pista bloqueada detrás: recorta sin juntar (y sin candado, junta todo)")


def prueba_pareja_bloqueada():
    c = nuevo()
    mv = medio(c, audio=True, dur=10)
    v1, v2 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_VIDEO)[0]
    vid, aud = c.add_media([mv.id], v1.id, 0.0)
    p = c.project
    atr = p.clips[aud].track_id
    p.track(atr).locked = True
    img = medio(c, kind=KIND_IMAGE, audio=False, nombre="foto.png")
    ii = c.add_media([img.id], v2.id, 4.0)[0]
    c.change_duration([ii], 2.0)
    assert c.insert_gap([ii])
    p = c.project
    auds = [x for x in p.clips.values() if x.track_id == atr]
    assert len(auds) == 1 and abs(auds[0].start) < EPS and abs(auds[0].duration - 10.0) < EPS, \
        ("el sonido de la pista bloqueada ni se parte ni se mueve", [(x.start, x.duration) for x in auds])
    vids = sorted((x for x in p.clips.values() if x.track_id == v1.id), key=lambda x: x.start)
    assert len(vids) == 2 and abs(vids[1].start - 6.0) < EPS, [(x.start, x.end) for x in vids]
    assert vids[0].link == auds[0].link and not vids[1].link, "el sonido sigue con su trozo (el de la izquierda)"
    print("✓ 2) insertar espacio: la pareja de una pista bloqueada ni se parte ni se desincroniza")

    # mover con el texto
    c = nuevo()
    mv = medio(c, audio=True, dur=20)
    v1 = pistas(c, TRACK_VIDEO)[-1]
    vid, aud = c.add_media([mv.id], v1.id, 0.0)
    atr = c.project.clips[aud].track_id
    c.project.track(atr).locked = True
    c.move_range(5.0, 8.0, 15.0)
    p = c.project
    auds = [x for x in p.clips.values() if x.track_id == atr]
    assert len(auds) == 1 and abs(auds[0].duration - 20.0) < EPS, [(x.start, x.duration) for x in auds]
    assert all(x.link == "" or x.link == auds[0].link for x in p.clips.values())
    assert sum(1 for x in p.clips.values() if x.link == auds[0].link) == 2, "vinculado con UN solo trozo"
    print("✓ 2) mover con el texto: la pareja bloqueada se queda entera")

    # cortar con S (imagen + su sonido de pista bloqueada): corta la imagen y no falla
    c = nuevo()
    mv = medio(c, audio=True, dur=10)
    v1 = pistas(c, TRACK_VIDEO)[-1]
    vid, aud = c.add_media([mv.id], v1.id, 0.0)
    atr = c.project.clips[aud].track_id
    c.project.track(atr).locked = True
    r = c.split(5.0, c.linked_ids([vid]))
    p = c.project
    assert r and len(r) == 1, r
    assert len([x for x in p.clips.values() if x.track_id == atr]) == 1
    assert not p.clips[r[0]].link and p.clips[vid].link == p.clips[aud].link
    print("✓ 2) cortar con S: se salta la pareja bloqueada (antes fallaba entero)")

    # slide: igual
    c = nuevo()
    mv = medio(c, audio=True, dur=30)
    v1 = pistas(c, TRACK_VIDEO)[-1]
    a, aa = c.add_media([mv.id], v1.id, 0.0)
    c.trim_clip(a, "right", 5.0)
    b, ba = c.add_media([mv.id], v1.id, 5.0)
    c.trim_clip(b, "left", 7.0)
    c.trim_clip(b, "right", 10.0)        # (con material libre a los dos lados: se puede deslizar)
    d, da = c.add_media([mv.id], v1.id, 10.0)
    c.trim_clip(d, "right", 15.0)
    atr = c.project.clips[ba].track_id
    c.project.track(atr).locked = True
    assert c.slide_clip(b, 1.0), "slide se salta el sonido de la pista bloqueada"
    p = c.project
    assert abs(p.clips[b].start - 8.0) < 1e-3, p.clips[b].start
    assert abs(p.clips[ba].start - 7.0) < 1e-3 and abs(p.clips[ba].start - 7.0) < 1e-3
    print("✓ 2) slide: se salta la pareja bloqueada")


def prueba_formato():
    c = nuevo()
    c.project.fps = 30.0
    c.set_project_format("short")
    assert c.project.fps == 30.0, c.project.fps
    c.set_project_format("youtube")
    assert c.project.fps == 30.0, c.project.fps
    print("✓ 3) cambiar de tipo de proyecto no pisa tus fotogramas por segundo")

    c = nuevo()
    m43 = medio(c, w=1440, h=1080, audio=False)
    v2 = pistas(c, TRACK_VIDEO)[0]
    cid = c.add_media([m43.id], v2.id, 0.0)[0]
    c.project.clips[cid].layout = None
    c.project.track(v2.id).locked = True
    huerfano = c.add_media([m43.id], pistas(c, TRACK_VIDEO)[-1].id, 30.0)[0]
    c.project.clips[huerfano].track_id = "pista_que_ya_no_existe"
    c.set_project_format("short")
    assert c.project.clips[cid].layout is None, ("pista bloqueada: su disposición no cambia",
                                                 c.project.clips[cid].layout)
    assert not relleno(c, cid)
    c.set_project_format("youtube")
    print("✓ 4) cambiar de formato respeta las pistas bloqueadas (y no falla con una pista que ya no existe)")

    c = nuevo()
    g = medio(c, kind=KIND_IMAGE, w=1920, h=1080, audio=False, nombre="solido.png", cat="Generadores")
    g.gen = {"kind": "solid", "c1": "#ff0000"}
    mv = medio(c, audio=False)
    c.add_media([mv.id], pistas(c, TRACK_VIDEO)[-1].id, 0.0)
    gid = c.add_media([g.id], pistas(c, TRACK_VIDEO)[0].id, 0.0)[0]
    assert c.project.clips[gid].layout is None
    c.set_project_format("short")
    lay = c.project.clips[gid].layout
    assert lay and lay.get("fit") == "stretch" and (lay["w"], lay["h"]) == (1.0, 1.0), lay
    assert not relleno(c, gid)
    g2 = medio(c, kind=KIND_IMAGE, w=1920, h=1080, audio=False, nombre="degradado.png", cat="Generadores")
    g2.gen = {"kind": "linear", "c1": "#000000", "c2": "#ffffff"}
    g2id = c.add_media([g2.id], pistas(c, TRACK_VIDEO)[0].id, 30.0)[0]
    assert (c.project.clips[g2id].layout or {}).get("fit") == "stretch", c.project.clips[g2id].layout
    print("✓ 5) los generadores (color, degradado) siguen llenando la pantalla al cambiar de formato")


def prueba_claves_imagen():
    kz = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5}, {"t": 5.0, "z": 2.0, "x": 0.5, "y": 0.5}]
    kl = [{"t": 0.0, "x": 0, "y": 0, "w": 1, "h": 1}, {"t": 5.0, "x": 0.5, "y": 0, "w": 0.5, "h": 0.5}]
    ko = [{"t": 0.0, "v": 1.0}, {"t": 5.0, "v": 0.0}]

    def con_claves():
        c = nuevo()
        img = medio(c, kind=KIND_IMAGE, w=1920, h=1080, audio=False, nombre="foto.png")
        v1 = pistas(c, TRACK_VIDEO)[-1]
        cid = c.add_media([img.id], v1.id, 0.0)[0]
        c.change_duration([cid], 5.0)
        x = c.project.clips[cid]
        x.zoom_kf, x.layout_kf, x.op_kf = [dict(k) for k in kz], [dict(k) for k in kl], [dict(k) for k in ko]
        return c, cid, img, v1

    def ts(x, d):
        return all([k["t"] for k in getattr(x, a)] == [round(-d, 4), round(5.0 - d, 4)]
                   for a in ("zoom_kf", "layout_kf", "op_kf"))

    c, cid, _img, _v1 = con_claves()
    der = c.split(2.0, [cid])[0]
    R = c.project.clips[der]
    assert ts(R, 2.0), (R.zoom_kf, R.layout_kf, R.op_kf)
    assert ts(c.project.clips[cid], 0.0), "la izquierda conserva las suyas"
    assert R.zoom_kf is not c.project.clips[cid].zoom_kf
    print("✓ 6) dividir una imagen: zoom, caja y opacidad de la derecha siguen en su sitio")

    c, cid, _img, _v1 = con_claves()
    c.trim_clip(cid, "left", 2.0)
    assert ts(c.project.clips[cid], 2.0), c.project.clips[cid].zoom_kf
    c, cid, _img, _v1 = con_claves()
    c.ripple_trim(cid, "left", 1.5)
    assert ts(c.project.clips[cid], 1.5), c.project.clips[cid].zoom_kf
    print("✓ 6) recortar el borde izquierdo (normal y ripple): las claves se desplazan")

    # roll y slide: la imagen de la derecha
    c, cid, img, v1 = con_claves()
    mv = medio(c, audio=False, dur=20)
    izq = c.add_media([mv.id], v1.id, 10.0)[0]
    c.trim_clip(izq, "right", 14.0)
    c.trim_clip(izq, "left", 12.0)                 # (material libre a los dos lados del video)
    c.move_clips({cid: (14.0, v1.id)})            # imagen pegada detrás del video: 14..19
    c.roll_edit(cid, 15.0)
    assert ts(c.project.clips[cid], 1.0), c.project.clips[cid].zoom_kf
    c, cid, img, v1 = con_claves()
    mv = medio(c, audio=False, dur=20)
    a = c.add_media([mv.id], v1.id, 10.0)[0]
    c.trim_clip(a, "right", 13.0)
    b = c.add_media([mv.id], v1.id, 13.0)[0]
    c.trim_clip(b, "left", 15.0)
    c.trim_clip(b, "right", 16.0)
    c.move_clips({cid: (16.0, v1.id)})            # a | b | imagen
    c.slide_clip(b, 0.5)
    assert ts(c.project.clips[cid], 0.5), c.project.clips[cid].zoom_kf
    print("✓ 6) roll y slide: la imagen que cambia de inicio desplaza sus claves")

    # sobrescribir: un clip encima tapa el principio de la imagen
    c, cid, img, v1 = con_claves()
    mv = medio(c, audio=False, dur=20)
    o = c.add_media([mv.id], pistas(c, TRACK_VIDEO)[0].id, 0.0)[0]
    c.trim_clip(o, "right", 2.0)
    c.move_clips({o: (0.0, v1.id)})
    assert ts(c.project.clips[cid], 2.0), (c.project.clips[cid].start, c.project.clips[cid].zoom_kf)
    print("✓ 6) un clip que tapa el principio de la imagen: las claves se desplazan")


def prueba_pegar_texto():
    c = nuevo()
    tid = c.add_text(1.0, 3.0, "Hola")
    c.copy_clips([tid])
    c._replace(Project.new(), None)        # (otro proyecto: el portapapeles sigue)
    n0 = c.undo_stack.count()
    r = c.paste_clips(0.0)
    p = c.project
    assert r and len(r) == 1, r
    assert p.track(p.clips[r[0]].track_id).kind == TRACK_TEXT
    assert c.undo_stack.count() == n0 + 1
    c.undo_stack.undo()
    assert not c.project.clips
    # un video copiado cuya pista ya no existe va a una de su tipo; si su archivo no está, se avisa (sin excepción)
    c = nuevo()
    mv = medio(c, audio=False)
    vid = c.add_media([mv.id], pistas(c, TRACK_VIDEO)[-1].id, 0.0)[0]
    c.copy_clips([vid])
    c._replace(Project.new(), None)        # (otro proyecto: el portapapeles sigue)
    c.project.media[mv.id] = mv
    r = c.paste_clips(0.0)
    assert r and c.project.track(c.project.clips[r[0]].track_id).kind == TRACK_VIDEO
    c._replace(Project.new(), None)        # otro proyecto SIN ese archivo
    assert c.paste_clips(0.0) is None and not c.project.clips
    print("✓ 7) pegar un texto (o un clip) en otro proyecto: va a una pista de su tipo, sin fallar")


def prueba_relleno_y_sfx():
    c = nuevo()
    c.set_project_format("short")
    mh = medio(c, w=1920, h=1080, audio=True)
    v1, v2 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_VIDEO)[0]
    a = c.add_media([mh.id], v1.id, 0.0)
    assert relleno(c, a[0])
    b = c.insert_ranges([{"media_id": mh.id, "start": 30.0, "source_in": 0, "duration": 3}], v1.id, "B-roll")
    assert relleno(c, b[0]), "insert_ranges (B-roll de la IA)"
    s = c.place_segment(mh.id, 0, 3, "insert", 50.0)
    assert relleno(c, s), "place_segment (momentos)"
    k = c.place_clip_at(mh.id, [70.0], [3.0], 0.0)
    assert relleno(c, k[0]), "place_clip_at (palabras clave, sin nada debajo)"
    k2 = c.place_clip_at(mh.id, [2.0], [3.0], 0.0)
    assert not relleno(c, k2[0]), "encima de V1: el relleno taparía lo de debajo"
    kw = c.add_media_at_times([mh.id], [90.0])
    assert kw and relleno(c, kw[0]), "add_media_at_times"
    # add_media en V2 encima de un video: sin relleno; en V2 sin nada debajo: con relleno
    up = c.add_media([mh.id], v2.id, 1.0, audio=False)[0]
    assert c.project.clips[up].track_id != v1.id and not relleno(c, up), "un video encima de otro: sin relleno"
    up2 = c.add_media([mh.id], v2.id, 200.0, audio=False)[0]
    assert relleno(c, up2)
    print("✓ 8) vertical: relleno por todos los caminos y solo en lo que no tapa nada de debajo")

    # lo de debajo solo cuenta si se VE durante la mayor parte del clip
    c = nuevo()
    c.set_project_format("short")
    mh = medio(c, w=1920, h=1080, audio=False)
    v1, v2 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_VIDEO)[0]
    base = c.add_media([mh.id], v1.id, 0.0)[0]
    c.trim_clip(base, "right", 10.0)
    roce = c.add_media([mh.id], v2.id, 10.0 - 1 / 30)[0]          # se solapa UN fotograma con lo de V1
    assert c.project.clips[roce].track_id == v2.id and relleno(c, roce), "un fotograma de solape no cuenta"
    c = nuevo()                                    # (otro proyecto: base 0..20 en V1 y el clip encima en V2)
    c.set_project_format("short")
    mh = medio(c, w=1920, h=1080, audio=False)
    v1, v2 = pistas(c, TRACK_VIDEO)[-1], pistas(c, TRACK_VIDEO)[0]
    base = c.add_media([mh.id], v1.id, 0.0)[0]
    c.project.clips[base].enabled = False          # (como el botón D: desactivado no se ve)
    c._bump_rev()
    tapa = c.add_media([mh.id], v2.id, 2.0, audio=False)[0]
    assert c.project.clips[tapa].track_id == v2.id and relleno(c, tapa), "lo de debajo desactivado no cuenta"
    c.project.clips[base].enabled = True
    c.project.track(v1.id).hidden = True
    c._bump_rev()
    c.project.clips[tapa].fx = None
    assert c._horizontal_sin_encuadre(c.project, c.project.clips[tapa]), "una pista oculta no cuenta"
    c.project.track(v1.id).hidden = False
    assert not c._horizontal_sin_encuadre(c.project, c.project.clips[tapa]), "lo de V1 visible: sí cuenta"
    adj = medio(c, kind=KIND_IMAGE, w=1080, h=1920, audio=False, nombre="ajuste.png", cat="Generadores")
    adj.gen = {"kind": "adjust"}
    c.project.clips[base].media_id = adj.id
    assert c._horizontal_sin_encuadre(c.project, c.project.clips[tapa]), "una capa de ajuste debajo no cuenta"
    print("✓ 8) no cuentan como «debajo» un fotograma de solape, clips desactivados, pistas ocultas ni capas de ajuste")

    # un recorte (PNG con transparencia) sin nada debajo: sin relleno; la misma imagen opaca, con relleno
    import struct
    import zlib

    def png(ruta, alfa):
        w, h = 4, 2
        tipo, px = (6, bytes(4)) if alfa else (2, bytes(3))
        crudo = b"".join(bytes(1) + px * w for _ in range(h))

        def trozo(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        with open(ruta, "wb") as fh:
            fh.write(bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) +
                     trozo(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, tipo, 0, 0, 0)) +
                     trozo(b"IDAT", zlib.compress(crudo)) + trozo(b"IEND", b""))
    os.makedirs(SALIDA, exist_ok=True)
    c = nuevo()
    c.set_project_format("short")
    v2 = pistas(c, TRACK_VIDEO)[0]
    for alfa in (True, False):
        ruta = os.path.join(SALIDA, f"recorte_{int(alfa)}.png")
        png(ruta, alfa)
        im = medio(c, kind=KIND_IMAGE, w=1920, h=1080, audio=False, nombre=os.path.basename(ruta))
        im.path = ruta
        cid = c.add_media([im.id], v2.id, 50.0 if alfa else 60.0)[0]
        assert relleno(c, cid) != alfa, ("con transparencia, sin relleno" if alfa else "opaca, con relleno")
    print("✓ 8) un PNG recortado (con transparencia) no lleva fondo borroso")

    c = nuevo()
    sfx = medio(c, kind=KIND_AUDIO, dur=1.0, w=0, h=0, nombre="whoosh.wav", cat="Efectos")
    a1 = pistas(c, TRACK_AUDIO)[0]
    x = c.add_media([sfx.id], a1.id, 0.0)
    assert c.project.clips[x[0]].volume == 0.5
    y = c.insert_ranges([{"media_id": sfx.id, "start": 5.0, "source_in": 0, "duration": 1}], a1.id, "x")
    assert c.project.clips[y[0]].volume == 0.5, "insert_ranges"
    mv = medio(c, audio=False, dur=10)
    vid = c.add_media([mv.id], pistas(c, TRACK_VIDEO)[-1].id, 0.0)[0]
    n = c.apply_effect_items([{"effect": "file:X:/no_existe/whoosh.wav", "t": 3.0, "clip_id": vid}],
                             {"file:X:/no_existe/whoosh.wav": sfx.id})
    assert n == 1
    sc = [x for x in c.project.clips.values() if (x.note or "").startswith("⭐")]
    assert sc and sc[0].volume == 0.5, [x.volume for x in sc]
    print("✓ 8) efectos de sonido a la mitad también desde la IA y desde «Mis efectos»")


def prueba_ctrl_d_reves():
    c = nuevo()
    m = medio(c, audio=False, dur=10)
    v1 = pistas(c, TRACK_VIDEO)[-1]
    cid = c.add_media([m.id], v1.id, 0.0)[0]
    c.trim_clip(cid, "left", 4.0)           # usa 4..10 del archivo
    c.set_speed([cid], reverse=True)
    x0 = c.project.clips[cid]
    fin0 = x0.source_in + x0.src_len
    c.change_duration([cid], 20.0)
    x = c.project.clips[cid]
    assert x.source_in >= -EPS and x.source_in + x.src_len <= m.duration + EPS, (x.source_in, x.src_len)
    assert abs(x.duration - 10.0) < 1e-3 and abs(x.source_in + x.src_len - fin0) < 1e-3, (x.duration, x.source_in)
    c.change_duration([cid], 3.0)           # acortar al revés: empieza en el mismo fotograma
    x = c.project.clips[cid]
    assert abs(x.source_in + x.src_len - fin0) < 1e-3 and abs(x.duration - 3.0) < 1e-3
    print("✓ 9) Ctrl+D en un clip al revés: no pasa del material y empieza en el mismo fotograma")


def prueba_fallo_inesperado():
    c = nuevo()
    mv = medio(c, audio=False)
    cid = c.add_media([mv.id], pistas(c, TRACK_VIDEO)[-1].id, 0.0)[0]
    avisos = []
    c.project_changed.connect(lambda: avisos.append(1))
    n0 = c.undo_stack.count()

    def roto(p):
        p.clips[cid].start = 99.0
        raise RuntimeError("fallo de prueba")
    try:
        c._edit("Paso roto", roto)
        raise AssertionError("la excepción debe llegar a quien llama")
    except RuntimeError:
        pass
    assert c.project.clips[cid].start == 0.0, "el proyecto vuelve a como estaba"
    assert avisos, "y la interfaz se entera (project_changed)"
    assert c.undo_stack.count() == n0
    print("✓ un fallo inesperado en una edición deja el proyecto como estaba y avisa a la interfaz")


def prueba_deshacer_por_clip():
    c = nuevo()
    mv = medio(c, audio=False)
    v1 = pistas(c, TRACK_VIDEO)[-1]
    a = c.add_media([mv.id], v1.id, 0.0)[0]
    b = c.add_media([mv.id], v1.id, 30.0)[0]
    n0 = c.undo_stack.count()
    c.set_color([a], {"exposure": 0.2})
    c.set_color([a], {"exposure": 0.3})          # el mismo clip enseguida: un solo paso
    assert c.undo_stack.count() == n0 + 1, c.undo_stack.count() - n0
    c.set_color([b], {"exposure": 0.4})          # OTRO clip enseguida: su propio paso
    assert c.undo_stack.count() == n0 + 2, c.undo_stack.count() - n0
    c.undo_stack.undo()
    assert c.project.clips[b].color != {"exposure": 0.4} and c.project.clips[a].color == {"exposure": 0.3},         (c.project.clips[a].color, c.project.clips[b].color)
    print("✓ pasos seguidos del mismo tipo: se juntan en el mismo clip, no entre clips distintos")


def main():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)   # (sin ventana; al salir, limpio)
    assert app is not None
    prueba_iman_bloqueado()
    prueba_pareja_bloqueada()
    prueba_formato()
    prueba_claves_imagen()
    prueba_pegar_texto()
    prueba_relleno_y_sfx()
    prueba_ctrl_d_reves()
    prueba_fallo_inesperado()
    prueba_deshacer_por_clip()
    print("TODO OK")


if __name__ == "__main__":
    main()
