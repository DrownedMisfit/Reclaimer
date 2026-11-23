"""
🔑 «🎬 Crear escena desde palabras clave» (Escenas → Material → 🔑 Palabras; core/categorias_palabras.py).
  · Núcleo: detecta palabras por categoría con conjugaciones, plurales y sin tildes («disparó», «balacera», «huyeron»,
    «premiación», «ganó»…), frases («abrió fuego») y deja fuera las neutras («vale la pena»); agrupa con cuántas veces;
    rota las prehechas sugeridas sin repetir seguidas y no solapa escenas.
  · Página: «🔍 Buscar en lo que digo» llena la lista por categorías con sus veces; las imágenes elegidas en 🗂 Local
    hacen los papeles; cambiar la escena de una categoría; 🌐 prepara la búsqueda de PNG y la imagen usada va a su
    papel; 📁 desde el PC; una vez desmarcada no lleva escena; «⚡ Acomodar» pone todas en UN paso de Ctrl+Z, sin
    solaparse y sin repetir la misma prehecha seguida; repetir no pone encima de las ya puestas.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_palabras.py <carpeta_salida>   (sin ventanas, sin sonido)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# (segundo, palabra) de la narración (el audio empieza en el 0 de la línea de tiempo)
NARRACION = [(1.0, "Hoy"), (1.3, "la"), (1.6, "premiación"), (8.0, "disparó"), (16.0, "¡Disparos!"),
             (24.0, "balacera"), (25.0, "disparan"), (32.0, "huyeron"), (40.0, "explotó"), (44.0, "vale"),
             (44.3, "la"), (44.5, "pena"), (48.0, "ganó"), (56.0, "trofeo.")]
DUR = 60.0


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def png(nombre, color):
    from PIL import Image, ImageDraw
    ruta = os.path.join(_TMP, nombre)
    im = Image.new("RGBA", (200, 320), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((60, 10, 140, 90), fill=color + (255,))
    d.rounded_rectangle((40, 95, 160, 310), radius=30, fill=color + (255,))
    im.save(ruta)
    return ruta


def wav_mudo(ruta, dur):
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * dur))
    return ruta


def nucleo():
    from editoria.core import categorias_palabras as CP
    from editoria.core import escenas_prehechas as PH
    ws = [(t, t + 0.3, w) for t, w in NARRACION]
    ms = CP.detectar(ws, CP.ESCENAS)
    cats = [(m["cat"], CP.dicha(m)) for m in ms]
    assert cats == [("premio", "premiación"), ("disparos", "disparó"), ("disparos", "disparos"),
                    ("disparos", "balacera"), ("disparos", "disparan"), ("huida", "huyeron"),
                    ("explosion", "explotó"), ("premio", "ganó"), ("premio", "trofeo")], cats
    g = CP.agrupar(ms)
    assert [(x["cat"], x["veces"]) for x in g[:2]] == [("disparos", 4), ("premio", 3)], g
    assert g[0]["palabras"]["disparó"] == [8.0]
    # frases, conjugaciones raras y palabras que no deben contar
    f = CP.detectar([(0, .3, "y"), (.3, .6, "abrió"), (.6, .9, "fuego"), (2, 2.3, "persecución"), (3, 3.3, "corre"),
                     (4, 4.3, "correo"), (5, 5.3, "navegador"), (6, 6.3, "Holanda"), (7, 7.3, "tengo"),
                     (7.3, 7.6, "ganas")], CP.ESCENAS)
    assert [(m["cat"], m["palabra"]) for m in f] == [("disparos", "abrio fuego"), ("huida", "persecucion"),
                                                       ("huida", "corre")], f
    assert all(k in PH.POR_CLAVE for c in CP.ESCENAS for k in c["prehechas"]), "las sugeridas existen"
    assert len({c["clave"] for c in CP.ESCENAS}) == len(CP.ESCENAS) >= 12
    # rotación y plan
    assert CP.rotacion("disparos", "duelo") == ["duelo", "tiroteo", "contra_grupo"]
    assert CP.rotacion("disparos", "duelo", variar=False) == ["duelo"]
    assert CP.rotacion("disparos", "pelea")[0] == "pelea", "una prehecha de otra categoría también vale"
    elegir = {c: CP.rotacion(c) for c in ("premio", "disparos", "huida", "explosion")}
    plan, saltadas = CP.plan_escenas(ms, elegir, lambda k: PH.POR_CLAVE[k]["dur"], ocupado=[(39.0, 41.0)])
    claves = [(t, k) for t, _c, k in plan]
    assert ("disparos", 25.0) not in [(c, t) for t, c, _k in plan] and saltadas == 2, (plan, saltadas)
    assert [k for t, c, k in plan if c == "disparos"] == ["tiroteo", "duelo", "contra_grupo"], claves
    assert [k for t, c, k in plan if c == "premio"] == ["victoria", "saltan", "ganador_perdedor"], claves
    assert all(a[1] != b[1] for a, b in zip(claves, claves[1:])), "nunca la misma seguida"
    tramos = sorted((t, t + PH.POR_CLAVE[k]["dur"]) for t, k in claves)
    assert all(a[1] <= b[0] for a, b in zip(tramos, tramos[1:])), "no se solapan"
    print(f"✓ núcleo: {len(ms)} momentos en {len(g)} categorías (conjugaciones, sin tildes, frases, neutras fuera); "
          f"rotación sin repetir y sin solapes ({len(plan)} escenas, {saltadas} saltadas)")


def main():
    nucleo()
    app = QApplication.instance() or QApplication([])
    from editoria.core import categorias_palabras as CP
    from editoria.core.model import TRACK_AUDIO
    from editoria.ui.main_window import MainWindow
    rA, rB, rC = png("rojo.png", (220, 60, 60)), png("azul.png", (60, 90, 220)), png("verde.png", (60, 180, 90))
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ws, ctrl = win.workspaces, win.ctrl
        ws.switch("youtube")
        pump(app, 0.2)
        p = ctrl.project
        voz = wav_mudo(os.path.join(_TMP, "voz.wav"), DUR)
        (aid,) = ctrl.import_now([voz])
        while ctrl.analyzing:
            pump(app, 0.1)
        a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
        ctrl.add_media([aid], a1.id, 0.0)
        p.transcripts[aid] = {"language": "es", "words": [[t, t + 0.3, w, 0.9] for t, w in NARRACION]}
        a_id, b_id = ctrl.media_for_path(rA, "Escenas"), ctrl.media_for_path(rB, "Escenas")
        p.mark_in = p.mark_out = None
        win.go_page("scenes")
        pump(app, 0.4)
        pg = win._scenes_widget
        assert pg.material.tabText(3) == "Palabras clave"
        pg._llenar_imagenes()
        for i in range(pg.lista_img.count()):
            it = pg.lista_img.item(i)
            it.setSelected(it.data(Qt.UserRole) in (a_id, b_id))

        # ------------------------------------------------ 🌐 Internet como 🔎 PNG de 🖼 Miniatura
        from urllib.parse import parse_qs, urlsplit

        def q_de(u):
            return parse_qs(urlsplit(u).query)
        qs = q_de(pg._url_busqueda("png", "persona"))
        assert qs.get("udm") == ["2"] and qs.get("tbm") == ["isch"], qs
        assert "ic:trans" in qs["tbs"][0] and "ift:png" in qs["tbs"][0], qs
        pg.web_sin_marca.setChecked(False)
        assert q_de(pg._url_busqueda("png", "persona"))["q"][0] == "persona png"
        assert q_de(pg._url_busqueda("png", "logo png"))["q"][0] == "logo png", "sin «png» repetido"
        pg.web_sin_marca.setChecked(True)
        assert "-site:" in q_de(pg._url_busqueda("png", "persona"))["q"][0], "sin marca de agua"
        f = q_de(pg._url_busqueda("fondo", "bosque"))
        assert f.get("udm") == ["2"] and "isz:l" in f["tbs"][0] and f["q"][0].startswith("bosque wallpaper"), f
        web = pg.sub_img.widget(1).layout()
        caja = pg._busq["png"]["caja"]
        i_caja = next(i for i in range(web.count()) if web.itemAt(i).layout() is caja)
        assert web.stretch(i_caja) == 1, "el navegador se lleva todo el alto"
        assert all(web.stretch(i) == 0 for i in range(web.count()) if i != i_caja), "nada más le quita alto"
        sec = getattr(pg, "sec_fandom", None)
        if sec is not None:                                 # (solo en la copia con la parte local)
            assert web.indexOf(sec) > i_caja, "Fandom, debajo del navegador"
            sec.set_open(False, save=False)
            assert sec.body.isHidden()
        assert not pg._split.childrenCollapsible() and pg.material.maximumWidth() > 5000
        t = pg._split.sizes()
        pg._split.setSizes([270, sum(t) - 270 - sum(t[2:])] + t[2:])
        pg._ensanchar_material()
        hay = sum(t) - 200 - sum(max(pg._split.widget(i).minimumSizeHint().width(), pg._split.widget(i).minimumWidth())
                                 for i in range(2, pg._split.count()))
        assert pg._split.sizes()[0] >= min(560, hay) - 2, (pg._split.sizes(), hay)
        pg._split.setSizes([800, max(200, sum(t) - 800 - sum(t[2:]))] + t[2:])
        assert pg._split.sizes()[0] >= min(750, hay) - 2, ("se puede ensanchar arrastrando", pg._split.sizes(), hay)
        print("✓ 🌐 Internet: Google Imágenes con udm=2 y transparencia, «png» en la consulta, sin marca de agua; "
              "navegador a todo el alto, Fandom plegable debajo; «Material» se ensancha", flush=True)

        # ------------------------------------------------ 🔍 buscar en lo que digo
        grupos = pg._pal_analizar()
        arbol = pg.pal_arbol
        assert arbol.topLevelItemCount() == len(grupos) == 4, arbol.topLevelItemCount()
        tops = {arbol.topLevelItem(i).data(0, Qt.UserRole)[1]: arbol.topLevelItem(i)
                for i in range(arbol.topLevelItemCount())}
        assert tops["disparos"].childCount() == 4 and "4 veces" in tops["disparos"].text(0)
        assert "disparó (1)" in tops["disparos"].toolTip(0)
        assert tops["disparos"].checkState(0) == Qt.Checked
        assert pg._pal_cat == "disparos" and not pg.pal_ajustes.isHidden(), "elige la primera categoría"
        cfg = pg._pal_cfg["disparos"]
        assert {cfg["medios"]["A"], cfg["medios"]["B"]} == {a_id, b_id}, cfg
        assert pg.pal_pre.currentData() == "tiroteo" and pg.pal_pre.itemText(0).startswith("★")
        assert set(pg._pal_combos) == {"A", "B", "G"}, "papeles de las tres que se turnan"
        assert pg._pal_combos["A"].currentData() == cfg["medios"]["A"]
        print(f"✓ página: {len(grupos)} categorías con sus veces; papeles con lo elegido en 🗂 Local")

        # cambiar la escena de una categoría y sin variar
        arbol.setCurrentItem(tops["explosion"])
        assert pg._pal_cat == "explosion" and set(pg._pal_combos) == {"A"}
        arbol.setCurrentItem(tops["huida"])
        pg.pal_pre.setCurrentIndex(pg.pal_pre.findData("huida"))
        assert pg._pal_cfg["huida"]["pre"] == "huida"
        pg.pal_variar.setChecked(False)
        assert pg._pal_rotacion("huida") == ["huida"]
        tops["huida"].child(0).setCheckState(0, Qt.Unchecked)      # (ahí no quiero escena)
        assert tops["huida"].checkState(0) == Qt.Unchecked, "la categoría sigue a sus veces"

        # 🌐 buscar PNG para un papel → la imagen usada va a ese papel (no a la escena)
        arbol.setCurrentItem(tops["premio"])
        pg._pal_buscar_png("A", buscar=False)
        assert pg.material.currentIndex() == 0 and pg.sub_img.currentIndex() == 1
        assert pg._busq["png"]["q"].text() == "trofeo" and pg._modo_web == "png"
        assert pg._pal_destino == ("premio", "A")
        c_id = ctrl.media_for_path(rC, "Escenas")
        actores = len(pg.escena["actores"])
        pg._pal_recibir(c_id)
        assert pg._pal_cfg["premio"]["medios"]["A"] == c_id and pg._pal_destino is None
        assert pg.material.currentIndex() == 3 and pg._pal_combos["A"].currentData() == c_id
        assert len(pg.escena["actores"]) == actores, "no se añade a la escena abierta"
        # 📁 desde el PC (sin el diálogo)
        assert pg._pal_poner_archivo("B", rA) == a_id and pg._pal_cfg["premio"]["medios"]["B"] == a_id
        print("✓ escena por categoría cambiable, sin variar, desmarcar; 🌐 PNG y 📁 van a su papel")

        # ------------------------------------------------ ⚡ acomodar
        n_antes = len(p.scenes)
        esc = pg._pal_acomodar()
        assert esc, pg.pal_estado.text()
        # premio ×3, disparos ×3 (el 4.º cae encima), explosión ×1; huida desmarcada
        assert len(esc) == 7, [(e["nombre"], e["a"]) for e in esc]
        assert len(p.scenes) == n_antes + 7
        for e in esc:
            assert e["id"] in p.scenes and ctrl.scene_clips(p, e["id"]), e["nombre"]
        por = sorted(esc, key=lambda e: e["a"])
        assert [round(e["a"], 1) for e in por] == [1.6, 8.0, 16.0, 24.0, 40.0, 48.0, 56.0], [e["a"] for e in por]
        assert [e["prehecha"] for e in por if e.get("palabra_clave") == "disparos"] == \
            ["tiroteo", "duelo", "contra_grupo"]
        assert [e["prehecha"] for e in por if e.get("palabra_clave") == "premio"] == \
            ["victoria", "saltan", "ganador_perdedor"]
        assert all(a["prehecha"] != b["prehecha"] for a, b in zip(por, por[1:]))
        assert all(float(a["b"]) <= float(b["a"]) + 1e-6 for a, b in zip(por, por[1:])), "sin solapes"
        vic = next(e for e in por if e["prehecha"] == "victoria")
        assert {x["media_id"] for x in vic["actores"] if not x.get("efecto")} == {c_id}, "la imagen bajada"
        tir = next(e for e in por if e["prehecha"] == "tiroteo")
        assert {x["media_id"] for x in tir["actores"] if not x.get("efecto")} == {a_id, b_id}
        assert "7 escenas puestas" in pg.pal_estado.text() and "1 saltadas" in pg.pal_estado.text()
        assert pg.sel_escena.findData(esc[0]["id"]) >= 0, "salen en la lista de escenas"
        print(f"✓ ⚡ acomodar: {len(esc)} escenas en un paso, en su segundo, sin solapes ni repetir seguidas, con "
              "las imágenes de cada categoría")

        # otra vez: todo cae encima de las ya puestas → no pone nada
        assert pg._pal_acomodar() is None and len(p.scenes) == n_antes + 7
        ctrl.undo_stack.undo()
        assert len(p.scenes) == n_antes and not any(ctrl.scene_clips(p, e["id"]) for e in esc), "Ctrl+Z las quita"
        print("✓ repetir no pone encima; un Ctrl+Z en el editor las quita todas")

        # sin transcripción: lo dice
        p.transcripts.clear()
        assert pg._pal_analizar() == [] and "transcrib" in pg.pal_estado.text()
        assert pg.pal_arbol.topLevelItemCount() == 0 and not pg.b_pal_acomodar.isEnabled()
        print("✓ sin transcripción lo dice")
        assert CP.POR_CLAVE_ESCENA["risa"]["prehechas"][0] == "risa"
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
