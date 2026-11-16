"""
Prueba de 🎞 «Animar imagen» (core/image_anim.py, controller.add_animated_images / set_image_anim, la ventana
ui/image_anim_dialog.py y el ⚡ acomodar por palabras clave con «animar los recortes»). Sin ventanas, sin sonido.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_animar_imagen.py [carpeta_temporal]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = sys.argv[1] if len(sys.argv) > 1 else None
if _BASE:
    os.makedirs(_BASE, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="animar_", dir=_BASE)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "datos")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from editoria.core import image_anim as A  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core import transform  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def png(nombre: str, alfa: bool) -> str:
    im = QImage(200, 300, QImage.Format_ARGB32 if alfa else QImage.Format_RGB32)
    im.fill(Qt.transparent if alfa else Qt.darkGreen)
    for y in range(60, 240):                       # un «personaje»: un rectángulo naranja
        for x in range(60, 140):
            im.setPixelColor(x, y, Qt.darkYellow)
    ruta = os.path.join(_TMP, nombre)
    assert im.save(ruta)
    return ruta


def prueba_plantillas():
    caja = dict(A.CAJA_PERSONAJE)
    for k, _n, _d in A.ANIMS:
        p = A.plan(k, caja, 3.0, 0)
        kf = p["layout_kf"]
        assert kf == sorted(kf, key=lambda x: x["t"]), k
        assert all(0.0 <= x["t"] <= 3.0 for x in kf), k
        assert len({x["t"] for x in kf}) == len(kf), f"{k}: dos claves en el mismo instante"
    # disparar: retrocede hacia la ESPALDA (mira a la derecha → se mueve a la izquierda) y vuelve
    d = A.plan("disparo", caja, 2.0, 1)["layout_kf"]
    xs = [k["x"] for k in d]
    assert min(xs) < caja["x"] and max(xs) <= caja["x"] + 1e-6 and abs(d[-1]["x"] - caja["x"]) < 1e-6
    d2 = A.plan("disparo", caja, 2.0, -1)["layout_kf"]
    assert max(k["x"] for k in d2) > caja["x"], "mirando a la izquierda retrocede a la derecha"
    assert len(A.plan("disparo", caja, 20.0, 1)["layout_kf"]) <= 1 + 3 * A.MAX_SHOTS, "ráfaga limitada"
    # morir: baja, se desvanece y tiembla al recibir el impacto
    m = A.plan("muere", caja, 3.0, 1)
    assert m["layout_kf"][-1]["y"] > caja["y"] + 0.2 and m["op_kf"][-1]["v"] == 0.0 and m["fx"]["shake"] > 0
    # entrar: empieza fuera de la pantalla y llega a su sitio · salir: al revés · cruzar: de fuera a fuera
    e = A.plan("entra", caja, 3.0, 1)["layout_kf"]
    assert e[0]["x"] + e[0]["w"] <= 0.0 + 1e-6 and abs(e[-1]["x"] - caja["x"]) < 1e-6
    s = A.plan("sale", caja, 3.0, 1)["layout_kf"]
    assert abs(s[0]["x"] - caja["x"]) < 1e-6 and s[-1]["x"] >= 1.0 - 1e-6 and s[-1]["t"] == 3.0
    c = A.plan("cruza", caja, 3.0, -1)["layout_kf"]
    assert c[0]["x"] >= 1.0 - 1e-6 and c[-1]["x"] + c[-1]["w"] <= 1e-6
    a = A.plan("acerca", caja, 3.0, 1)["layout_kf"]
    assert a[-1]["w"] > caja["w"] * 1.1
    # lado automático: a la izquierda mira a la derecha (hacia el centro) y al revés
    assert A.lado_de({"x": 0.05, "w": 0.3}) == 1 and A.lado_de({"x": 0.6, "w": 0.3}) == -1
    # según lo que dices
    for frase, k in (("y el jefe le dispara al soldado", "disparo"), ("ahí muere Johnson tras el disparo", "muere"),
                     ("el Master Chief llega al anillo", "entra"), ("se va corriendo", "sale"),
                     ("le pega un golpe tremendo", "golpe"), ("salta por encima", "salta"), ("nada que ver", None)):
        assert A.elegir(frase) == k, (frase, A.elegir(frase))
    assert A.tiene_transparencia(png("con_alfa.png", True)) and not A.tiene_transparencia(png("sin_alfa.png", False))
    print("✓ plantillas (disparar, morir, golpe, saltar, entrar, salir, cruzar, acercarse, temblar), lado y palabras")


def esperar(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def proyecto(app):
    ctrl = ProjectController()
    ff = media_tools.ffmpeg()
    fondo = os.path.join(_TMP, "fondo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=f=220:d=12", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", fondo], check=True, creationflags=media_tools.NO_WINDOW)
    (fid,) = ctrl.import_now([fondo])
    esperar(app, ctrl)
    # «la narración»: lo que se dice en cada momento (dispara en el 2, muere en el 6, llega en el 9)
    ctrl.project.transcripts[fid] = {"words": [[1.8, 2.1, "el", 1], [2.1, 2.5, "soldado", 1],
                                               [2.5, 2.9, "dispara", 1], [6.0, 6.4, "y", 1], [6.4, 6.9, "muere", 1],
                                               [9.0, 9.3, "luego", 1], [9.3, 9.7, "llega", 1]]}
    v1 = next(t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO and t.name == "V1")
    ctrl.add_media([fid], v1.id, 0.0)
    img = png("soldado.png", True)
    (mid,) = ctrl.import_now([img])
    esperar(app, ctrl)
    return ctrl, mid, img


def prueba_controlador(app):
    ctrl, mid, _img = proyecto(app)
    p = ctrl.project
    caja = {"x": 0.05, "y": 0.2, "w": 0.35, "h": 0.6, "fit": "contain", "bg": "none"}
    ids = ctrl.add_animated_images(mid, [2.0, 6.0, 9.0], 2.5, caja, "auto")
    assert ids and len(ids) == 3, ids
    claves = [(p.clips[i].fx or {}).get("anim", {}).get("key") for i in sorted(ids, key=lambda i: p.clips[i].start)]
    assert claves == ["disparo", "muere", "entra"], claves
    c0 = p.clips[ids[0]]
    assert c0.layout["x"] == caja["x"] and c0.layout_kf and abs(c0.duration - 2.5) < 1e-6
    assert all(p.track(p.clips[i].track_id).kind == TRACK_VIDEO for i in ids)
    vt = [t.id for t in p.tracks if t.kind == TRACK_VIDEO]
    assert all(vt.index(p.clips[i].track_id) < vt.index(next(t.id for t in p.tracks if t.name == "V1"))
               for i in ids), "encima del video"
    # en pantalla durante la reproducción: la caja se mueve (disparo) como dicen las claves
    box = transform.layout_at(c0, 0.12, is_image=True)
    assert box["x"] < caja["x"], box
    # un paso de Ctrl+Z quita las tres
    ctrl.undo_stack.undo()
    assert not any(i in p.clips for i in ids)
    ctrl.undo_stack.redo()
    assert all(i in p.clips for i in ids)
    # cambiar la animación de una ya puesta (y «quieta» la deja sin claves)
    assert ctrl.set_image_anim([ids[0]], "salta") == 1
    assert (p.clips[ids[0]].fx or {})["anim"]["key"] == "salta"
    assert ctrl.set_image_anim([ids[1]], "ninguna") == 1
    c1 = p.clips[ids[1]]
    assert not c1.layout_kf and not c1.op_kf and "shake" not in (c1.fx or {}) and "anim" not in (c1.fx or {})
    print("✓ ponerla en varios momentos según lo que dices (dispara / muere / llega), encima, un solo Ctrl+Z; cambiarla")
    return ctrl


def prueba_convivencia(app):
    """🎞 Animación y 🖼 Estilo de imagen no se pisan a medias; pantalla completa no se encoge; dividir y «ajustar a la
    frase» respetan la animación."""
    ctrl, mid, _img = proyecto(app)
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.name == "V1")
    v2 = next(t for t in p.tracks if t.name == "V2")             # (encima del video: así hay algo que desenfocar)
    (cid,) = ctrl.add_image_overlay([mid], v2.id, 2.0) or [None]
    c = p.clips[cid]
    assert "ovl" in (c.fx or {})
    def desenfocado():
        return any(((o.fx or {}).get("ovl_bg") or {}).get("ov") == cid for o in p.clips.values())
    assert desenfocado(), "el estilo «encima» desenfoca el video de debajo"
    assert ctrl.set_image_anim([cid], "disparo") == 1
    assert "ovl" not in c.fx and not desenfocado(), "animar quita el estilo y el desenfoque de debajo"
    ctrl.set_image_anim([cid], "tiembla")
    ctrl.set_image_style([cid], "corner")
    assert "anim" not in c.fx and "shake" not in c.fx, "el estilo quita la animación y su temblor"
    # «ajustar a la frase» con animación: la rehace a la duración nueva
    ctrl.set_image_anim([cid], "sale")
    ctrl.set_image_style([cid], "phrase")
    assert c.fx.get("anim", {}).get("key") == "sale" and abs(c.layout_kf[-1]["t"] - c.duration) < 1e-3
    # pantalla completa (sin caja): animarla no la encoge
    img2 = png("captura.png", False)
    (m2,) = ctrl.import_now([img2])
    esperar(app, ctrl)
    full = ctrl.add_media([m2], v1.id, 10.0)
    cf = p.clips[full[0]]
    cf.layout = None
    ctrl.set_image_anim([cf.id], "acerca")
    assert cf.layout["w"] == 1.0 and cf.layout["h"] == 1.0, cf.layout
    # dividir una imagen que «muere»: la opacidad de la derecha sigue desde donde iba (no se repite el desvanecido)
    ctrl.set_image_anim([cid], "muere")
    d0 = c.duration
    op_fin = c.op_kf[-1]["t"]
    t_corte = c.start + d0 * 0.5
    ctrl.split(t_corte, [cid])
    der = next(o for o in p.clips.values() if o.media_id == mid and abs(o.start - t_corte) < 1e-3)
    assert der.op_kf and abs(der.op_kf[-1]["t"] - (op_fin - d0 * 0.5)) < 1e-3, der.op_kf
    print("✓ animación y estilo de imagen se sustituyen bien; pantalla completa no se encoge; dividir y ajustar a la frase")


def prueba_exportar(ctrl):
    """Lo que se ve es lo que se exporta: FFmpeg acepta las claves de una ráfaga de disparos y de una caída."""
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    out = os.path.join(_TMP, "animado.mp4")
    opts = ExportOptions(path=out, width=640, height=360, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
    args, _total = build_command(ctrl.project, opts, media_tools.ffmpeg(), os.path.join(_TMP, "filtro.txt"))
    r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
    if r.returncode != 0:
        print(r.stderr.decode(errors="replace")[-2500:])
    assert r.returncode == 0 and os.path.getsize(out) > 10000
    filtro = open(os.path.join(_TMP, "filtro.txt"), encoding="utf-8").read()
    assert "if(lt(" in filtro, "las claves de movimiento no llegaron al filtro de FFmpeg"
    # la imagen que «entra» (en el 9) está fuera al principio y en su sitio después: el borde izquierdo cambia
    import numpy as np
    def fotograma(t):
        raw = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", out,
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "160x90", "-"],
                             capture_output=True, creationflags=media_tools.NO_WINDOW).stdout
        return np.frombuffer(raw, np.uint8).reshape(90, 160).astype(np.int16)
    antes, despues = fotograma(9.03), fotograma(10.2)
    assert np.abs(antes[:, :60] - despues[:, :60]).mean() > 3, "la imagen que entra no se movió en el video"
    print("✓ se exporta con FFmpeg y la imagen se mueve en el video exportado")


class _Ventana(QWidget):
    """Lo que usa la ventana «Animar imagen» de la ventana principal."""
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.engine = type("E", (), {"time": 3.0})()
        self.timeline = type("T", (), {"set_selection": lambda *_a: None})()


def prueba_ventana(app):
    from editoria.ui.image_anim_dialog import AUTO, ImageAnimDialog
    ctrl, mid, _img = proyecto(app)
    win = _Ventana(ctrl)
    d = ImageAnimDialog(win, mid)
    assert d.media.currentData() == mid and d.btn_poner.isEnabled()
    d.caja.setPos(d.W * 0.6, d.H * 0.1)                 # arrastrarla a la derecha
    caja = d.caja_elegida()
    assert caja["x"] > 0.55
    for _ in range(10):
        d._tick()
        app.processEvents()
    assert d.anim_item.isVisible()
    d.anims.setCurrentRow(next(i for i in range(d.anims.count()) if d.anims.item(i).data(Qt.UserRole) == "cruza"))
    d.dur.setValue(4.0)
    assert d.momentos_elegidos() == [3.0]                 # en el cabezal
    d._poner()
    assert d.creados and len(d.creados) == 1
    c = ctrl.project.clips[d.creados[0]]
    assert abs(c.start - 3.0) < 1e-6 and abs(c.duration - 4.0) < 1e-6 and c.fx["anim"]["key"] == "cruza"
    assert c.fx["anim"]["side"] == -1, "a la derecha mira a la izquierda: cruza hacia la izquierda"
    d2 = ImageAnimDialog(win, mid)
    assert d2.anims.item(0).data(Qt.UserRole) == AUTO
    assert not d2.en_palabra.isEnabled(), "sin palabras clave: la opción no se puede elegir"
    d2.reject()
    print("✓ ventana: arrastrar el recuadro, vista previa animada, duración, poner en el cabezal")


def prueba_palabras_clave(app):
    """⚡ Acomodar por palabras clave con «🎞 animar los recortes»: el PNG con transparencia se anima según lo que dices;
    la foto sin transparencia se queda como siempre."""
    from editoria.core.keyword_arrange import Item
    ctrl, _mid, img = proyecto(app)
    foto = png("foto.png", False)
    items = [Item("k1", 2.0, 2.0, img, 0.0, "image"), Item("k2", 6.0, 2.0, foto, 0.0, "image")]
    ids = ctrl.arrange_keywords(items, animar=True)
    assert ids and len(ids) == 2, ids
    p = ctrl.project
    por_t = {round(p.clips[i].start): p.clips[i] for i in ids}
    assert (por_t[2].fx or {}).get("anim", {}).get("key") == "disparo", por_t[2].fx
    assert por_t[2].layout["w"] < 0.6, "el recorte va en tamaño de personaje"
    assert "anim" not in (por_t[6].fx or {}), "la foto sin transparencia no se anima"
    ids2 = ctrl.arrange_keywords(items, animar=False)
    assert not any("anim" in (p.clips[i].fx or {}) for i in ids2), "sin la opción, como siempre"
    print("✓ ⚡ palabras clave: los recortes se animan según lo que dices; las fotos y sin la opción, como siempre")


def main():
    app = QApplication.instance() or QApplication([])
    prueba_plantillas()
    ctrl = prueba_controlador(app)
    prueba_exportar(ctrl)
    prueba_convivencia(app)
    prueba_ventana(app)
    prueba_palabras_clave(app)
    assert TRACK_AUDIO
    print("TODO OK")


if __name__ == "__main__":
    main()
