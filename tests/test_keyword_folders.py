"""
Prueba de «carpetas por palabra clave» (sin ventanas):
  · norm (tildes, mayúsculas, signos) y alias con coma / punto y coma / « | »;
  · list_folders: orden alfabético, conteo recursivo, ignora audio, «_x», «.x» y archivos sueltos;
  · match: exacto, alias y plural simple; create_folder no duplica y limpia el nombre;
  · add_files: copia, renombra «(2)», copia el contenido de una carpeta soltada, no copia lo que ya está dentro;
  · find_mentions con extra_terms detecta una palabra que antes no detectaba, sin duplicar las conocidas;
  · place_clip_at con una imagen: clip de esa duración en una pista de video por encima de la principal,
    sin volumen, y un solo Deshacer lo quita.
Sin ventanas visibles. Ejecutar:  .venv/Scripts/python.exe tests/test_keyword_folders.py _pruebas_tmp/test_keyword_folders
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no imprime ✓ por defecto

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai.mentions import find_mentions  # noqa: E402
from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def _escribir(ruta: str, texto: str = "x"):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)


def _sin_ext(ruta: str) -> str:
    return os.path.basename(ruta)


def prueba_norm_alias():
    check(KF.norm("  Fortnité  ¡Hola!  ") == "fortnite hola", "norm: quita tildes, signos y espacios sobrantes")
    check(KF.norm("ÑANDÚ Pingüino") == "nandu pinguino", "norm: minúsculas y tildes en mayúsculas")
    check(KF.folder_keys("Fortnite, fortnait") == ["fortnite", "fortnait"], "alias separados por coma")
    check(KF.folder_keys("Fortnite; Fortnait | fortnite") == ["fortnite", "fortnait"],
          "alias con «;» y « | », sin repetidos")
    check(KF.folder_keys(" ,, ") == [], "alias vacíos se descartan")


def prueba_listar(root: str):
    os.makedirs(root, exist_ok=True)
    base = os.path.join(root, "Fortnite, fortnait")
    _escribir(os.path.join(base, "a.mp4"))
    _escribir(os.path.join(base, "b.png"))
    _escribir(os.path.join(base, "c.mp3"), "audio")               # audio: se ignora
    _escribir(os.path.join(base, "sub", "d.mov"))                   # recursivo
    _escribir(os.path.join(root, "minecraft", "e.jpg"))
    _escribir(os.path.join(root, "_oculta", "f.mp4"))               # empieza por «_»: se ignora
    _escribir(os.path.join(root, ".tmp", "g.mp4"))                  # empieza por «.»: se ignora
    os.makedirs(os.path.join(root, "Zeta"), exist_ok=True)          # carpeta vacía: cuenta 0
    _escribir(os.path.join(root, "suelto.mp4"))                     # archivo suelto: no es carpeta
    ahora = time.time()
    os.utime(os.path.join(base, "a.mp4"), (ahora - 100, ahora - 100))
    os.utime(os.path.join(base, "b.png"), (ahora - 50, ahora - 50))
    os.utime(os.path.join(base, "sub", "d.mov"), (ahora - 10, ahora - 10))

    fs = KF.list_folders(root)
    check([f["label"] for f in fs] == ["Fortnite", "minecraft", "Zeta"],
          f"list_folders: orden alfabético por label {[f['label'] for f in fs]}")
    por = {f["label"]: f for f in fs}
    check(por["Fortnite"]["count"] == 3, "list_folders: cuenta vídeos e imágenes también en subcarpetas (3)")
    check(por["minecraft"]["count"] == 1 and por["Zeta"]["count"] == 0, "list_folders: conteos de las demás")
    check(_sin_ext(por["Fortnite"]["files"][0]) == "d.mov", "list_folders: el archivo más reciente va primero")
    check(not any(f.endswith(".mp3") for f in por["Fortnite"]["files"]), "list_folders: no cuenta el audio")
    check(por["Fortnite"]["keys"] == ["fortnite", "fortnait"], "list_folders: keys de los alias")
    check(KF.list_folders(os.path.join(root, "no_existe")) == [], "list_folders: carpeta inexistente → []")
    return fs


def prueba_match_y_crear(root: str, fs: list):
    m = KF.match("FORTNITES", fs)
    check(m is not None and m["label"] == "Fortnite", "match: plural simple («FORTNITES» → Fortnite)")
    check(KF.match("fortnait", fs)["label"] == "Fortnite", "match: alias")
    check(KF.match("Minecraft!", fs)["label"] == "minecraft", "match: ignora mayúsculas y signos")
    check(KF.match("Zetas", fs)["label"] == "Zeta", "match: plural de «Zeta»")
    check(KF.match("Valorant", fs) is None, "match: sin coincidencia → None")

    n_antes = len(os.listdir(root))
    ruta = KF.create_folder(root, "Fortnite")
    check(ruta == por_ruta(fs, "Fortnite") and len(os.listdir(root)) == n_antes,
          "create_folder: reutiliza la carpeta existente y no crea otra")
    nueva = KF.create_folder(root, "Valorant")
    check(os.path.isdir(nueva) and os.path.basename(nueva) == "Valorant", "create_folder: crea la carpeta nueva")
    mario = KF.create_folder(root, "Mario: <kart>?")
    check(os.path.basename(mario) == "Mario kart", "create_folder: limpia caracteres no válidos en Windows")
    check(KF.safe_name("Fin. ") == "Fin" and KF.safe_name("...") == "Sin nombre",
          "safe_name: quita puntos finales y usa «Sin nombre» si queda vacío")
    return nueva


def por_ruta(fs: list, label: str) -> str:
    return next(f["path"] for f in fs if f["label"] == label)


def prueba_copiar(root: str, destino: str):
    origen = os.path.join(root, "..", "origen_pruebas")
    origen = os.path.abspath(origen)
    if os.path.isdir(origen):
        shutil.rmtree(origen)
    _escribir(os.path.join(origen, "clip.mp4"), "A")
    _escribir(os.path.join(origen, "sub", "otro.png"), "P")
    _escribir(os.path.join(origen, "nota.txt"), "no")
    _escribir(os.path.join(origen, "musica.mp3"), "audio")
    otro = os.path.join(origen, "..", "origen_pruebas_2", "clip.mp4")
    _escribir(otro, "B")
    otro = os.path.abspath(otro)

    r = KF.add_files(destino, [os.path.join(origen, "clip.mp4")])
    check(r == [os.path.join(destino, "clip.mp4")] and _leer(os.path.join(destino, "clip.mp4")) == "A",
          "add_files: copia un video a la carpeta")
    r = KF.add_files(destino, [otro])
    check(_sin_ext(r[0]) == "clip (2).mp4" and _leer(os.path.join(destino, "clip (2).mp4")) == "B"
          and _leer(os.path.join(destino, "clip.mp4")) == "A",
          "add_files: si el nombre existe usa «nombre (2)» sin pisar el original")
    r = KF.add_files(destino, [origen])
    nombres = sorted(_sin_ext(x) for x in r)
    check(nombres == ["clip (3).mp4", "otro.png"], f"add_files: copia el contenido de una carpeta soltada {nombres}")
    check(os.path.isfile(os.path.join(destino, "otro.png")), "add_files: lo de subcarpetas se copia plano")
    check(not os.path.exists(os.path.join(destino, "nota.txt")) and not os.path.exists(
        os.path.join(destino, "musica.mp3")), "add_files: ignora texto y audio")
    antes = sorted(os.listdir(destino))
    r = KF.add_files(destino, [os.path.join(destino, "clip.mp4")])
    check(r == [os.path.join(destino, "clip.mp4")] and sorted(os.listdir(destino)) == antes,
          "add_files: un archivo que ya está dentro no se copia (sí se cuenta)")
    r = KF.add_files(destino, [destino])
    check(len(r) == len(antes) and sorted(os.listdir(destino)) == antes,
          "add_files: carpeta destino soltada sobre sí misma no duplica nada")
    check(KF.add_files(destino, [os.path.join(origen, "nota.txt")]) == [],
          "add_files: solo texto → no devuelve nada")


def _leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def _palabras(texto: str) -> list:
    return [[i * 0.5, i * 0.5 + 0.4, t, 0.9] for i, t in enumerate(texto.split())]


def prueba_menciones():
    texto = ("Hoy vamos a jugar con zombis en la noche y los zombis atacan. "
             "Luego Fortnite y Fortnite otra vez.")
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(texto)}}
    antes = find_mentions(p)
    check(not any(m["term"].lower() == "zombis" for m in antes), "find_mentions sin extra: no detecta «zombis»")
    ms = find_mentions(p, ["Zombis"])
    z = [m for m in ms if m["term"].lower() == "zombis"]
    check(len(z) == 1 and z[0]["count"] == 2 and z[0]["known"] is True,
          "find_mentions con extra_terms: detecta «zombis» (2 veces, como conocido)")
    fn = [m for m in find_mentions(p, ["Fortnite"]) if m["term"] == "Fortnite"]
    check(len(fn) == 1 and fn[0]["count"] == 2, "find_mentions: un término extra ya conocido no se duplica")
    check(find_mentions(p, None) == antes, "find_mentions(extra_terms=None) igual que antes")


def _imagen(ruta: str):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    img = QImage(64, 36, QImage.Format.Format_RGB32)
    img.fill(0xFF336699)
    img.save(ruta, "PNG")


def prueba_poner_imagen(app):
    png = os.path.join(_TMP, "foto.png")
    _imagen(png)
    p = Project.new()
    main = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    p.media["img"] = MediaItem(id="img", path=png, kind=KIND_IMAGE, name="foto.png", duration=0.0,
                               width=64, height=36, probed=True)
    ctrl = ProjectController()
    ctrl.project = p
    antes = len(ctrl.project.clips)
    pila = ctrl.undo_stack.count()
    ids = ctrl.place_clip_at("img", [2.0], [3.0], 0.0)
    check(len(ids) == 1, "place_clip_at con imagen: crea un clip")
    c = ctrl.project.clips[ids[0]]
    check(abs(c.duration - 3.0) < 1e-6 and c.source_in == 0.0 and c.start == 2.0,
          "place_clip_at imagen: empieza en el momento pedido, dura lo pedido, source_in 0")
    check(c.volume == 0.0, "place_clip_at imagen: sin volumen")
    pista = ctrl.project.track_index(c.track_id)
    check(ctrl.project.track_index(main.id) > pista and next(
        t for t in ctrl.project.tracks if t.id == c.track_id).kind == TRACK_VIDEO,
          "place_clip_at imagen: en una pista de video por encima de la principal")
    check(ctrl.undo_stack.count() == pila + 1, "place_clip_at imagen: un solo paso de deshacer")
    ctrl.undo_stack.undo()
    check(len(ctrl.project.clips) == antes and ids[0] not in ctrl.project.clips,
          "place_clip_at imagen: Deshacer lo quita entero")


def main():
    if len(sys.argv) > 1:
        trabajo = os.path.abspath(sys.argv[1])
    else:
        trabajo = os.path.join(_TMPROOT, "test_keyword_folders")
    shutil.rmtree(trabajo, ignore_errors=True)
    os.makedirs(trabajo, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])

    prueba_norm_alias()
    root = os.path.join(trabajo, "clips")
    fs = prueba_listar(root)
    destino = prueba_match_y_crear(root, fs)
    prueba_copiar(root, destino)
    prueba_menciones()
    prueba_poner_imagen(app)
    shutil.rmtree(trabajo, ignore_errors=True)
    print("TODO OK")


if __name__ == "__main__":
    main()
