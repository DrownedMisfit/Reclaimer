"""
Prueba de 🎭 PNGTuber: la boca abre con la voz y cierra en el silencio, parpadea (siempre igual), el video del avatar
sale con la duración correcta y la boca abierta se ve distinta de la cerrada; la ventana lo pone encima de todo con
la 🟩 Pantalla verde y sin sonido, al exportar el verde no se ve, un Ctrl+Z lo quita; Mis PNGTubers guarda y carga.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles ni sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_pngtuber.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

VOZ = [(1.0, 3.0), (5.0, 7.0)]      # tramos con voz (s); el resto, silencio
DUR = 10.0


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def caras(out: str) -> dict:
    """PNG con alfa: boca cerrada / abierta / ojos cerrados (dibujados a 4× y reducidos: borde suave)."""
    S = 4

    def cara(boca_abierta: bool, ojos_cerrados: bool) -> Image.Image:
        im = Image.new("RGBA", (200 * S, 240 * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([10 * S, 10 * S, 190 * S, 230 * S], fill=(250, 210, 180, 255), outline=(25, 25, 25, 255),
                  width=4 * S)
        for x in (65, 135):
            if ojos_cerrados:
                d.line([(x - 15) * S, 95 * S, (x + 15) * S, 95 * S], fill=(25, 25, 25, 255), width=4 * S)
            else:
                d.ellipse([(x - 12) * S, 82 * S, (x + 12) * S, 108 * S], fill=(25, 25, 25, 255))
        if boca_abierta:
            d.ellipse([60 * S, 150 * S, 140 * S, 205 * S], fill=(140, 20, 30, 255))
        else:
            d.line([65 * S, 175 * S, 135 * S, 175 * S], fill=(25, 25, 25, 255), width=4 * S)
        return im.resize((200, 240), Image.LANCZOS)

    rutas = {}
    for k, (b, o) in {"cerrada": (False, False), "abierta": (True, False), "ojos": (False, True)}.items():
        rutas[k] = os.path.join(out, f"avatar_{k}.png")
        cara(b, o).save(rutas[k])
    return rutas


def audio(out: str) -> str:
    """10 s: voz (tono con sílabas) en VOZ y silencio (con un poco de ruido) en el resto."""
    sr = 48000
    t = np.arange(int(DUR * sr)) / sr
    x = np.random.default_rng(1).normal(0, 0.002, len(t))
    for a, b in VOZ:
        m = (t >= a) & (t < b)
        silabas = 0.55 + 0.45 * np.abs(np.sin(2 * np.pi * 2.5 * t[m]))
        x[m] += 0.5 * silabas * np.sin(2 * np.pi * 220 * t[m])
    ruta = os.path.join(out, "voz.wav")
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype(np.int16).tobytes())
    return ruta


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    from editoria.core import chroma as CK
    from editoria.core import media as M
    from editoria.core import pngtuber as PT

    imgs = caras(out)
    wav = audio(out)
    fps = 30

    # 1) Estados: boca con la voz, cerrada en el silencio, sin temblores; parpadeo reproducible
    pk = M.waveform_peaks(wav)
    ests = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, sensibilidad=0.5, fps=fps, parpadeo=PT.PARPADEO["normal"],
                      rebote_px=8)
    assert len(ests) == int(DUR * fps), len(ests)
    boca = np.array([e.boca_abierta for e in ests])
    for a, b in VOZ:
        dentro = boca[int((a + 0.15) * fps):int((b - 0.15) * fps)]
        assert dentro.mean() > 0.9, ("abre al hablar", a, b, dentro.mean())
    silencio = np.ones(len(ests), bool)
    for a, b in VOZ:
        silencio[int((a - 0.2) * fps):int((b + 0.2) * fps)] = False
    assert not boca[silencio].any(), "en el silencio la boca está cerrada"
    cambios = np.flatnonzero(np.diff(boca.astype(int))) + 1
    tramos = np.diff(np.concatenate([[0], cambios, [len(boca)]]))
    assert tramos.min() >= int(np.ceil(PT.MIN_ESTADO * fps)), ("sin temblores", tramos)
    print(f"✓ la boca abre en la voz ({boca[~silencio].mean():.0%} del tramo) y está cerrada en el silencio; "
          f"cada estado dura ≥ {tramos.min()} fotogramas")
    ojos = np.array([e.ojos_cerrados for e in ests])
    assert ojos.any(), "parpadea"
    parp = np.flatnonzero(np.diff(np.concatenate([[0], ojos.astype(int)])) == 1)
    assert ojos.mean() < 0.15
    otra = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, sensibilidad=0.5, fps=fps, parpadeo=PT.PARPADEO["normal"],
                      rebote_px=8)
    assert otra == ests, "con la misma semilla sale igual"
    nunca = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, fps=fps, parpadeo=None)
    assert not any(e.ojos_cerrados for e in nunca)
    reb = np.array([e.rebote_px for e in ests])
    quieto = np.r_[int(3.6 * fps):int(4.6 * fps), int(8.0 * fps):len(reb)]
    assert reb[boca].max() > 4 and reb[quieto].max() < 0.5, ("rebota al hablar y baja callado", reb[quieto].max())
    sorda = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, sensibilidad=0.0, fps=fps)
    sensible = PT.estados(pk, M.PEAK_RATE, 0.0, DUR, sensibilidad=1.0, fps=fps)
    assert sum(e.boca_abierta for e in sorda) <= sum(e.boca_abierta for e in sensible)
    print(f"✓ parpadea {len(parp)} veces en {DUR:.0f} s (siempre igual con la misma semilla; «nunca» no parpadea); "
          f"rebota hasta {reb.max():.1f} px al hablar")

    # 2) Video del avatar
    modelo = {"nombre": "Prueba", "imagenes": dict(imgs)}
    assert PT.fondo_para(modelo) == PT.VERDE
    mp4 = os.path.join(out, "avatar.mp4")
    prog = []
    res = PT.renderizar(modelo, ests, mp4, 240, fps, progress=lambda f, _t: prog.append(f))
    assert os.path.isfile(mp4) and prog and prog[-1] == 1.0
    info = M.probe(mp4)
    assert abs(info["duration"] - DUR) < 0.06, info["duration"]
    assert not info["has_audio"]
    W = res["ancho"]
    i_ab = next(i for i in range(int(1.5 * fps), len(ests)) if ests[i].boca_abierta and not ests[i].ojos_cerrados)
    i_ce = next(i for i in range(int(8.0 * fps), len(ests)) if not ests[i].boca_abierta and not ests[i].ojos_cerrados)
    f_ab = M.frame_rgb(mp4, (i_ab + 0.5) / fps, W).astype(int)
    f_ce = M.frame_rgb(mp4, (i_ce + 0.5) / fps, W).astype(int)
    H = f_ab.shape[0]
    assert abs(f_ce[3, 3] - np.array(CK._rgb(PT.VERDE))).max() < 12, ("fondo verde", f_ce[3, 3])
    dif = np.abs(f_ab - f_ce).mean()
    boca_zona = (slice(int(H * 0.62), int(H * 0.85)), slice(int(W * 0.3), int(W * 0.7)))
    dif_boca = np.abs(f_ab[boca_zona] - f_ce[boca_zona]).mean()
    assert dif_boca > 20, dif_boca
    print(f"✓ video del avatar: {res['ancho']}×{res['alto']}, {info['duration']:.2f} s, sin sonido, fondo verde; "
          f"boca abierta ≠ cerrada (diferencia {dif_boca:.0f} en la boca, {dif:.1f} en total)")
    i_oj = int(np.flatnonzero(ojos & ~boca)[0]) if (ojos & ~boca).any() else None
    if i_oj is not None:
        f_oj = M.frame_rgb(mp4, (i_oj + 0.5) / fps, W).astype(int)
        ojos_zona = (slice(int(H * 0.3), int(H * 0.5)), slice(int(W * 0.2), int(W * 0.8)))
        assert np.abs(f_oj[ojos_zona] - f_ce[ojos_zona]).mean() > 5
        print("✓ en el parpadeo se ve la imagen de ojos cerrados")

    # 3) Mis PNGTubers
    ruta = PT.guardar(dict(modelo, ajustes={"sensibilidad": 0.7, "posicion": "abajo_izquierda"}))
    assert os.path.dirname(ruta) == PT.carpeta_modelos() and ruta.endswith("Prueba.json")
    lst = PT.listar()
    assert [m["nombre"] for m in lst] == ["Prueba"]
    m2 = PT.cargar("Prueba")
    assert m2["imagenes"]["abierta"] == os.path.abspath(imgs["abierta"])
    assert m2["ajustes"]["sensibilidad"] == 0.7 and m2["ajustes"]["parpadeo"] == "normal"
    assert PT._archivo("../../con").startswith(PT.carpeta_modelos())
    print("✓ Mis PNGTubers: guardar, listar y cargar (imágenes y ajustes)")

    # 4) La ventana: lo pone en la línea de tiempo con croma, sin sonido; exportado sin verde; Ctrl+Z
    app = QApplication(sys.argv)
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui import pngtuber_dialog as PD
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 640, 360
        rojo = os.path.join(out, "fondo_rojo.mp4")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=red:s=640x360:d={DUR}", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", rojo], check=True, creationflags=M.NO_WINDOW)
        rid, aid = ctrl.import_now([rojo, wav])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
        ctrl.add_media([rid], v1.id, 0.0)
        voz = ctrl.add_media([aid], a1.id, 0.5)[0]
        ctrl.ensure_peaks(aid, wait=True)
        d = PD.abrir(win, voz)
        assert d.isVisible() and not d.isModal()
        assert d.audio.currentData() == voz, "elige el audio pedido"
        assert d.modelos.currentText() == "🎭 Prueba" and d.btn_crear.isEnabled(), "abre con el avatar guardado"
        assert d.sens.value() == 70, "con sus ajustes"
        d.modelos.setCurrentIndex(0)                       # ＋ Nuevo avatar
        assert not d.btn_crear.isEnabled(), "sin imágenes no se puede crear"
        for k, r in imgs.items():
            d.set_imagen(k, r)
        d.nombre.setText("Mi avatar")
        d.sens.setValue(50)
        d.posicion.setCurrentIndex(d.posicion.findData("abajo_derecha"))
        d.tamano.setValue(40)
        pump(app, 0.4)
        assert d._ests and any(e.boca_abierta for e in d._ests), "la vista previa sabe cuándo abre la boca"
        assert d.btn_crear.isEnabled()
        assert d.guardar_modelo() and d.modelos.findText("🎭 Mi avatar") >= 0
        assert [m["nombre"] for m in PT.listar()] == ["Mi avatar", "Prueba"]
        n_antes = len(p.clips)
        job = d.crear()
        assert job is not None
        t0 = time.time()
        while d.job is not None and time.time() - t0 < 120:
            pump(app, 0.1)
        pump(app, 0.2)
        assert d.creado and d.creado in p.clips, d.estado.text()
        c = p.clips[d.creado]
        vt = [t for t in p.tracks if t.kind == TRACK_VIDEO]
        assert c.track_id == vt[0].id, "en la pista de video de más arriba"
        assert abs(c.start - 0.5) < 1e-6 and abs(c.duration - DUR) < 0.06, (c.start, c.duration)
        ch = CK.of(c.fx)
        assert ch and ch["color"] == PT.VERDE and ch["similarity"] == PT.CHROMA["similarity"], c.fx
        assert c.volume == 0.0 and not p.media_of(c).has_audio
        assert c.layout and c.layout["x"] > 0.5 and abs(c.layout["y"] + c.layout["h"] - 1.0) < 1e-3, c.layout
        assert abs(c.layout["h"] - PT.alto_en_px(0.40, 360) / 360) < 1e-3
        assert len(p.clips) == n_antes + 1
        print(f"✓ la ventana lo crea en segundo plano y lo pone encima de todo en {c.start:.1f} s, "
              f"{c.duration:.2f} s, con 🟩 croma ({ch['similarity']}/{ch['blend']}), sin sonido, "
              f"abajo a la derecha ({c.layout['w']:.2f}×{c.layout['h']:.2f})")

        exp = os.path.join(out, "exportado.mp4")
        args, _t = build_command(p, ExportOptions(path=exp, width=640, height=360, fps=30, encoder="cpu",
                                                  loudnorm=False), M.ffmpeg(), os.path.join(out, "f.txt"))
        subprocess.run(args, check=True, capture_output=True, creationflags=M.NO_WINDOW)
        lay = c.layout
        x0, y0 = int(lay["x"] * 640), int(lay["y"] * 360)
        w0, h0 = int(lay["w"] * 640), int(lay["h"] * 360)
        fr = M.frame_rgb(exp, 2.0, 640).astype(int)
        caja = fr[y0:y0 + h0, x0:x0 + w0]
        verde = (caja[..., 1] > 120) & (caja[..., 0] < 80) & (caja[..., 2] < 110)
        assert verde.mean() < 0.002, ("no queda verde", verde.mean())
        esquina = fr[y0 + 3, x0 + 3]
        assert esquina[0] > 180 and esquina[1] < 80, ("se ve lo de debajo", esquina)
        piel = fr[y0 + int(h0 * 0.25), x0 + w0 // 2 - int(w0 * 0.2)]
        assert piel[0] > 200 and piel[1] > 160 and piel[2] > 120, ("se ve la cara", piel)
        print(f"✓ exportado: la cara se ve {tuple(int(v) for v in piel)}, donde el PNG es transparente se ve el "
              f"fondo {tuple(int(v) for v in esquina)} y no queda verde ({verde.mean():.2%})")

        ctrl.undo_stack.undo()
        assert d.creado not in p.clips and len(p.clips) == n_antes, "un Ctrl+Z lo quita"
        print("✓ un Ctrl+Z quita el avatar de la línea de tiempo")
        d.close()
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
