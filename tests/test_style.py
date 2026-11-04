"""
Prueba de «🎨 Mi estilo» (fase 6): aprender de una carpeta de miniaturas (OCR local, caras, colores),
el diálogo, y que las propuestas usen el estilo (palabra clave en otro color, contorno, tamaño)
sin pisar lo que el usuario corrigió a mano.
Ejecutar:  .venv/Scripts/python.exe tests/test_style.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import thumb_proposals as P
    from editoria.ai import thumb_style as S
    from editoria.core import thumbnail as T
    qs = QSettings("EditorIA", "EditorIA")
    saved = {k: qs.value(k) for k in ("miniatura/estilo", "miniatura/preferencias")}
    try:
        # Material: un fondo con un «personaje»
        rng = np.random.default_rng(3)
        img = (rng.random((720, 1280, 3)) * 50 + 60).astype(np.uint8)
        img = cv2.GaussianBlur(img, (0, 0), 8)
        cv2.ellipse(img, (900, 480), (150, 200), 0, 0, 360, (60, 90, 40), -1)
        bg = os.path.join(out, "fondo.png")
        cv2.imwrite(bg, img)

        # 5 «miniaturas mías»: texto blanco con contorno negro + la palabra clave en ROJO, a la izquierda
        mine = os.path.join(out, "mis_miniaturas")
        os.makedirs(mine, exist_ok=True)
        for i, (a, b) in enumerate([("FUE PURO", "EGO"), ("TIENES QUE", "VERLO"), ("ESTAMOS", "MAL"),
                                    ("NADIE", "LO VIO"), ("POR FIN", "LLEGÓ")]):
            d = T.new_doc("youtube")
            d["layers"].append(T.image_layer(bg, d, "f", fill=True))
            for j, (txt, col) in enumerate(((a, "#FFFFFF"), (b, "#FF1A0A"))):
                t = T.text_layer(d, txt, "title")
                t["color"], t["rotation"] = col, 0
                t["x"], t["y"] = 340, 290 + j * 150
                d["layers"].append(t)
            T.export(d, os.path.join(mine, f"mini_{i}.jpg"))

        prof = S.build_profile(S.list_images([mine]))
        yt = prof["youtube"]
        print("   ", S.describe(prof, "youtube"))
        assert prof["n"] == 5 and 2 <= yt["words"] <= 4, yt
        assert yt["upper"] and yt["text_side"] == "left"
        assert S._dist(yt["text_color"], "#FFFFFF") < 60, yt["text_color"]
        assert yt["accent_share"] >= 0.6 and S._dist(yt["accent_color"], "#FF1A0A") < 80, yt
        assert yt["outline_share"] >= 0.4
        prefs = S.to_prefs(prof, None, "youtube", 1280)
        assert prefs["accent"] and prefs["outline"] and prefs["text_side"] == "left" and prefs["uppercase"]
        print("✓ estudia una carpeta: ~3 palabras, mayúsculas, blanco con contorno, palabra clave en rojo, izquierda")

        # Para Shorts (sin miniaturas verticales) se toma lo que no depende del tamaño
        ps = S.to_prefs(prof, None, "short", 1080)
        assert ps.get("accent") and "text_side" not in ps and "size_k" not in ps
        print("✓ sin Shorts propios: usa color/contorno/palabras, no tamaño ni posición")

        # Propuestas con el estilo: título en dos piezas, la última palabra en rojo
        props = P.proposals("youtube", [bg], "NADIE LO ESPERABA", prefs)
        texts = [l for l in props[0][1]["layers"] if l["kind"] == "text"]
        assert len(texts) == 2 and texts[1]["text"] == "ESPERABA" and texts[1]["color"] == prefs["accent"], texts
        assert texts[0]["outline"]["on"] and texts[1]["y"] > texts[0]["y"]
        T.render(props[0][1], 0.5).save(os.path.join(out, "propuesta_estilo.png"))
        print("✓ propuestas con tu estilo: «NADIE LO» + «ESPERABA» en rojo debajo")

        # Sin estilo propio: valores del estudio de miniaturas de YouTube
        d0 = S.to_prefs(None, None, "youtube", 1280, defaults=True)
        assert d0["accent"] and d0["outline"] and d0["uppercase"] and d0["max_words"] <= 4 and d0["size_k"] > 1.1
        assert S.to_prefs(None, None, "youtube", 1280) == {}
        print("✓ sin estilo propio: punto de partida del estudio de YouTube (2–3 palabras, blanco + rojo, grande)")

        # Referencias: rellenan lo que falta, pero lo tuyo manda
        ref_prof = {"youtube": {"n": 3, "text_color": "#00FF00", "accent_share": 0.0, "words": 5,
                                "face_h": 0.6}}
        mixed = S.to_prefs(prof, ref_prof, "youtube", 1280)
        assert S._dist(mixed["color"], "#FFFFFF") < 60 and mixed["face_h"] == 0.6
        print("✓ referencias: completan lo que no sé de ti, sin pisar tu estilo")

        # Diálogo: carpeta → Analizar (en segundo plano) → resumen guardado
        from editoria.ui.thumb_style_dialog import StyleDialog, load
        from editoria.ui.theme import apply_dark_theme
        apply_dark_theme(app)
        qs.remove("miniatura/estilo")
        qs.setValue("miniatura/preferencias", "{}")
        dlg = StyleDialog()
        dlg.own.clear()
        dlg.own.addItem(mine)
        dlg.show()
        dlg.analyze()
        t0 = time.time()
        while dlg.job is not None and time.time() - t0 < 120:
            app.processEvents()
            time.sleep(0.05)
        pump(app, 0.2)
        assert "Tu estilo · YouTube" in dlg.summary.text(), dlg.summary.text()
        dlg.grab().save(os.path.join(out, "dialogo.png"))
        dlg.accept()
        st = load()
        assert st["propio"]["n"] == 5 and st["carpetas"] == [mine] and st["usar"]
        print("✓ diálogo «🎨 Mi estilo»: analiza la carpeta y guarda el perfil")

        # Editor: el estilo entra en las preferencias; lo corregido a mano manda
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        ed = win.open_thumbnail("youtube")
        pump(app, 0.3)
        assert ed._prefs().get("accent") and "Usando tu estilo" in ed.style_lbl.text()
        qs.setValue("miniatura/preferencias", '{"color": "#FFD400"}')
        assert ed._prefs()["color"] == "#FFD400"
        st["usar"] = False
        from editoria.ui.thumb_style_dialog import save
        save(st)
        qs.setValue("miniatura/preferencias", "{}")
        off = ed._prefs()            # sin tu estilo: lo del estudio de YouTube (blanco + palabra clave en rojo)
        assert off["color"] == "#FFFFFF" and off["accent"] == S.STUDY_DEFAULTS["youtube"]["accent_color"]
        assert "text_side" not in off
        print("✓ editor: usa tu estilo; tus correcciones a mano mandan; desactivado = reglas del estudio de YouTube")
        ed.close()
        win.analyzer.shutdown()
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    finally:
        for k, v in saved.items():
            if v is None:
                qs.remove(k)
            else:
                qs.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
