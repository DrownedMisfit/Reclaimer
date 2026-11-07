"""
Prueba de la vista previa de «✂ Eliminar silencio» en la línea de tiempo (estilo Resolve): el tramo que se quita
se oscurece dentro de los clips de las pistas que se cortan, con bordes finos; las demás pistas no se rellenan.
Sin ventanas: se renderiza el widget a imagen con widget.grab() y se leen píxeles.
Ejecutar:  .venv/Scripts/python.exe tests/test_silence_preview.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QScrollBar  # noqa: E402

from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem, Project, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.ui.timeline import TimelineWidget  # noqa: E402


def lum(c):
    return (c.red() + c.green() + c.blue()) / 3.0


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)

    ctrl = ProjectController()
    p = ctrl.project
    p.media["aud"] = MediaItem(id="aud", path=os.path.join(out, "no_existe.wav"), kind=KIND_AUDIO, name="voz.wav",
                               duration=10.0, probed=True)
    p.media["vid"] = MediaItem(id="vid", path=os.path.join(out, "no_existe.mp4"), kind=KIND_VIDEO, name="clip.mp4",
                               duration=10.0, width=320, height=180, fps=25.0, probed=True)
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    p.clips["ca"] = Clip(id="ca", media_id="aud", track_id=a1.id, start=0.0, source_in=0.0, duration=10.0)
    p.clips["cv"] = Clip(id="cv", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=10.0)

    tl = TimelineWidget(ctrl, QScrollBar())
    tl.resize(900, 420)
    tl.fit()
    tl.pps = 60.0                      # 10 s = 600 px: cada 0,1 s = 6 px
    tl.scroll = 0.0
    tl._ty_cache = None
    tl.update()

    ia = next(i for i, t in enumerate(p.tracks) if t.id == a1.id)
    iv = next(i for i, t in enumerate(p.tracks) if t.id == v1.id)

    def grab():
        return tl.grab().toImage()

    def px(img, t, i, dy=6):
        x = int(round(tl.x_for(t)))
        y = int(tl.track_y(i) + dy)
        return img.pixelColor(x, y)

    # Línea de base: sin vista previa
    tl.set_preview_regions([])
    base = grab()
    shot0 = os.path.join(out, "sin_vista_previa.png")
    base.save(shot0)

    # 1) Pistas con tracks: solo la de audio se oscurece dentro del tramo
    tl.set_preview_regions([(2.0, 4.0)], tracks=[a1.id])
    img = grab()
    img.save(os.path.join(out, "con_tramo_audio.png"))
    inside_a, base_a = px(img, 3.0, ia), px(base, 3.0, ia)
    assert lum(inside_a) < lum(base_a) - 40, (inside_a, base_a)
    outside_a = px(img, 7.0, ia)
    assert outside_a == px(base, 7.0, ia), (outside_a, px(base, 7.0, ia))
    print("✓ tramo en la pista de audio: oscurecido dentro, igual fuera del tramo")

    # 2) Pista de video (no cortada): dentro del tramo, igual que sin vista previa
    inside_v = px(img, 3.0, iv)
    assert inside_v == px(base, 3.0, iv), (inside_v, px(base, 3.0, iv))
    print("✓ pista de video (no se corta): dentro del tramo sin oscurecer")

    # 3) Borde del tramo: línea clara en la pista cortada (y no en la de video)
    xb = int(round(tl.x_for(2.0)))
    bright = max(lum(img.pixelColor(x, int(tl.track_y(ia) + 20))) for x in (xb - 1, xb, xb + 1))
    assert bright > 120, bright
    xb_v = max(lum(img.pixelColor(x, int(tl.track_y(iv) + 20))) for x in (xb - 1, xb, xb + 1))
    assert abs(xb_v - lum(base.pixelColor(xb, int(tl.track_y(iv) + 20)))) < 30, xb_v
    print("✓ borde del tramo con línea clara en la pista cortada")

    # 4) Marca fina arriba, en la regla, para las pistas que no se cortan
    top_new = img.pixelColor(int(round(tl.x_for(3.0))), 0)
    top_base = base.pixelColor(int(round(tl.x_for(3.0))), 0)
    assert top_new != top_base and lum(top_new) > lum(top_base) + 20, (top_new, top_base)
    print("✓ resto de pistas: solo una marca fina arriba de la regla")

    # 5) Un tramo de menos de 1 px se dibuja (al menos 1 px)
    tl.set_preview_regions([(9.9990, 10.0001)], tracks=[a1.id])
    img = grab()
    xs = int(round(tl.x_for(9.9995)))
    yy = int(tl.track_y(ia) + 6)
    assert any(img.pixelColor(x, yy) != base.pixelColor(x, yy) for x in (xs - 1, xs, xs + 1)), "tramo diminuto invisible"
    print("✓ tramo de menos de 1 px: se dibuja")

    # 6) Voz: en rojo solo en la banda de la pista cortada
    tl.set_preview_regions([(2.0, 4.0)], voice=[(6.0, 7.0)], tracks=[a1.id])
    img = grab()
    c = px(img, 6.5, ia)
    assert c.red() > c.green() + 50 and c.red() > c.blue() + 50, c
    cv = px(img, 6.5, iv)
    assert cv == px(base, 6.5, iv), cv
    print("✓ se cortaría voz: rojo solo en la banda de la pista de audio")

    # 7) Llamada antigua (sin tracks): oscurece todo el alto, también en video
    tl.set_preview_regions([(2.0, 4.0)])
    img = grab()
    assert lum(px(img, 3.0, iv)) < lum(px(base, 3.0, iv)) - 40, "sin tracks debe oscurecer el video"
    assert lum(px(img, 3.0, ia)) < lum(px(base, 3.0, ia)) - 40, "sin tracks debe oscurecer el audio"
    print("✓ llamada sin tracks: oscurece todo el alto")

    # 8) Vacío: vuelve a ser idéntico a la captura inicial
    tl.set_preview_regions([])
    img = grab()
    assert img == base, "con set_preview_regions([]) no coincide con la captura inicial"
    print("✓ set_preview_regions([]): vuelve a la captura inicial")

    # 9) Tramo fuera de la vista: no falla
    tl.set_preview_regions([(5000.0, 5002.0)], tracks=[a1.id])
    tl.grab()
    tl.set_preview_regions([(2.0, 4.0)], tracks=[a1.id])
    tl.grab()
    print("✓ tramo fuera de la vista: sin errores")

    print("TODO OK")


if __name__ == "__main__":
    main()
