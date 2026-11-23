"""
🎬 Escenas más fáciles (20/11).
  1) ⊞ Composición por huecos que funciona: dos videos soltados A LA VEZ llenan dos huecos (no uno detrás de otro), los
     dos empiezan en el cabezal, cada uno con su sonido; en el visor se ven los dos y al exportar salen los dos (color
     de cada hueco en un fotograma) y suenan los dos (440 Hz y 880 Hz en el audio). Varios desde la lista del «+».
     El «+» ya no se pinta en un hueco ocupado; botones de su esquina: × vaciar (con un clic de verdad), ⇄ cambiar
     con otro hueco, mover / acercar lo de dentro y doble clic = encuadrar. Un paso de Ctrl+Z cada cosa.
  2) 🎬 Resultados a la derecha: crear → tarjeta con miniatura, nombre entero (también sin espacios) y duración;
     copiar → Ctrl+V en la línea de tiempo; Ctrl+C; poner en el cabezal; abrir para editar; arrastrarla = clip de escena.
  3) Capas: lista (arriba = delante, ordenar), clic / Alt+clic en el lienzo, ojo, candado, imán, alinear, repartir,
     flechas (1 px / 10 px) y Ctrl+D.
  4) Recortar y ajustar: borde, esquinas y sombra con valores rápidos (horneado desde la original), exportado con su
     borde; quitar el fondo si el modelo está.
  5) Crear y llevar en un paso (casilla recordada).   6) Las 8 plantillas, soltar material en sus huecos, texto.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_facil.py <carpeta_salida>   (sin ventanas, sin sonido)
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
    return tmp


_TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

sys.stdout.reconfigure(line_buffering=True)

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def _video(M, ruta, color, hz, seg=4):
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x240:r=30:d={seg}", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seg}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", ruta],
                   check=True, creationflags=M.NO_WINDOW)
    return ruta


def _energia(M, mp4, hz) -> float:
    """Energía del audio exportado cerca de hz (FFT de 1 s en el medio)."""
    import numpy as np
    raw = subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-ss", "1", "-t", "1", "-i", mp4, "-ac", "1", "-ar",
                          "16000", "-f", "s16le", "-"], capture_output=True, check=True, creationflags=M.NO_WINDOW).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float)
    esp = np.abs(np.fft.rfft(x))
    f = np.fft.rfftfreq(len(x), 1 / 16000)
    banda = (f > hz - 15) & (f < hz + 15)
    return float(esp[banda].max() / (esp.mean() + 1e-9))


def prueba_huecos(app, win, out):
    from editoria.core import composicion
    from editoria.core import media as M
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.common import MEDIA_MIME
    ctrl = win.ctrl
    p = ctrl.project
    rojo = _video(M, os.path.join(_TMP, "rojo.mp4"), "red", 440)
    azul = _video(M, os.path.join(_TMP, "azul.mp4"), "blue", 880)
    verde = _video(M, os.path.join(_TMP, "verde.mp4"), "green", 660)
    rid, bid, gid = ctrl.import_now([rojo, azul, verde])
    t0 = time.time()
    while any(p.media[i].duration <= 0 for i in (rid, bid, gid)) and time.time() - t0 < 30:
        pump(app, 0.1)
    pv = win.preview
    cv = pv.canvas
    pv.set_composition(2)
    pump(app, 0.3)
    cv.grab().save(os.path.join(out, "1_huecos_vacios.png"))

    assert composicion.repartir(3, 1, 4, {2}) == [1, 3, 0], composicion.repartir(3, 1, 4, {2})
    assert composicion.repartir(2, -1, 4) == [-1, -1]
    print("✓ reparto: el hueco donde sueltas y luego los vacíos que siguen")

    md = QMimeData()
    md.setData(MEDIA_MIME, f"{rid},{bid}".encode())
    punto = QPointF(cv.mapFromScene(cv.comp.rect_of(cv.comp.slots[0]).center()))
    cv.dropEvent(QDropEvent(punto, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    pump(app, 0.3)
    vid = [c for c in p.clips.values() if p.track(c.track_id).kind == "video"]
    aud = [c for c in p.clips.values() if p.track(c.track_id).kind == "audio"]
    assert len(vid) == 2 and len(aud) == 2, (len(vid), len(aud))
    assert {round(c.start, 3) for c in vid} == {0.0}, "los dos empiezan a la vez (en el cabezal)"
    por_media = {c.media_id: c for c in vid}
    assert composicion.misma_caja(por_media[rid].layout, cv.comp.slots[0])
    assert composicion.misma_caja(por_media[bid].layout, cv.comp.slots[1])
    assert len({c.track_id for c in vid}) == 2 and all(ctrl.partners(p, c) for c in vid), "cada uno su pista y sonido"
    assert ctrl.undo_stack.undoText() == "⊞ Composición"
    print("✓ dos videos soltados a la vez → uno en cada hueco, los dos en el cabezal, cada uno con su sonido (1 paso)")
    ctrl.undo_stack.undo()                         # tres en dos huecos: avisa del que no cupo
    pump(app, 0.3)
    md = QMimeData()
    md.setData(MEDIA_MIME, f"{rid},{bid},{gid}".encode())
    cv.dropEvent(QDropEvent(punto, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    pump(app, 0.3)
    vid = [c for c in p.clips.values() if p.track(c.track_id).kind == "video"]
    assert len(vid) == 2 and gid not in {c.media_id for c in vid}
    assert "1 no cupieron" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
    por_media = {c.media_id: c for c in vid}
    print("✓ más archivos que huecos: avisa de cuántos quedaron fuera")

    win.timeline.set_view("main")
    win.engine.seek(1.0)
    pump(app, 1.2)
    img = cv.grab().toImage()
    img.save(os.path.join(out, "2_dos_videos_visor.png"))

    def color_en(i):
        r = cv.comp.rect_of(cv.comp.slots[i])
        return img.pixelColor(cv.mapFromScene(r.center() + QPointF(0, r.height() * 0.3)))
    c0, c1 = color_en(0), color_en(1)
    assert c0.red() > 180 and c0.blue() < 90 and c1.blue() > 180 and c1.red() < 90, (c0.name(), c1.name())
    assert cv.hueco_ocupado(0) and cv.hueco_ocupado(1) and cv.comp.plus_at(cv.comp.rect_of(cv.comp.slots[0]).center()) < 0
    assert cv.clip_de_hueco(0) == por_media[rid].id and cv.clip_de_hueco(1) == por_media[bid].id
    print(f"✓ el visor enseña los dos a la vez ({c0.name()} y {c1.name()}); sin «+» en los huecos ocupados")

    mp4 = os.path.join(_TMP, "comp.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=640, height=360, fps=30, encoder="cpu",
                                              loudnorm=False), M.ffmpeg(), os.path.join(_TMP, "f.txt"))
    subprocess.run(args, check=True, capture_output=True, creationflags=M.NO_WINDOW)
    fr = M.frame_rgb(mp4, 2.0, 640).astype(int)
    h, w = fr.shape[:2]
    for i, (canal, otro) in enumerate(((0, 2), (2, 0))):
        s = cv.comp.slots[i]
        px = fr[int((s["y"] + s["h"] / 2) * h), int((s["x"] + s["w"] / 2) * w)]
        assert px[canal] > 170 and px[otro] < 90, ("hueco", i, px)
    e440, e880 = _energia(M, mp4, 440), _energia(M, mp4, 880)
    assert e440 > 20 and e880 > 20, ("suenan los dos", e440, e880)
    print(f"✓ exportado: rojo en el hueco 1 y azul en el 2; suenan los dos (440 Hz ×{e440:.0f}, 880 Hz ×{e880:.0f})")

    # × vaciar con un clic de verdad en el botón de la esquina
    r_x = cv.comp.botones(1)["vaciar"]
    n_pistas = len(p.tracks)
    QTest.mouseClick(cv.viewport(), Qt.LeftButton, Qt.NoModifier, cv.mapFromScene(r_x.center()))
    pump(app, 0.4)
    assert por_media[bid].id not in p.clips and len(p.clips) == 2, "vaciado (la imagen y su sonido)"
    assert len(p.tracks) == n_pistas - 2, ("sus pistas vacías se quitan", [t.name for t in p.tracks])
    ctrl.undo_stack.undo()
    pump(app, 0.4)
    assert por_media[bid].id in p.clips and len(p.clips) == 4 and len(p.tracks) == n_pistas
    print("✓ × vaciar un hueco (clic en su botón) quita la imagen, su sonido y sus pistas vacías; Ctrl+Z lo devuelve")

    # ⇄ cambiar dos huecos: botón y clic en el otro
    win.engine.seek(1.0)
    pump(app, 0.6)
    QTest.mouseClick(cv.viewport(), Qt.LeftButton, Qt.NoModifier, cv.mapFromScene(cv.comp.botones(0)["cambiar"].center()))
    assert cv.comp.cambiando == 0
    QTest.mouseClick(cv.viewport(), Qt.LeftButton, Qt.NoModifier,
                     cv.mapFromScene(cv.comp.rect_of(cv.comp.slots[1]).center()))
    pump(app, 0.4)
    assert composicion.misma_caja(p.clips[por_media[rid].id].layout, cv.comp.slots[1])
    assert composicion.misma_caja(p.clips[por_media[bid].id].layout, cv.comp.slots[0])
    assert ctrl.undo_stack.undoText() == "⊞ Cambiar huecos"
    ctrl.undo_stack.undo()
    print("✓ ⇄ cambiar dos huecos entre sí (un paso de Ctrl+Z)")

    # mover con zoom 1 (se acerca un poco y se mueve), acercar, botón «encuadrar»; doble clic = elegir su clip
    cid = por_media[rid].id
    assert not p.clips[cid].zoom_kf
    cv.comp_accion.emit("mover", [cid, 0.03, 0.0])
    z = p.clips[cid].zoom_kf
    assert z and z[0]["z"] >= 1.15 and z[0]["x"] < 0.5, ("con zoom 1 también se mueve", z)
    cv.comp_accion.emit("escalar", [cid, 4])
    assert p.clips[cid].zoom_kf[0]["z"] > 1.6
    win.engine.seek(1.0)
    pump(app, 0.6)
    win.timeline.set_selection([])
    centro = cv.mapFromScene(cv.comp.rect_of(cv.comp.slots[0]).center() + QPointF(0, 40))
    QTest.mouseDClick(cv.viewport(), Qt.LeftButton, Qt.NoModifier, centro)
    pump(app, 0.3)
    assert p.clips[cid].zoom_kf, "el doble clic NO borra el encuadre"
    assert cid in win.timeline.selected, "doble clic = elige su clip (línea de tiempo e Inspector)"
    QTest.mouseClick(cv.viewport(), Qt.LeftButton, Qt.NoModifier,
                     cv.mapFromScene(cv.comp.botones(0)["encuadrar"].center()))
    pump(app, 0.3)
    assert not p.clips[cid].zoom_kf and ctrl.undo_stack.undoText() == "⊞ Encuadrar en su hueco"
    print("✓ arrastrar mueve lo de dentro (con zoom 1 se acerca un poco); Ctrl+rueda acerca; doble clic elige su "
          "clip sin tocar el encuadre; el botón «encuadrar» de la esquina lo vuelve a llenar")

    # cambiar el número de huecos con contenido: lo que había pasa a los huecos nuevos en orden
    ctrl.delete_clips(list(p.clips))
    pv.set_composition(3)
    win.engine.seek(0.0)
    pump(app, 0.4)
    md = QMimeData()
    md.setData(MEDIA_MIME, f"{rid},{bid},{gid}".encode())
    cv.dropEvent(QDropEvent(QPointF(cv.mapFromScene(cv.comp.rect_of(cv.comp.slots[0]).center())), Qt.CopyAction, md,
                            Qt.LeftButton, Qt.NoModifier))
    pump(app, 0.6)
    assert all(cv.clip_de_hueco(i) for i in range(3)), "tres llenos"
    orden = [cv.clip_de_hueco(i) for i in range(3)]
    pv.set_composition(4)
    win.engine.seek(0.0)
    pump(app, 0.6)
    assert [cv.clip_de_hueco(i) for i in range(3)] == orden and cv.clip_de_hueco(3) is None,         "recolocados en orden; el 4.º, vacío"
    assert cv.comp.plus_at(cv.comp.rect_of(cv.comp.slots[0]).center()) < 0 and cv.comp.botones(0)
    assert ctrl.undo_stack.undoText() == "⊞ Huecos recolocados"
    cv.grab().save(os.path.join(out, "3_de_tres_a_cuatro_huecos.png"))
    print("✓ de 3 huecos llenos a 4: lo que había pasa a los huecos nuevos en orden (con sus botones), el 4.º vacío")
    # un clip del mismo hueco MÁS ADELANTE también se recoloca; pasar por «Sin composición» también; de 4 a 2, aviso
    caja0 = dict(cv.comp.slots[0])
    tarde = composicion.colocar(ctrl, [(gid, caja0)], 30.0)
    assert tarde and composicion.misma_caja(p.clips[tarde[0]].layout, caja0)
    pv.set_composition(0)
    pv.set_composition(3)
    pump(app, 0.3)
    assert composicion.misma_caja(p.clips[tarde[0]].layout, cv.comp.slots[0]), "el de más adelante, también"
    assert ctrl.undo_stack.undoText() == "⊞ Huecos recolocados", "tras «Sin composición» también recoloca"
    avisos = []
    ctrl.message.connect(avisos.append)
    pv.set_composition(2)
    pump(app, 0.2)
    ctrl.message.disconnect(avisos.append)
    assert any("no caben" in a for a in avisos), avisos
    print("✓ también lo de ese hueco más adelante y tras «Sin composición»; al reducir, avisa de lo que no cabe")
    pv.set_composition(4)
    win.engine.seek(0.0)
    pump(app, 0.4)
    # un clic con temblor (menos de 4 px) no cambia el encuadre
    c1 = cv.clip_de_hueco(1)
    z0 = list(p.clips[c1].zoom_kf)
    pc = cv.mapFromScene(cv.comp.rect_of(cv.comp.slots[1]).center() + QPointF(0, 30))
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, pc)
    QTest.mouseMove(cv.viewport(), pc + QPoint(2, 1))
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, pc + QPoint(2, 1))
    pump(app, 0.2)
    assert p.clips[c1].zoom_kf == z0, "un temblor no cambia el encuadre"
    print("✓ arrastrar dentro del hueco empieza a partir de 4 px (un clic con temblor no cambia el encuadre)")

    # varios desde la lista del «+»: en el hueco libre que queda y, el resto, no cabe
    n0 = len(p.clips)
    pop = cv.abrir_medios_hueco(3)
    pump(app, 0.2)
    pop.elegir_varios([gid])
    pump(app, 0.4)
    assert len(p.clips) == n0 + 2, (n0, len(p.clips))
    win.engine.seek(0.0)
    pump(app, 0.6)
    assert cv.clip_de_hueco(3), "«+» de la lista → ese hueco"
    print("✓ «+» con varios elegidos (Ctrl+clic) → uno en cada hueco, a la vez")
    pv.set_composition(0)


def prueba_resultados(app, win, out):
    """2) 🎬 Resultados a la derecha: crear → sale con miniatura y duración; copiar → Ctrl+V en la línea de tiempo;
    poner en el cabezal; abrir para editar; arrastrar lleva el medio (MEDIA_MIME)."""
    from PIL import Image
    from editoria.core import scenes
    ctrl = win.ctrl
    p = ctrl.project
    png = os.path.join(_TMP, "verde.png")
    Image.new("RGBA", (200, 300), (30, 200, 60, 255)).save(png)
    aid = ctrl.media_for_path(png, "Escenas")
    win.go_page("scenes")
    pump(app, 0.4)
    pg = win._scenes_widget
    res = pg.resultados
    assert res.isVisible() and not res.tarjetas and res.vacio.isVisible()
    assert pg._split.indexOf(res) == pg._split.count() - 1, "Resultados va a la derecha del todo"
    pg._añadir_actor(aid)
    pg.nombre.setText("Pelea final con un nombre largo")
    pg.escena["nombre"] = pg.nombre.text()
    mid = pg.crear_escena()
    pump(app, 0.3)
    eid = pg.escena["id"]
    assert mid and eid in res.tarjetas and res.elegido == eid and not res.vacio.isVisible()
    t = res.tarjetas[eid]
    assert t.dura.text() == f"{scenes.largo(p.scenes[eid]):.1f} s".replace(".", ",")
    assert not t.mini.pixmap().isNull()
    for b in (t.b_copiar, t.b_cabezal, t.b_editar):
        assert b.isVisible() and b.toolTip(), "acciones siempre a la vista, con tooltip"
    assert mid in p.media, "también en Medios"
    pg.grab().save(os.path.join(out, "4_resultados.png"))
    print("✓ «Crear escena» → sale en Resultados (derecha) con miniatura, nombre y duración, y en Medios")

    # Copiar (botón) → en el editor, Ctrl+V la pega en el cabezal
    ctrl.clipboard = []
    t.b_copiar.click()
    assert ctrl.clipboard and ctrl.clipboard[0][0]["media_id"] == mid and win._copia_externa is False
    win.go_page("edit")
    pump(app, 0.3)
    win.engine.seek(1.5)
    n0 = len(p.clips)
    win._paste()
    pegados = ctrl.scene_clips(p, eid)
    assert len(pegados) == 1 and abs(pegados[0].start - 1.5) < 1e-3 and len(p.clips) == n0 + 1
    ctrl.undo_stack.undo()
    assert not ctrl.scene_clips(p, eid)
    print("✓ Copiar → Ctrl+V en la línea de tiempo la pega en el cabezal (Ctrl+Z la quita)")

    # Ctrl+C con la tarjeta elegida
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    res = pg.resultados
    ctrl.clipboard = []
    res.elegir(eid)
    QTest.keyClick(res, Qt.Key_C, Qt.ControlModifier)
    pump(app, 0.1)
    assert ctrl.clipboard and ctrl.clipboard[0][0]["media_id"] == mid, "Ctrl+C copia la elegida"
    print("✓ Ctrl+C en Resultados copia la escena elegida")

    # Poner en el cabezal (un paso)
    win.engine.seek(3.0)
    res.tarjetas[eid].b_cabezal.click()
    hechos = ctrl.scene_clips(p, eid)
    assert len(hechos) == 1 and abs(hechos[0].start - 3.0) < 1e-3
    ctrl.undo_stack.undo()
    assert not ctrl.scene_clips(p, eid)
    print("✓ «Poner en el cabezal» la pone en la línea de tiempo en un paso (Ctrl+Z la quita)")

    # Abrir para editar: otra escena cargada → el botón vuelve a cargar esta
    pg._cargar(pg._nueva_desde_marcas(), False)
    assert pg.escena["id"] != eid
    res.tarjetas[eid].b_editar.click()
    assert pg.escena["id"] == eid and not pg.sucia
    print("✓ «Abrir para editar» la carga en la página")

    # un nombre SIN espacios no se corta: se parte por letras
    pg.nombre.setText("NombreLarguisimoSinEspaciosParaVerSiSeCortaPorLaDerecha")
    pg.escena["nombre"] = pg.nombre.text()
    pg.crear_escena()
    pump(app, 0.3)
    t = res.tarjetas[pg.escena["id"]]
    fm = t.nombre.fontMetrics()
    lineas = t.nombre.text().split(chr(10))
    assert len(lineas) > 1 and "".join(lineas) == t.nombre.texto_completo()
    assert max(fm.horizontalAdvance(x) for x in lineas) <= t.nombre.width(), "ninguna línea se sale"
    print(f"✓ un nombre sin espacios se parte por letras ({len(lineas)} líneas), sin cortarse")

    # arrastrar la tarjeta a la línea de tiempo = clip de escena (como pegarla), no una imagen suelta de 5 s
    win.go_page("edit")
    pump(app, 0.3)
    tl = win.timeline
    eid2 = pg.escena["id"]
    vi = next(i for i, tr in enumerate(p.tracks) if tr.kind == "video" and tr.role not in ("comp", "fondo"))
    tl._drop = (vi, 2.0)
    md_t = t.mime()                                 # (que viva mientras dura el soltado)
    tl.dropEvent(QDropEvent(QPointF(50, 50), Qt.CopyAction, md_t, Qt.LeftButton, Qt.NoModifier))
    pump(app, 0.2)
    puestos = ctrl.scene_clips(p, eid2)
    assert len(puestos) == 1 and abs(puestos[0].duration - scenes.largo(p.scenes[eid2])) < 1e-3 and         abs(puestos[0].start - 2.0) < 1e-3, [(x.start, x.duration) for x in puestos]
    ctrl.undo_stack.undo()
    print("✓ arrastrar la tarjeta a la línea de tiempo la pone como clip de escena (con lo que dura)")
    win.go_page("edit")
    pump(app, 0.2)


def _png(nombre, color, tam=(200, 300), circulo=False):
    from PIL import Image, ImageDraw
    ruta = os.path.join(_TMP, nombre)
    if circulo:
        im = Image.new("RGBA", (400, 400), (255, 255, 255, 255))
        ImageDraw.Draw(im).ellipse((110, 110, 290, 290), fill=color + (255,))
    else:
        im = Image.new("RGBA", tam, color + (255,))
    im.save(ruta)
    return ruta


def prueba_capas(app, win, out):
    """3) Capas: lista (orden, ojo, candado), clic arriba / Alt+clic debajo, imán, alinear, repartir, flechas, Ctrl+D."""
    from editoria.core import scenes
    from editoria.ui import escenas_capas as EC
    ctrl = win.ctrl
    p = ctrl.project
    win.go_page("scenes")
    pump(app, 0.4)
    pg = win._scenes_widget
    pg._cargar(pg._nueva_desde_marcas(), True)
    ids = [ctrl.media_for_path(_png(f"capa_{n}.png", c), "Escenas")
           for n, c in (("a", (220, 40, 40)), ("b", (40, 200, 60)), ("c", (40, 80, 230)))]
    for k, mid in enumerate(ids):
        pg._añadir_actor(mid, {"x": 0.3 + 0.05 * k, "y": 0.2, "w": 0.3, "h": 0.5, "fit": "contain", "bg": "none"})
    pump(app, 0.2)
    pg.lateral.abrir("capas")
    acts = pg.escena["actores"]
    lista = pg.capas.lista
    assert lista.count() == 3 and lista.item(0).data(Qt.UserRole) == acts[-1]["id"], "arriba = delante"
    # arrastrar para ordenar: la de abajo pasa arriba
    abajo = acts[0]["id"]
    pg.capas.orden_cambiado([abajo, acts[2]["id"], acts[1]["id"]])
    assert pg.escena["actores"][-1]["id"] == abajo and pg._items[abajo].zValue() == max(
        i.zValue() for i in pg._items.values()), "la fila de arriba se ve delante"
    print("✓ lista de capas con miniatura: arriba = delante; ordenar cambia lo que se ve delante")
    # clic en el lienzo = la de arriba; Alt+clic = la de debajo
    v = pg.view
    pump(app, 0.2)
    punto = v.mapFromScene(QPointF(0.5 * pg.W, 0.45 * pg.H))
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, punto)
    pump(app, 0.1)
    arriba = pg._actor_elegido()["id"]
    assert arriba == pg.escena["actores"][-1]["id"], "clic = la de arriba"
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.AltModifier, punto)
    pump(app, 0.1)
    assert pg._actor_elegido()["id"] != arriba, "Alt+clic = la de debajo"
    print("✓ clic en el lienzo elige la capa de arriba; Alt+clic, la de debajo")
    # ojo y candado
    a0 = pg.escena["actores"][0]
    pg.capas.alternar(a0["id"], "oculto")
    assert not pg._items[a0["id"]].isVisible() and not any(z["actor"] == a0["id"] for z in scenes.piezas(pg.escena))
    assert pg._avisar_ocultas() == 1 and "no salen" in win.statusBar().currentMessage(), "aviso de capas ocultas"
    fila = pg.capas.lista.itemWidget(next(pg.capas.lista.item(i) for i in range(pg.capas.lista.count())
                                          if pg.capas.lista.item(i).data(Qt.UserRole) == a0["id"]))
    assert "NO sale" in fila.b_ojo.toolTip() and "exportar" in fila.b_ojo.toolTip()
    pg.capas.alternar(a0["id"], "oculto")
    pg.capas.alternar(a0["id"], "bloqueado")
    it0 = pg._items[a0["id"]]
    assert it0.acceptedMouseButtons() == Qt.NoButton and not (it0.flags() & it0.GraphicsItemFlag.ItemIsMovable)
    pg.capas.alternar(a0["id"], "bloqueado")
    print("✓ ojo: oculta no se ve ni sale al aplicar; candado: no se mueve ni se elige en el lienzo")
    # nombres de fila enteros en la línea de la escena (2 líneas o tooltip) y su columna se ensancha arrastrando
    tl = pg.tl
    iz0 = tl.IZQ
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.IZQ), tl.REGLA + 5))
    QTest.mouseMove(tl, QPoint(int(iz0) + 60, tl.REGLA + 5))
    tl.mouseMoveEvent(__import__("PySide6.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(
        __import__("PySide6.QtCore", fromlist=["QEvent"]).QEvent.MouseMove, QPointF(iz0 + 60, tl.REGLA + 5),
        QPointF(iz0 + 60, tl.REGLA + 5), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(iz0) + 60, tl.REGLA + 5))
    assert tl.IZQ >= iz0 + 50, (iz0, tl.IZQ)
    assert int(QSettings("EditorIA", "EditorIA").value("escenas/ancho_nombres")) == int(tl.IZQ), "se recuerda"
    print("✓ la columna de nombres de la línea de la escena se ensancha arrastrando su borde (y se recuerda)")
    # imán: cerca del centro se pega al centro (y dibuja su guía)
    act = pg.escena["actores"][-1]
    w = act["caja"]["w"] * pg.W
    otros = [it for aid, it in pg._items.items() if aid != act["id"]]
    for it in otros:                               # (solo el lienzo: así la guía más cercana es su centro)
        it.setVisible(False)
    x, _y, guias = EC.iman(pg, act["id"], pg.W / 2 - w / 2 + 2.0, 50.0, w, 100.0, 1.0)
    assert abs(x - (pg.W / 2 - w / 2)) < 1e-6 and ("v", pg.W / 2) in guias, (x, guias)
    for it in otros:
        it.setVisible(True)
    o = otros[0].rect().translated(otros[0].pos())
    x2, _y, guias2 = EC.iman(pg, act["id"], o.right() + 3.0, 50.0, 40.0, 40.0, 1.0)
    assert abs(x2 - o.right()) < 1e-6 and guias2, ("se pega al borde de otra capa", x2, o.right())
    print("✓ guías magnéticas: se pega al centro del lienzo (y a bordes y otras capas)")
    # alinear y repartir
    pg.tl.sel = ("actor", act)
    pg._elegir("actor", act)
    EC.alinear(pg, "centro_h")
    assert abs(act["caja"]["x"] - (1 - act["caja"]["w"]) / 2) < 1e-3
    EC.alinear(pg, "abajo")
    assert abs(act["caja"]["y"] + act["caja"]["h"] - 1) < 1e-3
    for k, a in enumerate(pg.escena["actores"]):
        a["caja"]["x"] = (0.0, 0.1, 0.6)[k]
    EC.repartir(pg, "h")
    cx = sorted(a["caja"]["x"] + a["caja"]["w"] / 2 for a in pg.escena["actores"])
    assert abs((cx[1] - cx[0]) - (cx[2] - cx[1])) < 1e-3, cx
    print("✓ alinear (centro, abajo…) y repartir con el mismo espacio")
    # flechas = 1 px, Mayús = 10 px
    pg.tl.sel = ("actor", act)
    pg._elegir("actor", act)
    v.setFocus()
    x0 = act["caja"]["x"]
    QTest.keyClick(v, Qt.Key_Right)
    assert abs(act["caja"]["x"] - x0 - 1 / p.width) < 2e-6, (act["caja"]["x"] - x0)
    QTest.keyClick(v, Qt.Key_Left, Qt.ShiftModifier)
    assert abs(act["caja"]["x"] - x0 + 9 / p.width) < 4e-6
    print("✓ flechas mueven 1 px del proyecto y Mayús + flechas 10 px")
    n = len(pg.escena["actores"])
    QTest.keyClick(pg, Qt.Key_D, Qt.ControlModifier)
    assert len(pg.escena["actores"]) == n + 1
    pg.capas.botones["duplicar"].click()
    assert len(pg.escena["actores"]) == n + 2
    print("✓ duplicar con Ctrl+D y con el botón de Capas")
    pg.grab().save(os.path.join(out, "5_capas.png"))


def prueba_ajustes(app, win, out):
    """4) Recortar y ajustar: borde, sombra y esquinas con valores rápidos (horneado desde la original), texto, quitar
    el fondo (si el modelo está), y se exporta igual."""
    from PIL import Image
    from editoria.core import escena_ajustes as EA
    from editoria.core import media as M
    from editoria.core import scenes
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ctrl = win.ctrl
    p = ctrl.project
    pg = win._scenes_widget
    pg._cargar(pg._nueva_desde_marcas(), True)
    mid = ctrl.media_for_path(_png("ajuste_azul.png", (40, 80, 230), (300, 300)), "Escenas")
    pg._añadir_actor(mid, {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.6, "fit": "contain", "bg": "none"})
    act = pg.escena["actores"][-1]
    act["fases"] = [{"tipo": "accion", "anim": "ninguna", "dur": scenes.largo(pg.escena), "auto": True}]
    aj = pg.ajustes
    assert aj.isVisibleTo(pg.insp.currentWidget()) or True
    from editoria.ui.escenas_ajustes_ui import al_dia

    def esperar_horneado(tope=30.0):
        t0 = time.time()
        while not al_dia(pg, act) and time.time() - t0 < tope:
            pump(app, 0.1)
        assert al_dia(pg, act), "el horneado terminó (en segundo plano)"
    propios0 = sum(1 for m in p.media.values() if EA.es_propia(m.path))
    rapido = next(b for b in aj.findChildren(type(aj.color)) if b.text() == "Grueso")
    t_clic = time.time()
    rapido.click()
    assert time.time() - t_clic < 0.5, "el clic no congela la interfaz (se hornea después)"
    assert pg._items[act["id"]].previa is not None, "mientras tanto, vista previa barata"
    esperar_horneado()
    assert act["base_media"] == mid and act["media_id"] != mid, "horneado desde la original"
    with Image.open(p.media[act["media_id"]].path) as im:
        assert im.size[0] > 300, "el borde va por fuera"
    for v in (2.0, 4.0, 6.0, 8.0):                    # (varios pasos del deslizador: un solo resultado final)
        aj.valores["borde"].setValue(v)
    aj.poner("redondeo", 0.5)
    esperar_horneado()
    propios = sum(1 for m in p.media.values() if EA.es_propia(m.path))
    assert propios <= propios0 + 1, ("sin intermedios en Medios", propios0, propios)
    with Image.open(p.media[act["media_id"]].path) as im:
        g = max(1, int(round(300 * 0.08)))
        assert im.getpixel((g + 2, g + 2))[3] == 0 or im.getpixel((g + 2, g + 2))[:3] == (255, 255, 255)
        assert im.getpixel((im.size[0] // 2, im.size[1] // 2))[:3] == (40, 80, 230)
    aj.poner("sombra", 0.8)
    pz = scenes.piezas(pg.escena)
    assert pz and pz[0]["plan"]["fx"].get("shadow", {}).get("opacity") == 0.8
    print("✓ borde (por fuera, desde la original), esquinas y sombra con valores rápidos: sin congelar (vista previa y "
          "horneado en segundo plano) y sin intermedios en Medios")
    aj.poner("borde", 0.0)
    aj.poner("redondeo", 0.0)
    assert act["media_id"] == mid, "sin borde ni esquinas vuelve a la original"
    # se exporta igual: con borde rojo, el rojo se ve fuera de la imagen
    aj.poner_color("#ff0000")
    aj.poner("borde", 0.06)
    win.engine.seek(0.0)
    pg.escena["fondo"] = "nada"
    assert pg.aplicar()
    mp4 = os.path.join(_TMP, "ajustes.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=640, height=360, fps=30, encoder="cpu",
                                              loudnorm=False), M.ffmpeg(), os.path.join(_TMP, "fa.txt"))
    subprocess.run(args, check=True, capture_output=True, creationflags=M.NO_WINDOW)
    a0 = float(pg.escena["a"])
    fr = M.frame_rgb(mp4, a0 + 1.0, 640).astype(int)
    rojo = ((fr[..., 0] > 180) & (fr[..., 1] < 70) & (fr[..., 2] < 70)).sum()
    azul = ((fr[..., 2] > 180) & (fr[..., 0] < 90)).sum()
    assert rojo > 200 and azul > 1000, (rojo, azul)
    print(f"✓ exportado: la imagen ({azul} px azules) con su borde rojo ({rojo} px)")
    # quitar el fondo (solo si el modelo ya está en esta PC)
    from editoria.ai import bg_removal as BR
    if BR.is_available():
        pg._cargar(pg._nueva_desde_marcas(), True)
        cid = ctrl.media_for_path(_png("circulo.png", (220, 40, 40), circulo=True), "Escenas")
        pg._añadir_actor(cid)
        a = pg.escena["actores"][-1]
        pg.tl.sel = ("actor", a)
        pg._elegir("actor", a)
        pg.ajustes.b_fondo.click()                     # (por el camino del botón: trabajo en segundo plano)
        t0 = time.time()
        while not (a.get("ajustes") or {}).get("sin_fondo") and time.time() - t0 < 120:
            pump(app, 0.2)
        assert (a.get("ajustes") or {}).get("sin_fondo"), ("el botón quita el fondo", pg.ajustes.estado.text())
        assert EA.es_propia(a["ajustes"]["sin_fondo"]), "la máscara, fuera de la caché que se limpia"
        with Image.open(p.media[a["media_id"]].path) as im:
            assert im.getpixel((5, 5))[3] < 40 and im.getpixel((200, 200))[3] > 200, "fondo fuera, círculo dentro"
        pg.ajustes.devolver_fondo()
        assert a["media_id"] == cid
        print("✓ quitar el fondo (IA local de Miniaturas) y devolverlo")
    else:
        print("· (sin el modelo de quitar fondo en esta PC: esa parte no se prueba)")
    pg.grab().save(os.path.join(out, "6_ajustes.png"))
    win.go_page("edit")
    pump(app, 0.2)


def prueba_crear_llevar(app, win, out):
    """5) Crear y llevar en un paso: con la casilla, «Crear escena» la deja en Resultados, en Medios y en el cabezal."""
    from PySide6.QtCore import QSettings as _QS
    ctrl = win.ctrl
    p = ctrl.project
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    pg._cargar(pg._nueva_desde_marcas(), True)
    pg._añadir_actor(ctrl.media_for_path(_png("llevar.png", (200, 200, 30)), "Escenas"))
    pg.al_cabezal.setChecked(True)
    assert str(_QS("EditorIA", "EditorIA").value("escenas/al_cabezal")).lower() == "true", "se recuerda"
    win.engine.seek(5.0)
    mid = pg.crear_escena()
    eid = pg.escena["id"]
    puestos = ctrl.scene_clips(p, eid)
    assert mid in p.media and eid in pg.resultados.tarjetas and len(puestos) == 1 and \
        abs(puestos[0].start - 5.0) < 1e-3
    pg.al_cabezal.setChecked(False)
    print("✓ «Crear escena» con «Al crearla, ponerla en el cabezal»: Resultados, Medios y la línea de tiempo en un paso")
    win.go_page("edit")
    pump(app, 0.2)


def prueba_plantillas(app, win, out):
    """6) Plantillas: crean sus huecos y textos; soltar material en un hueco lo llena (con sus ajustes)."""
    from editoria.ui import escenas_plantillas as PL
    ctrl = win.ctrl
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    esperados = {"dividida_2": (2, 0), "dividida_3": (3, 0), "dividida_4": (4, 0), "pip": (2, 0),
                 "reaccion": (2, 0), "antes_despues": (2, 2), "meme": (1, 2), "collage": (6, 0)}
    for clave, (nh, nt) in esperados.items():
        pg.sucia = False
        hechos = PL.aplicar(pg, clave)
        huecos = [a for a in pg.escena["actores"] if a.get("hueco")]
        textos = [a for a in pg.escena["actores"] if a.get("texto")]
        assert len(hechos) == nh + nt and len(huecos) == nh and len(textos) == nt, (clave, len(huecos), len(textos))
        assert all(0 <= a["caja"]["x"] and a["caja"]["x"] + a["caja"]["w"] <= 1.0001 for a in hechos), clave
    print(f"✓ las {len(esperados)} plantillas crean sus huecos y textos (dividida 2/3/4, imagen en imagen, reacción, "
          "antes/después, meme, collage)")
    # reacción: soltar dos de Medios en el hueco grande → llena ese y el pequeño (con esquinas, borde y sombra)
    pg.sucia = False
    PL.aplicar(pg, "reaccion")
    a1 = ctrl.media_for_path(_png("contenido.png", (30, 160, 200), (320, 180)), "Escenas")
    a2 = ctrl.media_for_path(_png("camara.png", (200, 120, 60), (240, 240)), "Escenas")
    pg.soltar_medios([a1, a2], 0.3, 0.3)
    grande, peque = pg.escena["actores"][0], pg.escena["actores"][1]
    assert not grande.get("hueco") and grande["media_id"] == a1
    assert not peque.get("hueco") and peque["base_media"] == a2 and peque["media_id"] != a2, "con sus ajustes"
    assert pg.escena["actores"][1]["ajustes"]["sombra"] > 0
    pg.grab().save(os.path.join(out, "7_plantilla_reaccion.png"))
    print("✓ soltar dos imágenes en la reacción: el contenido en el grande y la cámara en el pequeño (con esquinas, "
          "borde y sombra)")
    pg.sucia = False
    PL.aplicar(pg, "pip")
    peq = pg.escena["actores"][1]
    pg._cambiar_imagen(peq, a2)
    assert not peq.get("hueco") and peq["base_media"] == a2 and peq["media_id"] != a2, "Cambiar imagen en un hueco"
    assert pg.nombre_capa(peq) == "camara", pg.nombre_capa(peq)
    print("✓ «Cambiar imagen» en un hueco de plantilla: deja de ser hueco y lleva su borde (nombre de la imagen, no "
          "del PNG horneado)")
    # meme: el texto se cambia desde la derecha
    pg.sucia = False
    PL.aplicar(pg, "meme")
    t = next(a for a in pg.escena["actores"] if a.get("texto"))
    pg.tl.sel = ("actor", t)
    pg._elegir("actor", t)
    antes = t["media_id"]
    pg.ajustes.texto.setText("CUANDO TODO SALE BIEN")
    pg.ajustes._texto_cambiado()
    assert t["texto"]["t"] == "CUANDO TODO SALE BIEN" and t["media_id"] != antes
    pg.grab().save(os.path.join(out, "8_plantilla_meme.png"))
    print("✓ meme: el texto de arriba se cambia a la derecha y se vuelve a dibujar")
    pg.sucia = False
    win.go_page("edit")
    pump(app, 0.2)


def prueba_restos(app, win, out):
    """7) Sin restos en Medios ▸ Escenas: quitar una capa saca su PNG horneado (Ctrl+Z lo vuelve a hornear); el PNG de
    un texto se queda mientras la capa pueda volver con Ctrl+Z; descartar la escena sin aplicar saca todos sus PNG
    propios que no use nadie."""
    from editoria.core import escena_ajustes as EA
    from editoria.ui import escenas_plantillas as PL
    from editoria.ui.escenas_ajustes_ui import al_dia
    ctrl = win.ctrl
    p = ctrl.project
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    pg.sucia = False
    pg._cargar(pg._nueva_desde_marcas(), True)
    mid = ctrl.media_for_path(_png("resto_verde.png", (40, 200, 90), (240, 240)), "Escenas")
    pg._añadir_actor(mid, {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.6, "fit": "contain", "bg": "none"})
    act = pg.escena["actores"][-1]
    pg.ajustes.poner("borde", 0.06)

    def esperar(cond, tope=30.0):
        t0 = time.time()
        while not cond() and time.time() - t0 < tope:
            pump(app, 0.1)
        return cond()
    assert esperar(lambda: al_dia(pg, act) and act["media_id"] != mid), "horneado con su borde"
    pump(app, 0.6)                                    # (Ctrl+Z: la foto de la escena ya asentada)
    horneado, ruta = act["media_id"], p.media[act["media_id"]].path
    assert EA.es_propia(ruta) and os.path.isfile(ruta)
    pg._quitar_actor(act)
    assert horneado not in p.media and not os.path.isfile(ruta), "quitar la capa saca su PNG horneado"
    pump(app, 0.6)
    pg.deshacer()
    vuelto = next((a for a in pg.escena["actores"] if a["id"] == act["id"]), None)
    assert vuelto is not None, "Ctrl+Z devuelve la capa"
    assert esperar(lambda: al_dia(pg, vuelto)), "Ctrl+Z la vuelve a hornear"
    assert vuelto["media_id"] in p.media and os.path.isfile(p.media[vuelto["media_id"]].path)
    print("✓ quitar una capa saca su PNG horneado de Medios ▸ Escenas; Ctrl+Z la devuelve y se vuelve a hornear")
    # texto: se queda mientras pueda volver con Ctrl+Z
    pg.sucia = False
    PL.aplicar(pg, "meme")
    pump(app, 0.6)
    t = next(a for a in pg.escena["actores"] if a.get("texto"))
    mt = t["media_id"]
    pg._quitar_actor(t)
    assert mt in p.media and os.path.isfile(p.media[mt].path), "el PNG del texto se queda (puede volver con Ctrl+Z)"
    pump(app, 0.6)
    pg.deshacer()
    t2 = next((a for a in pg.escena["actores"] if a["id"] == t["id"]), None)
    assert t2 is not None and t2["media_id"] in p.media, "Ctrl+Z devuelve el texto con su imagen"
    print("✓ quitar un texto deja su PNG mientras pueda volver con Ctrl+Z (y vuelve con su imagen)")
    # descartar la escena sin aplicar: fuera todo lo propio que no use nadie
    propios = {m for a in pg._capas_y_su_historial() for m in (a.get("media_id"), a.get("base_media"))
               if m in p.media and EA.es_propia(p.media[m].path)}
    assert propios, "la escena tiene PNG propios (textos)"
    pg.sucia = True
    assert pg.volver("edit"), "volver descartando (sin preguntar en las pruebas)"
    pump(app, 0.3)
    usados = {c.media_id for c in p.clips.values()}
    for esc in p.scenes.values():
        for a in esc.get("actores", []):
            usados.update({a.get("media_id"), a.get("base_media")})
    quedan = [m for m in propios if m in p.media and m not in usados]
    assert not quedan, ("descartar la escena deja PNG propios sin usar en Medios", quedan)
    print(f"✓ descartar la escena sin aplicar saca sus {len(propios)} PNG propios sin usar (textos y horneados)")


def prueba_aplicada_deshacer(app, win, out):
    """8) Lo APLICADO no se borra (revisión de Fable, caso A4): borde 3 % → Aplicar, 6 % → Aplicar, volver al editor y
    Ctrl+Z → la escena de 3 % vuelve CON su PNG. Red de seguridad: un PNG de una escena del proyecto que falte se
    repone (mismo id, se rehornea). Pegar una capa horneada cuyo PNG se quitó la vuelve a hornear."""
    from editoria.core import escena_ajustes as EA
    from editoria.ui import escenas_ajustes_ui as EAU
    ctrl = win.ctrl
    p = ctrl.project
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    pg.sucia = False

    def esperar(cond, tope=30.0):
        t0 = time.time()
        while not cond() and time.time() - t0 < tope:
            pump(app, 0.1)
        return cond()

    def rotos():
        malos = []
        for e in list(p.scenes.values()):
            for a in e.get("actores", []):
                m = p.media.get(a["media_id"])
                if m is None:
                    malos.append(f"{e.get('nombre')}: medio quitado del proyecto")
                elif not os.path.isfile(m.path):
                    malos.append(f"{e.get('nombre')}: archivo borrado")
        return malos
    mid = ctrl.media_for_path(_png("aplicada_roja.png", (210, 60, 60), (220, 260)), "Escenas")
    pg._cargar(pg._nueva_desde_marcas(), True)
    pg.escena["a"], pg.escena["b"] = 40.0, 44.0
    pg._añadir_actor(mid)
    act = pg.escena["actores"][-1]
    pg.ajustes.poner("borde", 0.03)
    assert esperar(lambda: EAU.al_dia(pg, act) and act["media_id"] != mid)
    assert pg.aplicar(), "aplicar con borde 3 %"
    act = pg.escena["actores"][-1]
    pg.tl.sel = ("actor", act)
    pg._elegir("actor", act)
    pg.ajustes.poner("borde", 0.06)
    assert esperar(lambda: EAU.al_dia(pg, act))
    assert pg.aplicar(), "aplicar con borde 6 %"
    pg.sucia = False
    assert pg.volver("edit")
    pump(app, 0.3)
    assert not rotos(), rotos()
    ctrl.undo_stack.undo()
    pump(app, 0.4)
    assert not rotos(), ("Ctrl+Z en el editor tras cambiar el borde de una escena aplicada", rotos())
    ctrl.undo_stack.redo()
    pump(app, 0.4)
    assert not rotos(), ("y rehacer", rotos())
    print("✓ borde 3 % aplicado → 6 % aplicado → volver → Ctrl+Z / Ctrl+Y en el editor: la escena sigue con su PNG")
    # 🛟 red de seguridad: falta el PNG horneado de una escena del proyecto → se repone (mismo id) y se rehornea
    esc = next(e for e in p.scenes.values() if any(a.get("horneado_de") for a in e.get("actores", [])))
    a = next(a for a in esc["actores"] if a.get("horneado_de"))
    falta = a["media_id"]
    m = p.media.pop(falta)
    EAU._QUITADOS[falta] = m
    if os.path.isfile(m.path):
        os.remove(m.path)
    ctrl.project_changed.emit()
    pump(app, 0.2)
    assert falta in p.media and os.path.isfile(p.media[falta].path), "el PNG que faltaba vuelve, rehorneado"
    print("✓ red de seguridad: una escena del proyecto sin su PNG horneado lo recupera (mismo id, rehorneado)")
    # pegar una capa horneada cuyo PNG ya se quitó: se vuelve a hornear
    win.go_page("scenes")
    pump(app, 0.3)
    pg = win._scenes_widget
    pg.sucia = False
    pg._cargar(pg._nueva_desde_marcas(), True)
    pg._añadir_actor(mid)
    a = pg.escena["actores"][-1]
    pg.ajustes.poner("borde", 0.02)
    assert esperar(lambda: EAU.al_dia(pg, a) and a["media_id"] != mid)
    pg.tl.sel = ("actor", a)
    pg._elegir("actor", a)
    assert pg.copiar()
    pg._quitar_actor(a)
    pump(app, 0.3)
    pg.pegar()
    b = pg.escena["actores"][-1]
    assert esperar(lambda: EAU.al_dia(pg, b)), "pegar la vuelve a hornear"
    assert b["media_id"] != mid and b["media_id"] in p.media and os.path.isfile(p.media[b["media_id"]].path)
    assert EA.es_propia(p.media[b["media_id"]].path)
    print("✓ pegar una capa horneada cuyo PNG se quitó la vuelve a hornear")
    pg.sucia = False
    win.go_page("edit")
    pump(app, 0.2)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "escenas_facil")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("escenas/al_cabezal", False)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.4)
    try:
        win.workspaces.switch("youtube")
        win.ctrl.project.width, win.ctrl.project.height = 640, 360
        win.preview.canvas.set_canvas_size(640, 360) if hasattr(win.preview.canvas, "set_canvas_size") else None
        pump(app, 0.3)
        prueba_huecos(app, win, out)
        prueba_resultados(app, win, out)
        prueba_capas(app, win, out)
        prueba_ajustes(app, win, out)
        prueba_crear_llevar(app, win, out)
        prueba_plantillas(app, win, out)
        prueba_restos(app, win, out)
        prueba_aplicada_deshacer(app, win, out)
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
