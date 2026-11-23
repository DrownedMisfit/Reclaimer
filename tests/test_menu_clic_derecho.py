"""
🖱 PRUEBA del clic derecho en un clip de la línea de tiempo (20/11, aprobado por el usuario): de unas 30 opciones a la
vista a unas 12–16, sin perder ninguna.
  · todo lo que salía antes (por tipo de clip: video con su sonido, su sonido, audio suelto, imagen, texto, color
    sólido) sigue en el menú nuevo, a la vista o en «Más ▸»;
  · a la vista, como mucho 16 entradas por tipo, en el orden pedido (portapapeles · editar · velocidad y color ·
    memes, compuesto y nota · lo propio del tipo · IA · Más);
  · sin emojis de color en ningún texto (también en los submenús);
  · lo mismo está en el menú de arriba: Timeline → «Clip elegido ▸» repite el menú del clip elegido;
  · con varios clips elegidos, las mismas reglas.
El menú se ARMA sin abrirlo (build_clip_menu): la prueba no se cuelga.
Ejecutar:  .venv/Scripts/python.exe tests/test_menu_clic_derecho.py <carpeta_salida> [--volcar]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time


# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _vigilante(segundos: float = 420.0):
    """Si la prueba se cuelga (un diálogo o un menú de verdad), sale sola y libera el turno."""
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta (¿un menú o un diálogo esperando?)", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


# Emojis de color: pictogramas (U+1F000–1FAFF), símbolos y dingbats (U+2600–27BF: ✂ ✨ ❓ ♻ ❄ …, salvo las marcas de
# una tinta ✓ ✕ ✗), estrellas (U+2B00–2BFF), relojes y flechas dobles (⏱ ⏩ …), 〰 y el selector de emoji (U+FE0F).
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u2712\u2714\u2716\u2718-\u27BF\u2B00-\u2BFF\u231A\u231B"
                   "\u23E9-\u23FA\u3030\u303D\uFE0F]")
# Para COMPARAR nombres (antes con emoji, ahora sin él): se quita todo eso y también ✓ ✗.
COMPARA = re.compile(EMOJI.pattern[:-1] + "\u2713\u2715\u2717]")


def limpio(texto: str) -> str:
    """El nombre de una opción para comparar: sin emojis, sin atajo, sin datos que cambian (tiempos, «…» citados)."""
    t = texto.split("\t")[0].replace("&", "")
    t = COMPARA.sub("", t)
    t = re.sub(r"\([^)]*\d[^)]*\)", "", t)          # (00:01–00:04), (2 marcados)…
    t = re.sub(r"«[^»]*»", "«»", t)
    return re.sub(r"\s+", " ", t).strip()


def recorrer(menu, ruta=()):
    """[(ruta, texto, acción)] de todas las opciones (y submenús) de un menú, recursivo."""
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        out.append((ruta, a.text(), a))
        if a.menu() is not None:
            out += recorrer(a.menu(), ruta + (a.text(),))
    return out


def a_la_vista(menu):
    return [a for a in menu.actions() if not a.isSeparator()]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def preparar(app, out):
    """Un proyecto con un clip de cada tipo. Devuelve (ventana, {tipo: clip_id})."""
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    vid = os.path.join(out, "video.mp4")
    img = os.path.join(out, "imagen.png")
    mus = os.path.join(out, "musica.wav")
    for ruta, args in ((vid, ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12", "-f", "lavfi", "-i",
                              "sine=f=440:d=12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest"]),
                       (img, ["-f", "lavfi", "-i", "testsrc2=s=320x180", "-frames:v", "1"]),
                       (mus, ["-f", "lavfi", "-i", "sine=f=880:d=12"])):
        if not os.path.exists(ruta):
            subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y"] + args + [ruta], check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.8)
    ctrl = win.ctrl
    ctrl.project.fps = 30.0
    mv, mi, mm = ctrl.import_now([vid, img, mus])
    while ctrl.analyzing:
        pump(app, 0.1)
    P = ctrl.project
    v1 = [t for t in P.tracks if t.kind == TRACK_VIDEO][-1].id
    ctrl.insert_ranges([{"media_id": mv, "start": 0.0, "source_in": 0.0, "duration": 3.0},
                        {"media_id": mv, "start": 3.0, "source_in": 4.0, "duration": 3.0}], v1, "Video")
    ctrl.insert_ranges([{"media_id": mi, "start": 7.0, "source_in": 0.0, "duration": 3.0}], v1, "Imagen")
    ya = {t.id for t in P.tracks}
    ctrl.add_track(TRACK_AUDIO)
    a_m = next(t.id for t in P.tracks if t.id not in ya)
    ctrl.insert_ranges([{"media_id": mm, "start": 0.0, "source_in": 0.0, "duration": 10.0}], a_m, "Música")
    with ctrl.sin_abrir_editor():
        ctrl.add_text(1.0, 2.0, "un texto")
    ctrl.add_generator({"kind": "solid", "color": "#336699"}, 11.0, 2.0)
    pump(app, 0.3)
    vids = sorted((c for c in P.clips_on(v1) if P.media_of(c) and P.media_of(c).id == mv), key=lambda c: c.start)
    video = vids[1]
    sonido = next(o for o in ctrl.partners(P, video) if P.track(o.track_id).kind == TRACK_AUDIO)
    imagen = next(c for c in P.clips.values() if c.media_id == mi)
    imagen.zoom_kf = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5}, {"t": 1.0, "z": 1.2, "x": 0.5, "y": 0.5}]       # (con rombos: sale «Quitar los rombos»)
    texto = next(c for c in P.clips.values() if c.text is not None)
    musica = next(c for c in P.clips.values() if c.media_id == mm)
    solido = next(c for c in P.clips.values() if (getattr(P.media_of(c), "gen", None) or {}).get("kind") == "solid")
    return win, {"video": video.id, "sonido": sonido.id, "musica": musica.id, "imagen": imagen.id, "texto": texto.id,
                 "solido": solido.id}


def armar(win, cid):
    tl = win.timeline
    tl.set_selection([])
    c = win.ctrl.project.clips[cid]
    return tl.build_clip_menu(c, tl.mapToGlobal(QPoint(300, 200)))


# Lo que salía ANTES (20/11, antes de ordenarlo), por tipo de clip: nombres limpios de todas las opciones y submenús.
ANTES = {
    "video": [
        "100 %", "150 %", "200 %", "25 %", "400 %", "50 %", "75 %", "Acelerar", "Activar/desactivar clip",
        "Agregar a memes…", "Amarillo", "Aplastar", "Atributos del clip…", "Azul", "Barrido suave ←", "Barrido ←",
        "Blanco y negro", "Bloquear clip", "Buscar en el panel multimedia", "Buscar lo que se dice…",
        "Buscar material para lo que digo aquí (transcribe antes tu voz)", "Buscar momentos parecidos a este clip",
        "Cambiar duración…", "Cambiar velocidad…", "Cinemático", "Color de clip",
        "Congelar la imagen desde el cabezal", "Copiar", "Cortar", "Cortar en los cambios de escena",
        "Cortar y propagar", "Cortes claros (cambio de plano o de escena)", "Crear clip compuesto…", "Círculo",
        "Dar más impacto visual a este clip", "Deslizar ←", "Deslizar →", "Destello blanco",
        "Desvincular audio y video", "Disolver", "Disolver con grano", "Dividir en el cabezal",
        "Efectos según lo que digo…", "Efectos solo al personaje…", "Eliminar atributos…", "Eliminar seleccionados",
        "Eliminar silencios (y juntar lo de detrás)…", "Eliminar solo el audio", "Eliminar solo el video",
        "Eliminar y propagar", "Enseñar este personaje (silueta)…", "Entrar en cámara lenta",
        "Escalonar las 2: cada una entra por un lado distinto · con sombra", "Frenar", "Fundido a negro", "Gris",
        "IA", "Ideas para esto", "Insertar espacio", "Latigazo", "Lima", "Marrón", "Morado", "Naranja",
        "Normalizar volumen…", "PNGTuber con esta voz…", "Pegar", "Pegar atributos…", "Pegar e insertar", "Pixelado",
        "Póster", "Quitar el sonido de este video", "Rampa de velocidad", "Recortar sujeto / quitar el fondo…",
        "Rehacer el B-roll de esta parte", "Reloj", "Rosa", "Rápido → lento → rápido", "Salir de cámara lenta",
        "Seguimiento…", "Separar los diálogos del ruido de fondo", "Sin color",
        "Solo poner marcadores en cada cambio", "También cambios más suaves (menú de pausa, fundidos)",
        "Todas entran desde abajo · contorno y sombra", "Transformar imagen",
        "Usar como ejemplo de lo que busco (aprende con /)…", "Velocidad", "Verde", "Verde azulado", "Viento",
        "Volver al original", "Zoom", "¿Qué hace esto?", "◀ Hacia atrás", "⧉ Transición al inicio",
    ],
    "sonido": [
        "100 %", "150 %", "200 %", "25 %", "400 %", "50 %", "75 %", "Acelerar", "Activar/desactivar clip",
        "Agregar a memes…", "Amarillo", "Atributos del clip…", "Azul", "Blanco y negro", "Bloquear clip",
        "Buscar en el panel multimedia", "Buscar lo que se dice…",
        "Buscar material para lo que digo aquí (transcribe antes tu voz)", "Cambiar duración…", "Cambiar velocidad…",
        "Cinemático", "Color de clip", "Copiar", "Cortar", "Cortar en los cambios de escena", "Cortar y propagar",
        "Cortes claros (cambio de plano o de escena)", "Crear clip compuesto…", "Dar más impacto visual a este clip",
        "Desvincular audio y video", "Dividir en el cabezal", "Efectos según lo que digo…", "Eliminar atributos…",
        "Eliminar seleccionados", "Eliminar silencios (y juntar lo de detrás)…", "Eliminar solo el audio",
        "Eliminar solo el video", "Eliminar y propagar", "Entrar en cámara lenta",
        "Escalonar las 2: cada una entra por un lado distinto · con sombra", "Frenar", "Gris", "IA",
        "Ideas para esto", "Insertar espacio", "Lima", "Marrón", "Morado", "Naranja", "Normalizar volumen…",
        "PNGTuber con esta voz…", "Pegar", "Pegar atributos…", "Pegar e insertar", "Póster",
        "Quitar el sonido de este video", "Rampa de velocidad", "Rehacer el B-roll de esta parte", "Rosa",
        "Rápido → lento → rápido", "Salir de cámara lenta", "Separar los diálogos del ruido de fondo", "Sin color",
        "Solo poner marcadores en cada cambio", "También cambios más suaves (menú de pausa, fundidos)",
        "Todas entran desde abajo · contorno y sombra", "Transformar imagen", "Velocidad", "Verde", "Verde azulado",
        "Volver al original", "¿Qué hace esto?", "◀ Hacia atrás",
    ],
    "musica": [
        "100 %", "150 %", "200 %", "25 %", "400 %", "50 %", "75 %", "Acelerar", "Activar/desactivar clip",
        "Agregar a memes…", "Amarillo", "Atributos del clip…", "Azul", "Bloquear clip",
        "Buscar en el panel multimedia", "Buscar lo que se dice…",
        "Buscar material para lo que digo aquí (transcribe antes tu voz)", "Cambiar duración…", "Cambiar velocidad…",
        "Color de clip", "Copiar", "Cortar", "Cortar y propagar", "Crear clip compuesto…", "Dividir en el cabezal",
        "Eliminar atributos…", "Eliminar seleccionados", "Eliminar silencios (y juntar lo de detrás)…",
        "Eliminar y propagar", "Entrar en cámara lenta", "Frenar", "Gris", "IA", "Insertar espacio", "Lima",
        "Marrón", "Morado", "Naranja", "Normalizar volumen…", "Nota…", "PNGTuber con esta voz…", "Pegar",
        "Pegar atributos…", "Pegar e insertar", "Rampa de velocidad", "Rehacer el B-roll de esta parte", "Rosa",
        "Rápido → lento → rápido", "Salir de cámara lenta", "Separar los diálogos del ruido de fondo", "Sin color",
        "Velocidad", "Verde", "Verde azulado", "¿Qué hace esto?", "◀ Hacia atrás",
    ],
    "imagen": [
        "Acercarse", "Activar/desactivar clip", "Agregar a memes…", "Amarillo", "Animación", "Animar imagen…",
        "Aparece suave · con sombra", "Atributos del clip…", "Azul", "Blanco y negro", "Bloquear clip",
        "Buscar en el panel multimedia", "Buscar lo que se dice…",
        "Buscar material para lo que digo aquí (transcribe antes tu voz)", "Buscar momentos parecidos a este clip",
        "Cambiar duración…", "Cinemático", "Color de clip", "Copiar", "Cortar", "Cortar y propagar",
        "Costado derecho", "Costado izquierdo", "Crear clip compuesto…", "Dar más impacto visual a este clip",
        "Disparar", "Dividir en el cabezal", "Efectos según lo que digo…", "Eliminar atributos…",
        "Eliminar seleccionados", "Eliminar y propagar", "Encima y centrada · entra desde la derecha · con sombra",
        "Encima, fondo desenfocado y sombra", "Entra desde abajo · contorno blanco y sombra",
        "Esquina superior derecha", "Estilo de imagen", "Gris", "IA", "Ideas para esto", "Insertar espacio", "Lima",
        "Marrón", "Morado", "Morir", "Naranja", "Nota…", "Pantalla completa", "Pegar", "Pegar atributos…",
        "Pegar e insertar", "Póster", "Quieta", "Quitar los rombos (zoom y posición)", "Recibir un golpe",
        "Rehacer el B-roll de esta parte", "Rosa", "Según lo que digo", "Sin animación", "Sin color",
        "Transformar imagen", "Usar como ejemplo de lo que busco (aprende con /)…", "Verde", "Verde azulado",
        "Volver al original", "¿Qué hace esto?", "↘ En una esquina · entra desde la derecha · con sombra",
        "⇆ Cruzar la pantalla", "⇤ Salir deslizando", "⇥ Entrar deslizando", "⏱ Ajustar a la frase", "⤴ Saltar",
        "〰 Temblar",
    ],
    "texto": [
        "Activar/desactivar clip", "Amarillo", "Atributos del clip…", "Azul", "Bloquear clip",
        "Buscar en el panel multimedia", "Buscar material para lo que digo aquí (transcribe antes tu voz)",
        "Buscar momentos parecidos a este clip", "Cambiar duración…", "Color de clip", "Copiar", "Cortar",
        "Cortar y propagar", "Crear clip compuesto…", "Dividir en el cabezal", "Eliminar atributos…",
        "Eliminar seleccionados", "Eliminar y propagar", "Gris", "IA", "Insertar espacio", "Lima", "Marrón",
        "Morado", "Naranja", "Nota…", "Pegar", "Pegar a un objeto seguido…", "Pegar atributos…", "Pegar e insertar",
        "Rehacer el B-roll de esta parte", "Rosa", "Sin color", "Usar como ejemplo de lo que busco (aprende con /)…",
        "Verde", "Verde azulado", "¿Qué hace esto?",
    ],
    "solido": [
        "Acercarse", "Activar/desactivar clip", "Agregar a memes…", "Amarillo", "Animación", "Animar imagen…",
        "Aparece suave · con sombra", "Atributos del clip…", "Azul", "Blanco y negro", "Bloquear clip",
        "Buscar en el panel multimedia", "Buscar lo que se dice…",
        "Buscar material para lo que digo aquí (transcribe antes tu voz)", "Buscar momentos parecidos a este clip",
        "Cambiar color…", "Cambiar duración…", "Cinemático", "Color de clip", "Copiar", "Cortar",
        "Cortar y propagar", "Costado derecho", "Costado izquierdo", "Crear clip compuesto…",
        "Dar más impacto visual a este clip", "Disparar", "Dividir en el cabezal", "Efectos según lo que digo…",
        "Eliminar atributos…", "Eliminar seleccionados", "Eliminar y propagar",
        "Encima y centrada · entra desde la derecha · con sombra", "Encima, fondo desenfocado y sombra",
        "Entra desde abajo · contorno blanco y sombra", "Esquina superior derecha", "Estilo de imagen", "Gris", "IA",
        "Ideas para esto", "Insertar espacio", "Lima", "Marrón", "Morado", "Morir", "Naranja", "Nota…",
        "Pantalla completa", "Pegar", "Pegar atributos…", "Pegar e insertar", "Póster", "Quieta", "Recibir un golpe",
        "Rehacer el B-roll de esta parte", "Rosa", "Según lo que digo", "Sin animación", "Sin color",
        "Transformar imagen", "Usar como ejemplo de lo que busco (aprende con /)…", "Verde", "Verde azulado",
        "Volver al original", "¿Qué hace esto?", "↘ En una esquina · entra desde la derecha · con sombra",
        "⇆ Cruzar la pantalla", "⇤ Salir deslizando", "⇥ Entrar deslizando", "⏱ Ajustar a la frase", "⤴ Saltar",
        "〰 Temblar",
    ],
}
# Opciones que cambiaron de nombre (antes → ahora).
RENOMBRADOS = {"Eliminar y propagar": "Eliminar y cerrar hueco"}
# A la vista, como mucho (el usuario pidió «unas 12»; con los 6 grupos pedidos salen 13–16).
MAX_A_LA_VISTA = 16


def main():
    _vigilante()
    out = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join("_pruebas_tmp", "menu_clic_derecho"))
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win, tipos = preparar(app, out)
    if "--volcar" in sys.argv or os.environ.get("VOLCAR_MENU"):
        vol = {}
        for tipo, cid in tipos.items():
            m = armar(win, cid)
            vol[tipo] = sorted({limpio(t) for _r, t, _a in recorrer(m)})
            print(f"  {tipo}: {len(a_la_vista(m))} a la vista, {len(vol[tipo])} en total")
        print("VOLCADO " + json.dumps(vol, ensure_ascii=False), flush=True)
        os._exit(0)

    P = win.ctrl.project
    tl = win.timeline

    def nombres(menu):
        return {RENOMBRADOS.get(n, n) for n in (limpio(tx) for _r, tx, _a in recorrer(menu))}

    def revisar(menu, tipo, antes=None):
        vista = a_la_vista(menu)
        textos = [a.text() for a in vista]
        assert len(vista) <= MAX_A_LA_VISTA, (tipo, len(vista), textos)
        assert [limpio(x) for x in textos[:3]] == ["Cortar", "Copiar", "Pegar"], (tipo, textos[:3])
        assert [limpio(x) for x in textos[3:7]] == ["Dividir en el cabezal", "Eliminar seleccionados",
                                                    "Eliminar y cerrar hueco", "Activar/desactivar clip"], textos[3:7]
        assert textos[:3] == ["Cortar\tCtrl+X", "Copiar\tCtrl+C", "Pegar\tCtrl+V"], textos[:3]
        assert textos[3] == "Dividir en el cabezal\tS" and textos[6] == "Activar/desactivar clip\tD", textos[3:7]
        assert textos[-2:] == ["IA", "Más"] and vista[-1].menu() is not None, (tipo, textos[-2:])
        assert "Color de clip" in textos, textos
        con_emoji = [(ruta, tx) for ruta, tx, _a in recorrer(menu) if EMOJI.search(tx)]
        assert not con_emoji, (tipo, "emojis de color", con_emoji)
        if antes is not None:
            faltan = sorted({RENOMBRADOS.get(limpio(x), limpio(x)) for x in antes} - nombres(menu))
            assert not faltan, (tipo, "ya no están", faltan)
        return textos

    vistos = {}
    for tipo, cid in tipos.items():
        m = armar(win, cid)
        textos = revisar(m, tipo, ANTES[tipo])
        vistos[tipo] = len(textos)
        mas = [a.text() for a in a_la_vista(a_la_vista(m)[-1].menu())]
        assert any(x.startswith("Bloquear clip") for x in mas) and any(x.startswith("Pegar e insertar") for x in mas), mas
        if tipo == "musica":     # (el ritmo cambia según haya terminado de escucharlo: alguna de sus opciones)
            assert any(re.search("ritmo", n) for n in nombres(m)), sorted(nombres(m))
        propias = {"sonido": ["Eliminar silencios (y juntar lo de detrás)…\tCtrl+Mayús+Supr", "Normalizar volumen…"],
                   "musica": ["Eliminar silencios (y juntar lo de detrás)…\tCtrl+Mayús+Supr", "Normalizar volumen…"],
                   "imagen": ["Transformar imagen", "Efectos según lo que digo…"],
                   "solido": ["Cambiar color…", "Transformar imagen", "Efectos según lo que digo…"],
                   "video": ["Seguimiento…", "Cortar en los cambios de escena"], "texto": []}[tipo]
        for x in propias:
            assert x in textos, (tipo, x, textos)
        if tipo in ("video", "sonido", "musica"):
            vel = next(a.menu() for a in a_la_vista(m) if a.text() == "Velocidad")
            assert a_la_vista(vel)[0].text() == "Cambiar velocidad…", [a.text() for a in a_la_vista(vel)]
    print("✓ por tipo de clip, a la vista: " + ", ".join(f"{k} {v}" for k, v in vistos.items()) +
          f" (máximo {MAX_A_LA_VISTA}; antes de 22 a 36); todo lo de antes sigue (a la vista o en «Más ▸»); sin emojis")

    # con varios clips elegidos (video + su sonido + imagen + texto): las mismas reglas
    varios = win.ctrl.linked_ids([tipos["video"], tipos["imagen"], tipos["texto"]])
    tl.set_selection(varios)
    m = tl.build_clip_menu(P.clips[tipos["imagen"]], tl.mapToGlobal(QPoint(300, 200)))
    revisar(m, "varios")
    assert set(tl.selected) == set(varios), "el clic derecho en uno ya elegido no cambia la selección"
    lk = next(a for _r, tx, a in recorrer(m) if tx.startswith("Bloquear clip"))
    lk.trigger()
    pump(app, 0.05)
    assert all(P.clips[i].locked for i in varios), "«Bloquear clip» (en «Más ▸») bloquea todos los elegidos"
    win.ctrl.undo_stack.undo()
    pump(app, 0.05)
    print("✓ con varios clips elegidos, las mismas reglas; «Bloquear clip» desde «Más ▸» los bloquea todos")

    # arriba: Timeline → «Clip elegido ▸» repite el menú del clip elegido (nada vive solo en el clic derecho)
    tm = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Timeline")
    sub = next(a.menu() for a in tm.actions() if a.text() == "Clip elegido")
    tl.set_selection([])
    sub.aboutToShow.emit()
    assert [a.text() for a in sub.actions()] == ["Elige antes un clip en la línea de tiempo"]
    for tipo, cid in tipos.items():
        del_clic = nombres(armar(win, cid))        # (pulsas el clip y luego abres el menú de arriba)
        sub.aboutToShow.emit()
        de_arriba = nombres(sub)
        assert de_arriba == del_clic, (tipo, sorted(de_arriba ^ del_clic))
    tl.set_selection([tipos["video"]])
    sub.aboutToShow.emit()
    on = next(a for a in sub.actions() if a.text().startswith("Activar/desactivar clip"))
    on.trigger()
    pump(app, 0.05)
    assert not P.clips[tipos["video"]].enabled, "la opción de arriba hace lo mismo que la del clic derecho"
    win.ctrl.undo_stack.undo()
    print("✓ Timeline → «Clip elegido ▸» tiene las mismas opciones que el clic derecho (y funcionan)")

    win.ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
