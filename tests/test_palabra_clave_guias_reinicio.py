"""
Prueba de tres cosas de la biblioteca y el visor (07/11/2026):
  1) 🔑 Clic derecho en un medio → «Añadir en la palabra clave seleccionada» (en la banderita elegida de la regla) y
     «Añadir en todas las «<palabra>» (N)»: una copia en cada marca con ese texto, en un solo Ctrl+Z.
  2) ▦ Guías por pestaña: Edits y Shorts empiezan en 9:16, YouTube sin relación de aspecto; lo que elijas a mano en
     una pestaña se recuerda en esa pestaña.
  3) ⟲ Reiniciar todo: quita todos los medios (los de la línea de tiempo se quedan), no borra los originales y, si
     lo pides, borra sus miniaturas / copias ligeras / formas de onda (y los análisis con la casilla).
Usa una carpeta de datos TEMPORAL y ventana fuera de pantalla; tus ajustes quedan como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_palabra_clave_guias_reinicio.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def wait_analyzed(app, ctrl):
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.05)


def video(path, secs):
    from editoria.core import media as MEDIA
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(secs), "-pix_fmt", "yuv420p", "-shortest",
                    path], check=True, timeout=180, creationflags=0x08000000)
    return path


def image(path, color):
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor(color))
    img.save(path)
    return path


def menu_actions(lib, ids):
    m = QMenu()
    lib._keyword_actions(m, lambda: ids)
    return [(a.text(), a.isEnabled(), a) for a in m.actions()], m


def part_keywords(app, win, out):
    from editoria.ui.hint_marks import set_source
    ctrl, tl, lib = win.ctrl, win.timeline, win.library
    vid = ctrl.import_paths([video(os.path.join(out, "base.mp4"), 12)])[0]
    clip_v = ctrl.import_paths([video(os.path.join(out, "clip.mp4"), 2)])[0]
    wait_analyzed(app, ctrl)
    base = ctrl.add_media([vid], None, 0.0)            # la «narración»: ocupa V1 de 0 a 12 s
    assert base, "no se pudo poner el video base"
    pump(app, 0.2)
    set_source(tl, "clips", [(1.0, "🎬 PlayStation"), (5.0, "🎬 PlayStation"), (9.0, "🎬 Xbox")])
    set_source(tl, "buscar", [(5.0, "🔎 playstation")])     # la misma aparición desde 🔎 Buscar: no se duplica
    win.engine.seek(3.0)
    pump(app, 0.2)

    # Sin banderita elegida y con el cabezal lejos: la opción sale apagada y explica qué hacer
    acts, _m = menu_actions(lib, [clip_v])
    assert len(acts) == 1 and not acts[0][1] and "selecciona una palabra clave" in acts[0][0], acts
    print("✓ sin palabra clave elegida: «Añadir en la palabra clave seleccionada (selecciona una…)» apagada")

    # Clic de verdad en la primera banderita: queda elegida y el cabezal va ahí
    r = tl._hint_rect(0)
    assert r is not None, "la banderita no se ve"
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r.center().toPoint())
    pump(app, 0.2)
    assert tl.hint_selected == 0, tl.hint_selected
    assert abs(win.engine.time - 1.0) < 0.05, win.engine.time
    # Si las marcas se vuelven a enviar iguales, sigue elegida
    set_source(tl, "buscar", [(5.0, "🔎 playstation")])
    assert tl.hint_selected == 0
    win.engine.seek(7.0)                                # aunque muevas el cabezal, vale la elegida
    acts, _m = menu_actions(lib, [clip_v])
    texts = [t for t, _e, _a in acts]
    assert len(acts) == 2 and all(e for _t, e, _a in acts), texts
    assert "«PlayStation», 00:01" in texts[0] and texts[1].endswith("todas las «PlayStation» (2)"), texts
    print("✓ clic en la banderita «PlayStation» → menú:", " | ".join(texts))

    # «Añadir en todas» (ahora pregunta: aquí se responde «Por partes»): un trozo en 1 s y otro en 5 s, sin sonido
    # (B-roll), en UN paso de deshacer
    win._pregunta_modo_palabra = lambda una_marca: "partes"
    n_undo = ctrl.undo_stack.count()
    before = set(ctrl.project.clips)
    acts[1][2].trigger()
    pump(app, 0.2)
    new = [ctrl.project.clips[i] for i in set(ctrl.project.clips) - before]
    # El clip de prueba dura 2 s: el 1.er trozo se come casi todo y el de 0:05 NO CABE → se omite (y se avisa).
    vids = sorted(c.start for c in new if c.media_id == clip_v and ctrl.project.track(c.track_id).kind == "video")
    assert vids == [1.0], vids
    assert len(new) == 1 and all(c.volume == 0.0 for c in new), f"esperaba 1 trozo de video sin sonido: {len(new)}"
    assert all(c.track_id != ctrl.project.clips[base[0]].track_id for c in new), "tapó el video base"
    assert ctrl.undo_stack.count() == n_undo + 1, (n_undo, ctrl.undo_stack.count())
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == before, "Ctrl+Z no lo quitó todo de una vez"
    ctrl.undo_stack.redo()
    assert len(set(ctrl.project.clips) - before) == 1
    print("✓ «Añadir en todas las «PlayStation» (2)» (Por partes): trozo en 0:01 sin sonido; el de 0:05 se omite "
          "porque el clip de 2 s ya no da más; un solo Ctrl+Z las quita y Ctrl+Y las devuelve")

    # «Añadir en la palabra clave seleccionada» (una marca): «Un trozo», igual que el cabezal pero en la marca
    win._pregunta_modo_palabra = lambda una_marca: "partes"
    before = set(ctrl.project.clips)
    acts[0][2].trigger()
    pump(app, 0.2)
    new = [ctrl.project.clips[i] for i in set(ctrl.project.clips) - before if ctrl.project.clips[i].media_id == clip_v]
    assert len(new) == 1 and all(abs(c.start - 1.0) < 1e-6 for c in new), [(c.start, c.track_id) for c in new]
    print("✓ «Añadir en la palabra clave seleccionada» (Un trozo): un trozo en 0:01 sin sonido")
    del win._pregunta_modo_palabra

    # Sin elegida, vale la banderita que está justo en el cabezal
    tl.select_hint(-1)
    win.engine.seek(9.0)
    acts, _m = menu_actions(lib, [clip_v])
    assert len(acts) == 1 and acts[0][1] and "«Xbox», 00:09" in acts[0][0], [a[0] for a in acts]
    print("✓ sin elegir ninguna, vale la que está en el cabezal («Xbox»; sale una vez → sin «todas»)")
    set_source(tl, "clips", [])
    set_source(tl, "buscar", [])
    assert tl.keyword_target(9.0) is None and tl.hint_selected == -1
    print("✓ al quitar las marcas no queda ninguna elegida")


def part_guides(app, win):
    st = QSettings("EditorIA", "EditorIA")
    for k in ("visor/guias_edit", "visor/guias_short"):
        st.remove(k)
    st.setValue("visor/guias", "")
    pv, ws = win.preview, win.workspaces
    nine = f"a:{9 / 16:.4f}"

    def state():
        return pv.canvas.guides.modes, {k for k, b in pv.guides_panel.buttons.items() if b.isChecked()}

    pv.set_guides_space(ws.current)
    assert ws.current == "youtube" and state() == (set(), {"a:"}), state()
    assert ws.switch("edit")
    pump(app, 0.2)
    assert state() == ({nine}, {nine}), state()
    print("✓ Edits empieza con la guía 9:16 marcada")
    assert ws.switch("short")
    pump(app, 0.2)
    assert state() == ({nine}, {nine}), state()
    pv.guides_panel.buttons["thirds"].setChecked(True)          # el usuario añade tercios en Shorts
    pv.guides_panel.buttons[f"a:{1.0:.4f}"].setChecked(True)    # y cambia a 1:1
    pump(app, 0.1)
    assert state()[0] == {"thirds", "a:1.0000"}, state()
    print("✓ Shorts empieza en 9:16; lo cambio a mano a 1:1 + tercios")
    assert ws.switch("youtube")
    pump(app, 0.2)
    assert state() == (set(), {"a:"}), state()
    print("✓ YouTube sigue sin relación de aspecto («Predet.» = 16:9)")
    assert ws.switch("short")
    pump(app, 0.2)
    assert state()[0] == {"thirds", "a:1.0000"}, state()
    assert ws.switch("edit")
    pump(app, 0.2)
    assert state() == ({nine}, {nine}), state()
    print("✓ al volver a Shorts se recuerda su 1:1 + tercios; Edits sigue en 9:16")
    assert ws.switch("youtube")
    pump(app, 0.2)


def part_reset(app, win, out):
    from editoria.core import media as MEDIA
    from editoria.core.paths import cache_dir
    ctrl, lib, p = win.ctrl, win.library, win.ctrl.project
    imgs = [image(os.path.join(out, f"img{i}.png"), c) for i, c in enumerate(("#c86428", "#2864c8"))]
    ids = ctrl.import_paths(imgs)
    wait_analyzed(app, ctrl)
    ctrl.set_media_props([ids[1]], category="Otra categoría")
    used = [m.id for m in p.media.values() if p.is_media_used(m.id)]
    assert used, "debería haber medios en la línea de tiempo (de la parte 1)"
    n_clips = len(p.clips)
    all_before = set(p.media)

    def fake(sub, path, suffix):
        f = cache_dir(sub) / f"{MEDIA.cache_key(path)}{suffix}"
        f.write_bytes(b"x" * 100)
        return str(f)

    def make_caches():
        files = [fake("proxies", imgs[0], "_half.mp4"), fake("formas_de_onda", imgs[1], "_v2.npy"),
                 fake("miniaturas", imgs[1], ".jpg")]
        return files, fake("huellas_clips", imgs[0], "_v3.npz")

    def press(text, check=False):
        def go():
            box = lib._reset_box
            if box is None:
                QTimer.singleShot(50, go)
                return
            box.checkBox().setChecked(check)
            for b in box.buttons():
                if b.text() == text:
                    b.click()
                    return
            raise AssertionError(f"no está el botón «{text}»: {[b.text() for b in box.buttons()]}")
        QTimer.singleShot(100, go)

    used_path = p.media[used[0]].path
    keep_proxy = fake("proxies", used_path, "_half.mp4")
    files, ana = make_caches()

    plan = lib.reset_plan()
    assert sorted(plan["all"]) == sorted(all_before), plan["all"]
    assert sorted(plan["used"]) == sorted(used)
    assert sorted(plan["free"]) == sorted(all_before - set(used))
    cache = lib.reset_cache(plan["free"])
    assert len(cache["copias"]) == 1 and len(cache["analisis"]) == 1, cache
    assert keep_proxy not in [f for fs in cache.values() for f in fs]
    print(f"✓ plan: {len(plan['all'])} medios de todas las categorías; {len(plan['used'])} están en la línea de "
          "tiempo")

    # Cancelar: no cambia nada
    press("Cancelar")
    lib.reset_all()
    assert set(p.media) == all_before and all(os.path.exists(f) for f in files + [ana]) and len(p.clips) == n_clips
    print("✓ «Cancelar» no toca nada")

    # «Quitar solo los que no se usan» + casilla: fuera los libres y su caché; la línea de tiempo intacta
    press("Quitar solo los que no se usan", check=True)
    lib.reset_all()
    pump(app, 0.3)
    assert set(p.media) == set(used), (set(p.media), used)
    assert len(p.clips) == n_clips, "la línea de tiempo cambió"
    assert all(os.path.exists(f) for f in imgs), "¡borró un archivo original!"
    assert not any(os.path.exists(f) for f in files) and not os.path.exists(ana)
    assert os.path.exists(keep_proxy), "borró la caché de un medio que se queda"
    print("✓ «Quitar solo los que no se usan» + casilla: quita los libres, borra su caché (miniaturas, copias, "
          "ondas, análisis); originales y línea de tiempo intactos")

    # Ctrl+Z devuelve la biblioteca (la caché borrada NO vuelve)
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    assert set(p.media) == all_before and len(p.clips) == n_clips, (set(p.media), len(p.clips))
    assert not any(os.path.exists(f) for f in files), "la caché borrada no debería volver"
    print("✓ Ctrl+Z devuelve la biblioteca; la caché borrada no vuelve")
    ctrl.undo_stack.redo()
    pump(app, 0.3)
    assert set(p.media) == set(used)

    # «Quitar también sus clips»: vuelve todo (Ctrl+Z) y se quita con sus clips; sin casilla no borra caché
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    files, ana = make_caches()
    press("Quitar también sus clips de la línea de tiempo", check=False)
    lib.reset_all()
    pump(app, 0.3)
    assert len(p.media) == 0 and len(p.clips) == 0, (len(p.media), len(p.clips))
    assert all(os.path.exists(f) for f in imgs + files + [ana, keep_proxy]), "sin casilla no se borra caché"
    print("✓ «Quitar también sus clips»: biblioteca y clips vacíos, sin casilla la caché queda")
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    assert set(p.media) == all_before and len(p.clips) == n_clips, (len(p.media), len(p.clips))
    print("✓ Ctrl+Z lo devuelve todo (biblioteca y clips) de una vez")

    # Con la casilla, miniaturas/copias/ondas/análisis de los que se quitan se borran; los originales no
    ctrl.undo_stack.redo()
    pump(app, 0.3)
    assert len(p.media) == 0
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    press("Quitar también sus clips de la línea de tiempo", check=True)
    lib.reset_all()
    pump(app, 0.3)
    assert len(p.media) == 0 and len(p.clips) == 0
    assert not any(os.path.exists(f) for f in files) and not os.path.exists(ana)
    assert all(os.path.exists(f) for f in imgs), "¡borró un archivo original!"
    print("✓ con la casilla: se borran las cachés de esos medios; los archivos originales siguen en el disco")


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.3)
    try:
        part_keywords(app, win, out)
        part_guides(app, win)
        part_reset(app, win, out)
    finally:
        win.ctrl._media_dirty = False          # (prueba: nada que guardar al cerrar; si no, sale un aviso modal)
        win.ctrl.undo_stack.setClean()
        try:
            from editoria.ui.task_window import stop_all
            stop_all(6000)
        except Exception:  # noqa: BLE001
            pass
        win.close()
        pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
