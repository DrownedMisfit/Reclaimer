"""
Prueba de «🎬 Arma tu video» (paso 3 de «Edita desde tu voz»: editoria/ai/armar_video.py + ui/armar_video.py), SIN
internet y sin modelos: una narración fabricada con su transcripción, clips locales de prueba (videos de FFmpeg), CLIP
falso y la fuente de internet SIMULADA. Comprueba:
  · la narración queda cubierta de principio a fin, sin huecos (solo en lo que estaba vacío);
  · ninguna escena repetida (tampoco desde otro archivo: una copia de un clip en la carpeta de relleno, con huella);
  · el orden de prioridad: el momento exacto (lo que describe con CLIP y lo que cita), sus clips por palabra clave,
    internet (solo donde no hay nada en casa) y la carpeta de relleno (con emoji y tildes en la ruta);
  · respeta el clip que el usuario puso a mano;
  · armado en cadena (dos trozos) = UN solo Ctrl+Z;
  · clic derecho → «Cambiar»: alternativas ya preparadas, un clic cambia, un Ctrl+Z;
  · si el usuario edita un tramo mientras se arma, ese tramo se salta y se avisa;
  · «Seguir armando»: el estado se guarda y se lee.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_armar_video.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading


def _aislar_datos():
    import atexit
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_armar_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
    os.environ["USERPROFILE"] = tmp
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import socket  # noqa: E402
import urllib.request  # noqa: E402

import numpy as np  # noqa: E402


def _sin_internet(*_a, **_k):
    print("FALLO: la prueba intentó conectarse a internet")
    os._exit(1)


urllib.request.urlopen = _sin_internet           # 🔒 sin red: cualquier intento falla la prueba
socket.create_connection = _sin_internet

from _material_frases_comun import ImagenFalsa, TextoFalso, check, esperar  # noqa: E402

FRASES = [(0.5, "En Elden Ring los dragones vuelan sobre el castillo."),
          (6.0, "Como dice el tráiler la noche será larga y oscura."),
          (12.0, "En Halo el jefe maestro pelea contra todos."),
          (18.0, "Luego los carros explotan en la ciudad."),
          (24.0, "Aquí puse yo mi propio clip a mano."),
          (30.0, "Gracias por ver y hasta la próxima.")]
MANUAL = (23.5, 6.3)            # el clip puesto a mano: de 23,5 a 29,8 s
FIN = 36.0


def _video(ff, ruta, fuente, dur):
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", fuente, "-t", str(dur), "-r", "30",
                    "-pix_fmt", "yuv420p", "-vf", "scale=320:180", ruta], check=True)


def fabricar(out):
    from editoria.core import media as MT
    ff = MT.ffmpeg()
    clips = os.path.join(out, "Mis clips")
    relleno = os.path.join(out, "relleno 🎮 cañón")
    bajado = os.path.join(out, "descargas")
    for d in (clips, relleno, bajado):
        os.makedirs(d, exist_ok=True)
    r = {"cielo": os.path.join(clips, "cielo.mp4"), "trailer": os.path.join(clips, "trailer.mp4"),
         "halo": os.path.join(clips, "Halo partida.mp4"), "manual": os.path.join(clips, "manual.mp4"),
         "fondo1": os.path.join(relleno, "fondo1.mp4"), "copia": os.path.join(relleno, "fondo_copia.mp4"),
         "bajado": os.path.join(bajado, "carros [abc] 10-20 s.mp4"),
         "voz": os.path.join(out, "narración.wav")}
    _video(ff, r["cielo"], "testsrc2=s=320x180:r=30", 20)
    _video(ff, r["trailer"], "mandelbrot=s=320x180:r=30", 20)
    _video(ff, r["halo"], "life=s=320x180:r=30:seed=1:mold=10", 30)
    _video(ff, r["manual"], "cellauto=s=320x180:r=30:rule=110", MANUAL[1])
    _video(ff, r["fondo1"], "life=s=320x180:r=30:seed=77:mold=25:ratio=0.3", 12)
    _video(ff, r["bajado"], "testsrc=s=320x180:r=30", 9.5)
    # la MISMA escena que «cielo» (recomprimida, otro nombre): la huella no debe dejar que se repita
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", r["cielo"], "-c:v", "libx264", "-crf", "30",
                    r["copia"]], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={FIN}",
                    r["voz"]], check=True)
    return r, relleno


def palabras():
    out = []
    for t0, texto in FRASES:
        for i, w in enumerate(texto.split()):
            out.append([round(t0 + i * 0.35, 2), round(t0 + i * 0.35 + 0.3, 2), w, 1.0])
    return out


class FuentesSimuladas:
    """Como armar_video.Fuentes, sin red ni modelos: CLIP falso y un «internet» que devuelve un archivo local."""

    def __init__(self, rutas):
        from editoria.ai import armar_video as A
        self._base = A.Fuentes(internet=True, enc_texto=TextoFalso(), enc_imagen=ImagenFalsa())
        self.rutas = rutas
        self.pedidas: list[str] = []
        self.fallos, self.avisos, self.bajado = [], [], 0

    def vector_texto(self, textos):
        return self._base.vector_texto(textos)

    def encoders(self):
        return self._base.encoders()

    def vectores(self, medio):
        """«cielo» enseña el cielo a los 8 s (eje 1); todo lo demás, nada que ver con ninguna frase (eje 3)."""
        t = np.arange(0.5, max(1.0, float(medio.get("dur") or 1.0)), 1.0, dtype=np.float32)
        v = np.zeros((len(t), 4), np.float32)
        v[:, 3] = 1.0
        if os.path.basename(medio["ruta"]) == "cielo.mp4":
            k = int(np.argmin(abs(t - 8.0)))
            v[k] = (0.0, 1.0, 0.0, 0.0)
        return t, v

    def disco_libre(self, carpeta=None):
        return 100.0

    def hay_internet(self):
        return True

    def privada(self):
        return True

    def internet(self, pieza, cancelado=None, usados_vecs=(), alto=1080):
        self.pedidas.append(pieza["frase"])
        if "carros" in pieza["frase"]:
            return [{"ruta": self.rutas["bajado"], "tipo": "video", "source_in": 2.0, "dur_archivo": 0.0,
                     "motivo": "De internet (oficial): «prueba»"}]
        return []

    def duracion(self, ruta):
        return self._base.duracion(ruta)


def proyecto(app, r):
    from editoria.core import huella_plano as HP
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    ctrl = ProjectController()
    ctrl.project.width, ctrl.project.height = 640, 360
    ids = ctrl.import_now([r["voz"], r["cielo"], r["trailer"], r["halo"], r["manual"]], quiet=True)
    esperar(app, ctrl)
    nid, cielo, trailer, halo, manual = ids
    p = ctrl.project
    p.transcripts[nid] = {"words": palabras()}
    # el tráiler dice (en su propia voz) lo que la narración cita
    p.transcripts[trailer] = {"words": [[4.0, 4.3, "Y", 1.0], [5.0, 5.3, "la", 1.0], [5.4, 5.7, "noche", 1.0],
                                        [5.8, 6.1, "será", 1.0], [6.2, 6.5, "larga", 1.0], [6.6, 6.9, "y", 1.0],
                                        [7.0, 7.3, "oscura", 1.0]]}
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([nid], a1.id, 0.0)
    ctrl.add_media([manual], v1.id, MANUAL[0])
    for ruta in (r["cielo"], r["trailer"], r["halo"], r["manual"], r["fondo1"], r["copia"], r["bajado"]):
        HP.calcular(ruta, 0.0)          # (las huellas, como si ya se hubieran analizado)
    return ctrl, v1, manual


def cubierto(p, a, b) -> list:
    """Los huecos (sin nada visible en pistas de video) dentro de [a, b]."""
    from editoria.core.model import TRACK_VIDEO
    tramos = sorted((c.start, c.end) for c in p.clips.values()
                    if c.enabled and p.track(c.track_id).kind == TRACK_VIDEO and c.text is None)
    huecos, t = [], a
    for x, y in tramos:
        if x > t + 0.05:
            huecos.append((t, min(x, b)))
        t = max(t, y)
        if t >= b:
            break
    if t < b - 0.05:
        huecos.append((t, b))
    return [h for h in huecos if h[1] - h[0] > 0.05]


def sin_repetir(p, nota) -> list:
    """Pares de clips que enseñan lo mismo: mismo archivo con tramos que se pisan, u otro archivo (huella)."""
    from editoria.core import repetidos
    nuestros = {c.id for c in p.clips.values() if c.note == nota}
    malos = []
    cl = [c for c in p.clips.values() if c.note == nota or c.id in nuestros]
    for i, a in enumerate(cl):
        for b in cl[i + 1:]:
            if a.media_id == b.media_id and min(a.source_in + a.src_len, b.source_in + b.src_len) - \
                    max(a.source_in, b.source_in) > 0.05:
                malos.append((a.id, b.id))
    mapa = repetidos.mapa(p)
    malos += [(cid, rep.otro) for cid, reps in mapa.items() for rep in reps if cid in nuestros or rep.otro in nuestros]
    return malos


def main():
    t = threading.Timer(400.0, lambda: (print("FALLO: la prueba tardó más de 400 s"), os._exit(1)))
    t.daemon = True
    t.start()
    from PySide6.QtWidgets import QApplication, QMenu
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import armar_video as A
    from editoria.ui import armar_video as UA
    out = os.path.join(TMP, "armar")
    r, relleno = fabricar(out)
    ctrl, v1, manual_mid = proyecto(app, r)
    p = ctrl.project
    man = next(c for c in p.clips.values() if c.media_id == manual_mid)
    antes_manual = (man.start, man.duration, man.source_in, man.track_id)
    fu = FuentesSimuladas(r)
    ajustes = {"carpeta_relleno": relleno, "umbral_exacto": 0.5}
    pasos0 = ctrl.undo_stack.index()

    # ---- armado EN CADENA: dos trozos (como si la transcripción siguiera llegando), una sola sesión
    ses = A.Sesion(ctrl)
    r1 = A.armar(ctrl, 0.0, 15.0, fu, ajustes=ajustes, sesion=ses)
    check(r1["puestos"] and not cubierto(p, 0.0, 15.0), f"primer trozo (0–15 s) cubierto ({cubierto(p, 0.0, 15.0)})")
    check(cubierto(p, 15.0, FIN), "lo de después aún no (en cadena: se llena desde el principio)")
    r2 = A.armar(ctrl, 15.0, None, fu, ajustes=ajustes, sesion=ses)
    check(not cubierto(p, 0.0, FIN), f"narración cubierta de principio a fin, sin huecos ({cubierto(p, 0.0, FIN)})")
    check(ctrl.undo_stack.index() == pasos0 + 1, f"los dos trozos = UN solo paso de Ctrl+Z "
          f"({ctrl.undo_stack.index() - pasos0} pasos)")

    # ---- el clip puesto a mano, intacto y sin nada encima
    man = p.clips.get(man.id)
    check(man is not None and (man.start, man.duration, man.source_in, man.track_id) == antes_manual,
          "el clip que puso el usuario a mano sigue igual")
    nuestros = [c for c in p.clips.values() if c.note == A.NOTA]
    check(not any(c.start < MANUAL[0] + MANUAL[1] - 0.01 and c.end > MANUAL[0] + 0.01 for c in nuestros),
          "y no se le pone nada encima: solo se rellena lo que falta")
    check(all(c.volume == 0.0 for c in nuestros), "todo lo puesto va mudo (B-roll)")

    # ---- prioridad
    niveles = sorted([(pz["t0"], pz["nivel"]) for pl in (r1["plan"], r2["plan"]) for pz in pl["piezas"]])
    por_t = {round(t0): n for t0, n in niveles}
    check(por_t.get(0) == "exacto", f"«los dragones vuelan» → el momento exacto que describe (CLIP) ({niveles})")
    check(por_t.get(6) == "exacto", "«la noche será larga y oscura» → lo que cita (la voz del tráiler)")
    check(por_t.get(12) == "mis_clips" and por_t.get(15) == "mis_clips", "«En Halo…» → sus clips por palabra clave")
    check(por_t.get(18) == "internet", "«los carros explotan» (nada en casa) → internet")
    check(niveles[-1][1] == "relleno", "«Gracias por ver» → la carpeta de relleno (ruta con emoji y tildes)")
    check(fu.pedidas == ["Luego los carros explotan en la ciudad."],
          f"internet solo donde no había nada en casa ({fu.pedidas})")
    porpieza = {c.start: c for c in nuestros}
    c_cielo = porpieza.get(0.0)
    check(c_cielo is not None and p.media[c_cielo.media_id].name == "cielo.mp4" and 5.0 <= c_cielo.source_in <= 8.0,
          f"el trozo de «cielo» empieza cerca del momento que se parece ({c_cielo and c_cielo.source_in})")
    c_cita = porpieza.get(6.0)
    check(c_cita is not None and p.media[c_cita.media_id].name == "trailer.mp4" and abs(c_cita.source_in - 4.8) < 0.6,
          "la cita empieza donde el tráiler lo dice")

    # ---- sin repetir (ni el mismo tramo ni la misma escena desde otro archivo)
    malos = sin_repetir(p, A.NOTA)
    check(not malos, f"ninguna escena repetida ({malos})")
    copia = [c for c in nuestros if os.path.basename(p.media[c.media_id].path) == "fondo_copia.mp4"]
    check(all(c.source_in + c.src_len <= 3.6 or c.source_in >= 14.4 for c in copia),
          "la copia de «cielo» de la carpeta de relleno nunca enseña lo que ya sale de «cielo»")

    # ---- «Cambiar»: alternativas ya preparadas, un clic, un Ctrl+Z
    con_alts = [c for c in nuestros if len(A.alternativas_de(c.id)) >= 2]
    check(con_alts, f"cada momento guarda 2–3 alternativas ({[len(A.alternativas_de(c.id)) for c in nuestros]})")
    c = con_alts[0]
    menu = QMenu()
    sub = UA.poner_en_menu(menu, ctrl, c.id)
    check(sub is not None and len(sub.actions()) >= 2 and sub.title() == "Cambiar",
          f"clic derecho → «Cambiar» con las alternativas ({[a.text() for a in sub.actions()] if sub else None})")
    viejo = (c.media_id, c.source_in)
    pasos = ctrl.undo_stack.index()
    sub.actions()[0].trigger()                      # (un clic)
    c2 = p.clips[c.id]
    check((c2.media_id, c2.source_in) != viejo and ctrl.undo_stack.index() == pasos + 1,
          "un clic cambia el material (mismo sitio y duración), en un Ctrl+Z")
    check(not sin_repetir(p, A.NOTA), "lo cambiado tampoco repite nada")
    ctrl.undo_stack.undo()
    check((p.clips[c.id].media_id, p.clips[c.id].source_in) == viejo, "Ctrl+Z devuelve el material de antes")

    # ---- «Seguir armando»: el estado se guarda y se lee
    A.guardar_estado(ctrl, 0.0, None, 15.0, ajustes)
    d = A.pendiente(ctrl)
    check(d is not None and d["hecho_hasta"] == 15.0 and d["ajustes"]["carpeta_relleno"] == relleno,
          "al cerrar a medias queda guardado dónde iba (para «Seguir armando»)")
    A.borrar_estado(ctrl)
    check(A.pendiente(ctrl) is None, "al terminar ya no hay nada que seguir")

    # ---- todo el armado se quita con UN Ctrl+Z (y vuelve con rehacer)
    ctrl.undo_stack.undo()
    check(not [c for c in p.clips.values() if c.note == A.NOTA] and man.id in p.clips,
          "un Ctrl+Z quita todo el armado (lo tuyo se queda)")
    ctrl.undo_stack.redo()
    check(len([c for c in p.clips.values() if c.note == A.NOTA]) == len(nuestros), "rehacer lo devuelve")
    ctrl.undo_stack.undo()

    # ---- editar mientras se arma: ese tramo se salta y se avisa
    fu2 = FuentesSimuladas(r)
    inst = A.instantanea(ctrl, 0.0, None, ajustes)
    plan = A.planear(inst, fu2)
    ctrl.add_media([manual_mid], v1.id, 13.0)        # (el usuario pone algo mientras se buscaba)
    res = A.colocar(ctrl, plan, A.Sesion(ctrl))
    check(res["saltados"] >= 1 and any("cambiaste" in a for a in res["avisos"]),
          f"lo que tocaste mientras se armaba no se pisa: se salta y se avisa ({res['saltados']}, {res['avisos']})")
    puesto2 = [c for c in p.clips.values() if c.note == A.NOTA]
    check(puesto2 and not any(c.start < 13.0 + MANUAL[1] - 0.01 and c.end > 13.01 for c in puesto2),
          "nada encima de lo tuyo nuevo")

    # ---- el Armador del panel: en cadena, por la cola de análisis, sin bloquear; un solo Ctrl+Z
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    check(cubierto(p, 0.0, FIN) and not [c for c in p.clips.values() if c.note == A.NOTA], "(vuelta a empezar)")
    import time
    pasos = ctrl.undo_stack.index()
    arm = UA.Armador(ctrl, ajustes=ajustes, fuentes=FuentesSimuladas(r))
    fin, trozos = [], []
    arm.terminado.connect(fin.append)
    arm.trozo_puesto.connect(lambda a, b, n: trozos.append((a, b, n)))
    arm.empezar(0.0, None, en_cadena=True)          # (la transcripción «sigue llegando»)
    t0 = time.time()
    while not trozos and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.02)
    arm.transcripcion_terminada()
    while not fin and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.02)
    check(fin and not fin[0]["cancelado"] and len(trozos) >= 2,
          f"el Armador arma por trozos mientras llega la transcripción ({trozos})")
    check(not cubierto(p, 0.0, FIN) and ctrl.undo_stack.index() == pasos + 1,
          f"cubierto de principio a fin y en UN solo Ctrl+Z ({cubierto(p, 0.0, FIN)}, {ctrl.undo_stack.index() - pasos})")
    check(A.pendiente(ctrl) is None, "terminado: no queda «Seguir armando»")
    print("TODO BIEN")


if __name__ == "__main__":
    main()
