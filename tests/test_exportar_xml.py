"""
⇄ Llevar a DaVinci Resolve / Premiere (XML xmeml 5), sin ventanas visibles:
  · XML bien formado, con la secuencia a los FPS del proyecto (29,97 → 30 + NTSC) y su tamaño;
  · cada clip con su archivo (definido UNA vez y luego por referencia), inicio/fin en la línea de tiempo y entrada/salida
    en el archivo, en fotogramas;
  · V1 del XML = la pista de abajo de Reclaimer; desactivados, velocidad/reversa (Time Remap), volumen y opacidad;
  · transiciones (disolver centrado en el corte), vínculos imagen/sonido y marcadores;
  · lo que no viaja (textos, color…) sale en las notas; desde el menú Archivo se guarda y avisa.
Ejecutar:  .venv/Scripts/python.exe tests/test_exportar_xml.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_xml_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, Marker, MediaItem, Project  # noqa: E402
from editoria.export.xml_export import export_xml  # noqa: E402


def proyecto():
    p = Project.new()
    p.fps = 29.97
    p.name = "Mi reseña & co"
    vt = [t for t in p.tracks if t.kind == "video"]
    at = [t for t in p.tracks if t.kind == "audio"]
    p.media["v"] = MediaItem(id="v", path=os.path.join(_TMP, "partida ñ.mp4"), kind=KIND_VIDEO, name="partida ñ.mp4",
                             duration=120, width=2560, height=1440, fps=59.94, probed=True, has_audio=True, channels=2)
    p.media["m"] = MediaItem(id="m", path=os.path.join(_TMP, "musica.mp3"), kind=KIND_AUDIO, name="musica.mp3",
                             duration=200, probed=True, has_audio=True, channels=2)
    abajo = vt[-1]                                   # (la última de la lista = la de abajo)
    p.clips["a"] = Clip("a", "v", abajo.id, 0.0, 10.0, 4.0, link="L1")
    p.clips["a_s"] = Clip("a_s", "v", at[0].id, 0.0, 10.0, 4.0, link="L1", volume=0.5)
    p.clips["b"] = Clip("b", "v", abajo.id, 4.0, 30.0, 3.0, speed=2.0, reverse=True)
    p.clips["b"].fx = {"trans": {"type": "fade", "dur": 1.0}}
    p.clips["c"] = Clip("c", "v", abajo.id, 7.0, 50.0, 2.0, enabled=False, opacity=0.4)
    p.clips["c"].color = {"exposure": 0.3}
    p.clips["t"] = Clip("t", "", vt[0].id, 1.0, 0.0, 2.0, text={"content": "Hola"})
    p.clips["mu"] = Clip("mu", "m", at[-1].id, 0.0, 0.0, 9.0)
    p.markers.append(Marker(id="mk", time=2.0, label="Ojo aquí"))
    return p


def main():
    p = proyecto()
    path = os.path.join(_TMP, "linea.xml")
    res = export_xml(p, path)
    root = ET.parse(path).getroot()
    assert root.tag == "xmeml" and root.get("version") == "5"
    seq = root.find("sequence")
    assert seq.findtext("name") == "Mi reseña & co"
    assert seq.findtext("rate/timebase") == "30" and seq.findtext("rate/ntsc") == "TRUE"
    assert seq.findtext("media/video/format/samplecharacteristics/width") == str(p.width)
    print("✓ XML bien formado: secuencia a 29,97 (30 + NTSC), con su tamaño y su nombre (con «&» y «ñ»)")

    vtracks = seq.findall("media/video/track")
    v1 = vtracks[0]
    items = v1.findall("clipitem")
    assert [i.findtext("name") for i in items] == ["partida ñ.mp4"] * 3, [i.findtext("name") for i in items]
    a, b, c = items
    f = lambda s: round(s * 29.97)                    # noqa: E731
    assert (a.findtext("start"), a.findtext("end"), a.findtext("in"), a.findtext("out")) == \
        (str(f(0)), str(f(4)), str(f(10)), str(f(10) + f(4))), [a.findtext(k) for k in ("start", "end", "in", "out")]
    assert a.find("file/pathurl").text.startswith("file://localhost/") and "%C3%B1" in a.find("file/pathurl").text
    assert b.find("file").get("id") == a.find("file").get("id") and b.find("file/pathurl") is None, \
        "el archivo se define una vez y luego se referencia"
    print("✓ cada clip con su archivo (una sola definición), inicio/fin y entrada/salida en fotogramas")
    remap = b.find("filter/effect[effectid='timeremap']")
    assert remap is not None and remap.findtext("parameter[parameterid='speed']/value") == "200.0"
    assert remap.findtext("parameter[parameterid='reverse']/value") == "TRUE"
    assert int(b.findtext("out")) - int(b.findtext("in")) == round(3 * 2 * 29.97)
    assert c.findtext("enabled") == "FALSE" and c.find("filter/effect[effectid='opacity']/parameter/value").text == "40.0"
    print("✓ V1 = la pista de abajo; velocidad 2× hacia atrás (Time Remap), desactivado y opacidad 40 %")
    tr = v1.find("transitionitem")
    assert tr is not None and tr.findtext("effect/name") == "Cross Dissolve"
    assert (int(tr.findtext("start")), int(tr.findtext("end"))) == (f(4) - f(0.5), f(4) + f(0.5))
    sonido = [i for i in seq.findall("media/audio/track/clipitem") if i.findtext("name") == "partida ñ.mp4"][0]
    assert sonido.find("filter/effect[effectid='audiolevels']/parameter/value").text == "0.5"
    refs = {lk.findtext("linkclipref") for lk in a.findall("link")}
    assert sonido.get("id") in refs and a.get("id") in refs, "imagen y sonido vinculados"
    assert seq.find("marker").findtext("name") == "Ojo aquí" and seq.find("marker").findtext("in") == str(f(2))
    print("✓ disolver centrado en el corte, volumen del sonido, vínculo imagen/sonido y marcadores")
    assert res["clips"] == 5, res
    assert any("textos" in n for n in res["notes"]) and any("Color" in n for n in res["notes"]), res["notes"]
    print("✓ lo que no viaja (textos, color…) sale en las notas")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.ctrl._replace(proyecto(), None)
    msgs = []
    win.ctrl.message.connect(msgs.append)
    out = os.path.join(_TMP, "desde_menu.xml")
    r = win.export_xml(out)
    assert r and os.path.exists(out) and any("DaVinci" in m for m in msgs), msgs
    print("✓ Archivo → «⇄ Llevar a DaVinci Resolve / Premiere (XML)…» lo guarda y explica cómo abrirlo")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
