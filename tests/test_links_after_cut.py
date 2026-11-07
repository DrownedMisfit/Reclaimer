"""
Prueba de los VÍNCULOS tras «✂ Eliminar silencio»: cada trozo de imagen queda vinculado SOLO con su trozo de sonido
(antes, los ~600 trozos de la narración compartían un vínculo: un clic seleccionaba todo y Supr lo borraba todo).
Comprueba: parejas de 2 clips; un clic selecciona 2 clips y Supr solo borra esos 2; y un proyecto guardado con el
fallo se repara al abrirlo.
Ejecutar:  .venv/Scripts/python.exe tests/test_links_after_cut.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Project  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def grupos_ok(p) -> tuple[int, int]:
    """(vínculos distintos, vínculos con más o menos de 2 clips)."""
    cnt = Counter(c.link for c in p.clips.values() if c.link)
    return len(cnt), sum(1 for v in cnt.values() if v != 2)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    voz = os.path.join(out, "voz.wav")
    nar = os.path.join(out, "narracion.mp4")          # video con su sonido (como una grabación de la narración)
    # voz de 20 s con pausas cortas (0,3 s) cada segundo y medio: 17 silencios que quitar
    pausas = "+".join(f"between(t,{k + 0.5},{k + 0.8})" for k in range(1, 18))
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=20", "-af",
                    f"volume='if({pausas},0,1)':eval=frame", voz], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                    "-i", voz, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", nar], check=True)

    from editoria.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    c = win.ctrl
    tl = win.timeline
    tl.set_linked(True)
    p = c.project
    p.fps = 30.0
    (nm,) = c.import_now([nar])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    c.add_media([nm], v1.id, 0.0)          # su sonido va a una pista de audio, vinculado (split_av)
    while c.analyzing:
        pump(app, 0.1)
    narr_ids = [cid for cid in p.clips if p.clips[cid].media_id == nm]
    assert len(narr_ids) == 2, "debe haber imagen y sonido de la narración"
    regions = [(k + 0.5, k + 0.8) for k in range(1, 18)]
    c.remove_silence(narr_ids, regions, scope="all")
    n_links, malos = grupos_ok(p)
    assert malos == 0, f"vínculos con clips de más o de menos: {malos}"
    assert n_links >= 17, n_links
    print(f"✓ tras quitar 17 silencios: {n_links} vínculos, cada uno con 2 clips (imagen + sonido)")

    # --- un clic en un trozo de imagen selecciona su pareja, no toda la narración
    def pt(cl):
        i = p.track_index(cl.track_id)
        return QPoint(int(tl.x_for(cl.start + cl.duration / 2)), int(tl.track_y(i) + tl.track_h(i) / 2))

    tl.pps = 40.0
    tl.scroll = 0.0
    tl._update_scrollbar()
    tl.update()
    pump(app, 0.5)
    v_clip = min((cl for cl in p.clips_on(v1.id)), key=lambda cl: abs(cl.start + cl.duration / 2 - 9.0))
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, pt(v_clip))
    pump(app, 0.3)
    sel = list(tl.selected)
    assert len(sel) == 2, f"un clic debe seleccionar imagen + sonido (2), no {len(sel)}"
    print("✓ un clic en un trozo selecciona 2 clips (imagen y sonido), no toda la narración")

    # --- Supr solo borra esa pareja
    antes = len(p.clips)
    QTest.keyClick(tl, Qt.Key_Delete)
    pump(app, 0.3)
    assert len(p.clips) == antes - 2, (antes, len(p.clips))
    n_links2, malos2 = grupos_ok(p)
    assert malos2 == 0, malos2
    print(f"✓ Supr borra solo esos 2 clips ({antes} → {len(p.clips)}); los demás siguen")
    c.undo_stack.undo()
    pump(app, 0.2)

    # --- proyecto «roto» (todo el narrado con un único vínculo, como se guardaba antes) se repara al abrirlo
    d = p.to_dict()
    for cd in d["clips"]:
        if cd.get("link"):
            cd["link"] = "ROTO0000"
    roto = os.path.join(out, "roto.eia")
    with open(roto, "w", encoding="utf-8") as f:
        json.dump(d, f)
    c.load(roto)
    pump(app, 0.3)
    assert c.project is not p
    n_fix, malos_fix = grupos_ok(c.project)
    assert malos_fix == 0 and n_fix >= 17, (n_fix, malos_fix)
    assert "ROTO0000" not in {x.link for x in c.project.clips.values()}
    p2 = c.project
    cl = min(p2.clips_on(v1.id), key=lambda x: abs(x.start + x.duration / 2 - 9.0))
    i2 = p2.track_index(cl.track_id)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(tl.x_for(cl.start + cl.duration / 2)), int(tl.track_y(i2) + tl.track_h(i2) / 2)))
    pump(app, 0.3)
    assert len(tl.selected) == 2, len(tl.selected)
    print(f"✓ proyecto roto (un vínculo para todo): al abrirlo se reparte en {n_fix} vínculos de 2 clips")

    win.analyzer.shutdown()
    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
