"""
🧭 PRUEBA PERMANENTE de la regla «lo que creas o pides, a la vista y listo para usar» (el usuario, 20/11: pulsó «T», se
creó el texto y no apareció dónde escribirlo: el Inspector estaba cerrado).

Con TODOS los paneles cerrados (el peor caso, el suyo), cada acción de la TABLA tiene que dejar a la vista el sitio donde
se usa y, si hay que escribir, con el foco (y el texto de fábrica seleccionado para escribir encima). Además:
  · lo que crea la IA (origin="ai"), el puente de Claude o un proceso automático (ctrl.sin_abrir_editor) NO abre nada ni
    quita el foco;
  · se recorren solos TODOS los botones de la barra de la línea de tiempo (y sus menús) y TODOS los menús: si alguien
    añade uno que no está en la tabla ni en CLASIFICADOS, la prueba falla y dice cuál (hay que decidir qué abre).
Ejecutar:  .venv/Scripts/python.exe tests/test_abre_su_panel.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QFileDialog, QInputDialog, QMenu,  # noqa: E402
                               QMessageBox, QPushButton, QToolButton)

# Ninguna ventana modal puede parar la prueba: se apunta que se abrió y se cancela
DIALOGOS: list[str] = []
QDialog.exec = lambda self, *a: (DIALOGOS.append(type(self).__name__), 0)[1]
QMenu.exec = lambda self, *a: (DIALOGOS.append("QMenu"), None)[1]
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: (DIALOGOS.append("QMessageBox"), QMessageBox.No)[1]))
for _n in ("getText", "getMultiLineText", "getItem", "getInt", "getDouble"):
    setattr(QInputDialog, _n, staticmethod(lambda *a, **k: (DIALOGOS.append("QInputDialog"), ("", False))[1]))
for _n in ("getOpenFileName", "getOpenFileNames", "getSaveFileName"):
    setattr(QFileDialog, _n, staticmethod(lambda *a, **k: ("", "")))

# Botones de la barra de la línea de tiempo y acciones de TODOS los menús de arriba que NO crean nada que rellenar ni piden que
# escribas (herramientas, zoom, cortes inmediatos, ventanas propias…). Lo que crea o pide algo va en la TABLA de main().
# ⚠ Si añades un botón o una acción y la prueba falla aquí: si crea algo que rellenar o necesita que escribas, haz que
#   abra su sitio (win.abrir_para_usar / ctrl.creado_por_ti) y ponlo en la TABLA; si no, apúntalo aquí con el motivo.
#   Claves: el texto del botón (sin texto: «tip:» + la 1.ª línea de su tooltip) o «Menú/Opción»; «Menú/Submenú/*» = el
#   submenú entero (sus opciones son todas de la misma clase, o cambian solas: plantillas, temas…).
CLASIFICADOS = {
    # barra: herramientas e interruptores (no crean nada)
    "↶ Deshacer": "inmediata", "↷ Rehacer": "inmediata", "➤": "herramienta", "✂": "herramienta",
    "⇿": "herramienta", "〰": "herramienta", "∩": "interruptor", "🔗": "interruptor",
    "Dividir": "inmediata", "Eliminar": "inmediata", "🗑 Vaciar": "inmediata (pregunta antes)",
    "▭ Quitar barras": "inmediata", "⚑": "inmediata (marcador con nombre; se renombra con doble clic)",
    "⚡ Ráfaga": "inmediata", "✨ B-roll": "abre IA ✨ (show_panel)", "🎬 Escenas": "inmediata (menú)",
    "📱 Vertical": "inmediata (en segundo plano)", "🖼 Miniatura": "abre su página", "⬆ Exportar": "ventana propia",
    "⋯ Más": "menú", "▤ Principal": "vista", "⊞ Pistas de composición": "vista", "◀": "abre ✂ Corte de audio",
    "▶": "abre ✂ Corte de audio", "−": "zoom", "+": "zoom", "⤢": "zoom",
    "👍": "inmediata", "👎": "inmediata", "⛔ Aquí no": "inmediata", "🔀 Remix": "inmediata", "🎛 Mix": "abre su ventana",
    # menús de la barra («⋯ Más», «⚡ Ráfaga»)
    "✂ Cambios de plano": "submenú", "⚡ Ráfaga de cortes al ritmo": "submenú",
    "✂ Cortar en los cambios claros": "inmediata", "✂ Cortar también en los suaves (menús, fundidos)": "inmediata",
    "⚑ Solo poner un marcador en cada cambio": "inmediata", "⚡ 1 compás (medio golpe)": "inmediata",
    "⚡ 2 compases (medio golpe)": "inmediata", "⚡⚡ 1 compás muy rápida (cuarto de golpe)": "inmediata",
    "⚡ Al golpe, entre las marcas I – O": "inmediata", "⚡ Medio golpe, entre las marcas I – O": "inmediata",
    "〰 Curvas de volumen y opacidad (Mayús+C)": "interruptor",
    # menú «Timeline»
    "Timeline/🟦 Añadir color sólido o degradado…": "ventana propia (el color se elige ahí)",
    "Timeline/🎯 Seguimiento del clip elegido…": "ventana propia", "Timeline/📌 Pegar el clip elegido a un objeto "
    "seguido…": "ventana propia", "Timeline/Acercar": "zoom", "Timeline/Alejar": "zoom",
    "Timeline/Ajustar a la ventana": "zoom", "Timeline/Añadir pista de video": "inmediata",
    "Timeline/Añadir pista de audio": "inmediata", "Timeline/🔗 Selección vinculada (audio y video juntos)": "interruptor",
    "Timeline/Separar el sonido al poner un video (como en Resolve)": "interruptor",
    "Timeline/〰 Forma de onda/*": "ajustes de vista", "Timeline/↕ Altura de las pistas de video/*": "ajustes de vista",
    "Timeline/⇤ Eliminar huecos (espacios vacíos entre clips)/*": "inmediatas",
    # menú «Archivo»
    "Archivo/Nuevo proyecto": "inmediata (pregunta si hay cambios)", "Archivo/Nuevo desde plantilla ▸/*":
    "inmediatas (lista que cambia)", "Archivo/Abrir proyecto…": "ventana propia", "Archivo/Guardar": "inmediata",
    "Archivo/Guardar como…": "ventana propia", "Archivo/Cambiar el nombre del proyecto": "edita el título del visor "
    "(siempre a la vista)", "Archivo/📋 Guardar como plantilla…": "ventana propia",
    "Archivo/Guardar nueva versión (v01, v02…)": "inmediata", "Archivo/💾 Guardado y copias de seguridad…":
    "ventana propia", "Archivo/⟲ Recuperar una copia de seguridad…": "ventana propia",
    "Archivo/📦 Recopilar proyecto (copia con todos sus archivos)…": "ventana propia",
    "Archivo/🎬 Ir a la pestaña Video horizontal": "cambia de pestaña", "Archivo/🎵 Ir a la pestaña Edits":
    "cambia de pestaña", "Archivo/📱 Ir a la pestaña Vertical": "cambia de pestaña",
    "Archivo/↪ Mover este proyecto a/*": "inmediatas (preguntan antes)", "Archivo/Importar archivos…": "ventana propia",
    "Archivo/Importar carpeta…": "ventana propia", "Archivo/Exportar video…": "ventana propia",
    "Archivo/🚀 Cola de exportación…": "ventana propia", "Archivo/🖼 Crear miniatura…": "abre su página",
    "Archivo/📸 Exportar este fotograma (PNG)": "ventana propia", "Archivo/📝 Descripción para YouTube (capítulos, "
    "créditos…)": "ventana propia", "Archivo/⇄ Llevar a DaVinci Resolve / Premiere (XML)…": "ventana propia",
    "Archivo/Salir": "cierra",
    # menú «Editar»
    "Editar/Copiar clips": "inmediata", "Editar/Cortar clips": "inmediata", "Editar/Pegar en el cabezal": "inmediata",
    "Editar/Pegar atributos… (efectos, zoom, sonido, velocidad)": "ventana propia", "Editar/Pegar e insertar":
    "inmediata", "Editar/Cortar y propagar": "inmediata", "Editar/Insertar espacio": "inmediata",
    "Editar/🎵 Ajustar la música a…/*": "inmediatas", "Editar/🔖 Leer marcas de OBS": "inmediata",
    "Editar/🔖 Fallos marcados…": "ventana propia", "Editar/Eliminar atributos…": "ventana propia",
    "Editar/🎬 Mi intro y mi outro…": "ventana propia", "Editar/➕ Poner mi intro y outro": "inmediata (pregunta)",
    "Editar/Activar / desactivar clip": "inmediata", "Editar/Cambiar duración…": "ventana propia (pide el número)",
    "Editar/Cambiar velocidad…": "ventana propia (pide el número)", "Editar/Normalizar volumen…": "ventana propia",
    "Editar/Buscar en el panel multimedia": "abre Medios con el archivo elegido", "Editar/Atributos del clip…":
    "ventana propia", "Editar/Dividir en el cabezal": "inmediata", "Editar/Eliminar": "inmediata",
    "Editar/Eliminar y cerrar hueco": "inmediata",
    "Editar/Recortar el inicio hasta el cabezal (y cerrar el hueco)": "inmediata (Q)",
    "Editar/Recortar el final hasta el cabezal (y cerrar el hueco)": "inmediata (W)",
    "Editar/Seleccionar todo lo que hay desde el cabezal hacia delante": "inmediata (Y)",
    "Editar/Seleccionar todo lo que hay desde el cabezal hacia atrás": "inmediata (Alt+Y)",
    "Editar/Mover el clip 1 fotograma a la izquierda": "inmediata («,»)",
    "Timeline/Clip elegido/*": "el clic derecho del clip elegido (cada opción, lo suyo)",
    "Timeline/Fila ⚡ de material por palabra clave": "inmediata (enseña la fila en la regla)",
    "Editar/Mover el clip 1 fotograma a la derecha": "inmediata («.»)",
    "Reproducción/Ir al corte anterior": "inmediata (↑)", "Reproducción/Ir al corte siguiente": "inmediata (↓)",
    "Editar/Poner lo elegido en Medios": "submenú (los modos de edición)",
    "Reproducción/Reproducir alrededor del cabezal": "inmediata («/»: suena y el cabezal vuelve)",
    "Voz/🎚 Voz pareja: el mismo volumen en cada frase": "inmediata (en segundo plano; se oye y su línea de volumen se ve en la narración; mensaje en la barra de estado)",
    "Voz/Quitar la voz pareja": "inmediata (mensaje en la barra de estado)",
    "Timeline/Detalle (10 s alrededor del cabezal)": "inmediata (zoom de la línea de tiempo, a la vista)",
    "Timeline/Barra resumen de todo el video": "interruptor (la franja encima de la línea de tiempo)",
    "tip:Detalle: 10 s alrededor del cabezal (otra vez = el zoom de antes)": "inmediata (zoom de la línea de tiempo, a la vista)",
    "Editar/Poner lo elegido en Medios/*": "inmediata (F9–F12: los clips nuevos quedan elegidos en la línea de tiempo, a la vista)",
    "Reproducción/Ir a la marca anterior": "inmediata (Mayús+↑; el cabezal en la marca y su texto en la barra de estado)",
    "Reproducción/Ir a la marca siguiente": "inmediata (Mayús+↓; el cabezal en la marca y su texto en la barra de estado)",
    "◉": "interruptor (puntos de unión en el audio; esquina de la línea de tiempo, = casilla de Cortes de audio)", "Editar/⇤ Juntar: todo se pega a la izquierda (canal seleccionado o "
    "todo)": "inmediata", "Editar/🗑 Vaciar la línea de tiempo…": "inmediata (pregunta)",
    "Editar/Bloquear / desbloquear selección": "inmediata", "Editar/Seleccionar todos los clips": "inmediata",
    "Editar/Añadir marcador": "inmediata (marcador con nombre)", "Editar/Marcar entrada": "inmediata",
    "Editar/Marcar salida": "inmediata", "Editar/Ir a la entrada": "inmediata", "Editar/Ir a la salida": "inmediata",
    "Editar/Quitar entrada y salida": "inmediata", "Editar/Quitar el tramo marcado (y cerrar el hueco)": "inmediata",
    "Editar/Congelar la imagen desde el cabezal": "inmediata", "Editar/Reproducir al revés (sí/no)": "inmediata",
    "Editar/✂ Eliminar silencio…": "ventana propia", "Editar/⧉ Poner transición (disolver) en el corte": "inmediata",
    "Editar/Herramienta de selección": "herramienta", "Editar/Herramienta cuchilla": "herramienta",
    "Editar/Herramienta de recorte avanzado (ripple, roll, slip, slide)": "herramienta",
    "Editar/〰 Curvas de volumen y opacidad (sí/no)": "interruptor", "Editar/Imán (encajar) sí/no": "interruptor",
    "Editar/🗣 Imán también a las palabras de la narración": "interruptor", "Editar/🧲 Pista principal magnética":
    "interruptor", "Editar/🥁 Imán también a los golpes de la música": "interruptor",
    # menú «Reproducción»
    "Reproducción/🎧 Audio en directo (ecualizador mientras suena)": "interruptor",
    "Reproducción/🔊 Oír al arrastrar el cabezal": "interruptor", "Reproducción/🎞 Video con motor propio (beta)":
    "interruptor", "Reproducción/⧉ Transiciones reales en el visor": "interruptor",
    "Reproducción/⚡ Pre-render de efectos pesados en el visor": "interruptor",
    "Reproducción/Resolución de la línea de tiempo (proxy)/*": "ajustes", "Reproducción/Reproducir / pausar": "transporte",
    "Reproducción/🖥 Visor en la segunda pantalla": "abre el visor en la otra pantalla",
    "Reproducción/Hacia atrás (J: otra vez = más rápido)": "transporte", "Reproducción/Parar (K)": "transporte",
    "Reproducción/Hacia delante (L: otra vez = más rápido)": "transporte",
    "Reproducción/Reproducir de la entrada a la salida": "transporte", "Reproducción/Repetir en bucle": "interruptor",
    "Reproducción/Fotograma anterior": "transporte", "Reproducción/Fotograma siguiente": "transporte",
    "Reproducción/⏪ Retroceder 5 segundos": "transporte", "Reproducción/⏩ Avanzar 5 segundos": "transporte",
    "Reproducción/⏩ Velocidad siguiente (1× → 2× → 4× → 8× → 1×)": "transporte",
    "Reproducción/▶ Velocidad normal (1×)": "transporte", "Reproducción/🔇 Silenciar / quitar el silencio de la "
    "escucha": "interruptor", "Reproducción/📊 Sonoridad para plataformas (LUFS)…": "ventana propia",
    "Reproducción/Ir al inicio": "transporte", "Reproducción/Ir al final": "transporte",
    "Reproducción/Corte de audio anterior (línea roja)": "abre ✂ Corte de audio",
    "Reproducción/Corte de audio siguiente (línea roja)": "abre ✂ Corte de audio",
    # menú «Voz»
    "Voz/Transcribir y analizar la narración": "abre Voz y texto → Transcribir", "Voz/Volver a analizar (silencios, "
    "muletillas…)": "abre Limpieza", "Voz/Ver transcripción": "abre Voz y texto → Transcripción",
    "Voz/Estilo de subtítulos": "abre Voz y texto → Subtítulos", "Voz/Exportar subtítulos (.srt)…": "ventana propia",
    "Voz/🎙 Grabar voz en off…": "ventana propia", "Voz/🎚 Analizar y proponer mezcla (música, diálogos y voz)…":
    "ventana propia", "Voz/◈ Entrenar la IA con mi voz": "en segundo plano (Tareas)",
    "Voz/◈ Olvidar lo que la IA aprendió de mi voz…": "pregunta",
    # menú «Ventana», «Convertir», «Ayuda» y «🔄 Reinicio»
    "Ventana/✂ Corte de audio": "abre ✂ Corte de audio", "Ventana/Restablecer la distribución de paneles": "inmediata",
    "Ventana/◧ Paneles de la izquierda a todo el alto": "interruptor", "Ventana/🔠 Tamaño de letra…": "ventana propia",
    "Ventana/🔍 Escala de la interfaz/*": "ajustes", "Ventana/🎨 Tema/*": "ajustes", "Ventana/🎨 Color de acento/*":
    "ajustes", "Ventana/⌨ Personalizar atajos de teclado…": "ventana propia",
    "Convertir/🔁 Convertir videos y audios…": "ventana propia", "Convertir/🎬 A MP4 (video)…": "ventana propia",
    "Convertir/🎵 A MP3 (solo audio)…": "ventana propia", "Ayuda/📖 Guía paso a paso": "abre la Guía",
    "Ayuda/Guía de primer uso": "abre la guía de primer uso (recorrido sobre los paneles)",
    "Ayuda/🎓 Proyecto de ejemplo": "abre el proyecto y la Guía", "Ayuda/Atajos de teclado": "ventana propia",
    "Ayuda/⌨ Personalizar atajos…": "ventana propia", "Ayuda/✧ Caché y diagnóstico…": "ventana propia",
    "Ayuda/◈ Motor de IA (tarjeta gráfica)…": "ventana propia", "Ayuda/👋 Bienvenida y componentes…": "ventana propia",
    "Ayuda/🤝 Dejar que Claude edite conmigo (MCP)": "interruptor", "Ayuda/♥ Apoyar Reclaimer…": "ventana propia",
    "Ayuda/Acerca de Reclaimer": "ventana propia", "🔄 Reinicio/🔄 Reinicio de proyecto (empezar de cero)…": "pregunta",
    "🔄 Reinicio/↪ Cambiar este proyecto a 🎬 Video horizontal…": "pregunta",
    "🔄 Reinicio/↪ Cambiar este proyecto a 🎵 Edits…": "pregunta",
    "🔄 Reinicio/↪ Cambiar este proyecto a 📱 Vertical…": "pregunta",
    "Timeline/🔒 Bloquear toda la timeline": "inmediata", "Timeline/🔓 Desbloquear toda la timeline": "inmediata",
}


MIN_BOTONES = 30          # (hoy hay más: si se ven menos, la prueba no mira donde debe)
MIN_ACCIONES = 150


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core.model import ORIGIN_AI, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.activateWindow()
    pump(app, 0.5)
    ctrl = win.ctrl
    fallos: list[str] = []

    vid = os.path.join(out, "abre.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=8", "-f", "lavfi", "-i", "sine=f=440:d=8", "-shortest", "-c:v",
                    "libx264", "-preset", "ultrafast", "-c:a", "aac", vid], check=True, stdin=subprocess.DEVNULL)
    (mid,) = ctrl.import_now([vid])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    vt = next(t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO)
    made = ctrl.add_media([mid], vt.id, 0.0)
    cid = next(i for i in made if ctrl.project.track(ctrl.project.clips[i].track_id).kind == TRACK_VIDEO)
    win.engine.seek(1.0)
    pump(app, 0.2)

    def peor_caso(panel=None, sel=()):
        """Todos los paneles cerrados (salvo la línea de tiempo), ninguna ventana suelta y el foco en la línea de
        tiempo; con panel, ese abierto (la acción se pulsa dentro de él)."""
        for w in app.topLevelWidgets():
            if w is not win and w.isVisible() and not isinstance(w, (QDockWidget, QMenu)):
                w.hide()
        for k, d in win.docks.items():
            if k != "timeline" and not d.isHidden():
                d.hide()
        win.activateWindow()
        if panel is not None:
            win.show_panel(panel)
        win.timeline.set_selection(list(sel))
        win.timeline.setFocus()
        pump(app, 0.15)
        DIALOGOS.clear()

    def accion(clave):
        return win.shortcut_actions[clave][0].trigger

    def boton(texto):
        for b in win._tl_bar.findChildren(QPushButton):
            if win._tl_compact.get(b, (b.text(),))[0] == texto:
                return b.click
        raise AssertionError(f"no encuentro el botón «{texto}» en la barra de la línea de tiempo")

    def plantilla():
        acts = [a for a in win.btn_titles.menu().actions() if a.text() and a.menu() is None]
        acts[0].trigger()

    from PySide6.QtTest import QTest
    ins = win.inspector
    # 🧭 LA TABLA: acción → (cómo se dispara, widget que debe quedar a la vista, widget con el foco o None,
    #    ¿texto entero seleccionado?, panel donde se pulsa, selección previa)
    TABLA = [
        ("barra «T» (añadir texto)", boton("T"), ins.text_edit, ins.text_edit, True, None, ()),
        ("tecla T", lambda: QTest.keyClick(win.timeline, Qt.Key_T), ins.text_edit, ins.text_edit, True, None, ()),
        ("menú Timeline › T Añadir texto en el cabezal", accion("Timeline/T Añadir texto en el cabezal"),
         ins.text_edit, ins.text_edit, True, None, ()),
        ("barra «🅣» (plantilla de título)", plantilla, ins.text_edit, ins.text_edit, True, None, ()),
        ("clic derecho › T Añadir texto aquí", lambda: win.timeline._add_text_here(2.0), ins.text_edit, ins.text_edit,
         True, None, ()),
        ("menú Timeline › 🎨 capa de ajuste", accion("Timeline/🎨 Añadir capa de ajuste (color y efectos a todo lo de "
                                                     "debajo)"), ins.secciones["color"], None, False, None, ()),
        ("Ctrl+F buscar clips por contenido", accion("IA/Buscar clips por contenido"), win.library.search,
         win.library.search, False, None, ()),
        ("Ctrl+Shift+F buscar momentos", accion("IA/🔎 Buscar momentos en mis medios…"), win.moments.query,
         win.moments.query, False, None, ()),
        ("Ctrl+Alt+F buscar en lo que dijiste", accion("Voz/🔎 Buscar en lo que dijiste"), win.transcript.search,
         win.transcript.search, False, None, ()),
        ("R velocidad del clip", accion("Editar/Velocidad del clip…"), ins.speed, ins.speed, False, None, (cid,)),
        ("Voz y texto › «T Añadir» (su propio cuadro)", win.text_writer.add_here, win.text_writer.edit,
         win.text_writer.edit, True, win.text_writer, ()),
        # 🌑 (21/11) Efectos › «Sombra»: pone la sombra y abre Inspector → Efectos → «Sombra» con el foco en «Fuerza»
        ("Efectos › Sombra", win.effects.b_sombra.click, ins.secciones["sombra"], ins.sombra_fuerza, False,
         win.effects, (cid,)),
    ]
    marcas = getattr(win, "marcadores_panel", None)
    if marcas is None or "marcadores" not in ins.secciones:
        fallos.append("📍 el índice de marcas no está en Inspector → Proyecto → «Marcadores» (poner_marcadores)")
    else:
        def m_m():                                       # (M y otra vez M en el mismo sitio = escribir su nota)
            QTest.keyClick(win.timeline, Qt.Key_M)
            pump(app, 0.2)
            win.timeline.setFocus()
            QTest.keyClick(win.timeline, Qt.Key_M)
        TABLA.append(("M+M nota del marcador", m_m, marcas.nota, marcas.nota, False, None, ()))
    for nombre, disparar, ver, foco, entero, panel, sel in TABLA:
        peor_caso(panel, sel)
        antes = set(ctrl.project.clips)
        disparar()
        pump(app, 0.4)
        nuevos = [i for i in ctrl.project.clips if i not in antes]
        problemas = []
        if not ver.isVisible():
            problemas.append("NO ABRE NADA" if not any(not d.isHidden() for k, d in win.docks.items()
                                                       if k != "timeline") else "ABRE ALGO QUE NO ES")
        if foco is not None and ver.isVisible() and not foco.hasFocus():
            fw = app.focusWidget()
            problemas.append(f"ABRE PERO SIN FOCO (lo tiene {type(fw).__name__ if fw else 'nadie'})")
        if entero and foco is not None and foco.hasFocus():
            cur = foco.textCursor()
            if not cur.hasSelection() or cur.selectedText() != foco.toPlainText():
                problemas.append("el texto de fábrica no queda seleccionado para escribir encima")
        if nuevos and panel is None and set(win.timeline.selected) != set(nuevos):
            problemas.append("lo creado no queda elegido")
        if problemas:
            fallos.append(f"{nombre}: " + "; ".join(problemas))
        print(("✓ " if not problemas else "✗ ") + nombre + ("" if not problemas else " → " + "; ".join(problemas)),
              flush=True)
        if nuevos:
            ctrl.delete_clips(nuevos)

    # 🔤 escribir de verdad: tras «T», lo tecleado sustituye a «Texto» en el clip nuevo
    peor_caso()
    antes = set(ctrl.project.clips)
    boton("T")()
    pump(app, 0.3)
    QTest.keyClicks(app.focusWidget(), "Hola mundo")
    pump(app, 0.6)
    nuevo = next(i for i in ctrl.project.clips if i not in antes)
    contenido = ctrl.project.clips[nuevo].text.get("content")
    if contenido != "Hola mundo":
        fallos.append(f"tras «T» y escribir, el texto del clip es {contenido!r} (esperaba 'Hola mundo')")
    else:
        print("✓ «T» y escribir: el clip nuevo dice «Hola mundo»")
    QTest.keyClick(ins.text_edit, Qt.Key_Escape)        # Esc: de vuelta a la línea de tiempo
    pump(app, 0.2)
    if not win.timeline.hasFocus():
        fallos.append("Esc en el cuadro del texto no devuelve el foco a la línea de tiempo")
    else:
        print("✓ Esc en el cuadro del texto vuelve a la línea de tiempo")
    ctrl.delete_clips([nuevo])
    # ↶ «T» y, sin escribir nada, Ctrl+Z: se deshace el texto recién creado y el foco vuelve a la línea de tiempo
    peor_caso()
    antes = set(ctrl.project.clips)
    boton("T")()
    pump(app, 0.3)
    QTest.keyClick(app.focusWidget(), Qt.Key_Z, Qt.ControlModifier)
    pump(app, 0.3)
    if set(ctrl.project.clips) != antes:
        fallos.append("«T» y Ctrl+Z sin escribir: el texto recién creado sigue ahí")
        ctrl.delete_clips([i for i in ctrl.project.clips if i not in antes])
    elif not win.timeline.hasFocus():
        fw = app.focusWidget()
        fallos.append(f"«T» y Ctrl+Z sin escribir: el foco se queda en {type(fw).__name__ if fw else 'nadie'}, no en la "
                      "línea de tiempo")
    else:
        print("✓ «T» y Ctrl+Z sin escribir: se deshace el texto recién creado y el foco vuelve a la línea de tiempo")

    # ↶ «T», escribir «Hola» y Ctrl+Z ×3: cada Ctrl+Z hace algo visible (un solo historial, el del proyecto)
    peor_caso()
    ctrl.add_marker(5.0, "marcador de la prueba")
    n_mk = len(ctrl.project.markers)
    antes = set(ctrl.project.clips)
    boton("T")()
    pump(app, 0.3)
    QTest.keyClicks(app.focusWidget(), "Hola")
    pump(app, 0.6)
    nuevo = next(i for i in ctrl.project.clips if i not in antes)
    pasos = []
    QTest.keyClick(app.focusWidget(), Qt.Key_Z, Qt.ControlModifier)
    pump(app, 0.3)
    c = ctrl.project.clips.get(nuevo)
    pasos.append(c is not None and c.text.get("content") == "Texto" and ins.text_edit.toPlainText() == "Texto")
    QTest.keyClick(app.focusWidget(), Qt.Key_Z, Qt.ControlModifier)
    pump(app, 0.3)
    pasos.append(nuevo not in ctrl.project.clips and win.timeline.hasFocus())
    QTest.keyClick(app.focusWidget(), Qt.Key_Z, Qt.ControlModifier)
    pump(app, 0.3)
    pasos.append(len(ctrl.project.markers) == n_mk - 1)
    if not all(pasos):
        fallos.append(f"«T» + «Hola» + Ctrl+Z ×3: ¿hizo algo visible cada uno? {pasos} (1 = vuelve a «Texto», "
                      "2 = quita el texto y el foco a la línea de tiempo, 3 = quita el marcador de antes)")
    else:
        print("✓ «T» + «Hola» + Ctrl+Z ×3: «Texto» → sin texto → sin el marcador de antes (cada uno, algo visible)")
    ctrl.delete_clips([i for i in ctrl.project.clips if i not in antes])

    # ⏩ dos textos seguidos rápido: lo escrito en el primero (aún sin guardar, < 350 ms) no se pierde
    peor_caso()
    antes = set(ctrl.project.clips)
    boton("T")()
    pump(app, 0.3)
    primero = next(i for i in ctrl.project.clips if i not in antes)
    QTest.keyClicks(app.focusWidget(), "Uno")
    t_rapido = time.time()
    plantilla()                                         # (🅣 enseguida: también crea un texto)
    rapido = time.time() - t_rapido < 0.35
    pump(app, 0.6)
    segundo = [i for i in ctrl.project.clips if i not in antes and i != primero]
    ok = (rapido and ctrl.project.clips[primero].text.get("content") == "Uno" and len(segundo) == 1
          and set(win.timeline.selected) == set(segundo) and ins.text_edit.hasFocus()
          and ins.text_edit.toPlainText() == ctrl.project.clips[segundo[0]].text.get("content"))
    if not ok:
        fallos.append(f"dos textos seguidos: el primero dice {ctrl.project.clips[primero].text.get('content')!r} "
                      f"(esperaba 'Uno'); a tiempo={rapido}; el cuadro enseña {ins.text_edit.toPlainText()!r}")
    else:
        print("✓ dos textos seguidos (< 350 ms): lo escrito en el primero se guarda y el cuadro pasa al segundo")
    QTest.keyClick(ins.text_edit, Qt.Key_Escape)
    ctrl.delete_clips([i for i in ctrl.project.clips if i not in antes])

    # ✍ deshacer por tramos, como en un editor de texto: «Hola», pausa, « mundo» = dos pasos; pegar = un paso propio
    peor_caso()
    antes = set(ctrl.project.clips)
    boton("T")()
    pump(app, 0.3)
    nuevo = next(i for i in ctrl.project.clips if i not in antes)
    QTest.keyClicks(app.focusWidget(), "Hola")
    pump(app, 0.5)
    QTest.keyClicks(app.focusWidget(), " mundo")
    pump(app, 0.6)

    def contenido():
        c = ctrl.project.clips.get(nuevo)
        return c.text.get("content") if c is not None else None

    vistos = []
    for tecla, mod in ((Qt.Key_Z, Qt.ControlModifier), (Qt.Key_Z, Qt.ControlModifier), (Qt.Key_Y, Qt.ControlModifier),
                       (Qt.Key_Y, Qt.ControlModifier)):
        QTest.keyClick(app.focusWidget(), tecla, mod)
        pump(app, 0.3)
        vistos.append((contenido(), ins.text_edit.toPlainText(), ins.text_edit.textCursor().position()))
    esperado = [("Hola", "Hola", 4), ("Texto", "Texto", 5), ("Hola", "Hola", 4), ("Hola mundo", "Hola mundo", 10)]
    if vistos != esperado:
        fallos.append(f"deshacer por tramos: (texto del clip, cuadro, cursor) = {vistos}; esperaba {esperado}")
    else:
        print("✓ «Hola», pausa, « mundo»: Ctrl+Z → «Hola» → «Texto»; Ctrl+Y ×2 → «Hola mundo» (cursor donde el cambio)")
    QApplication.clipboard().setText("XYZ")
    cur = ins.text_edit.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    ins.text_edit.setTextCursor(cur)
    QTest.keyClicks(ins.text_edit, "!")
    QTest.keyClick(ins.text_edit, Qt.Key_V, Qt.ControlModifier)
    pump(app, 0.6)
    pegado = contenido()
    QTest.keyClick(app.focusWidget(), Qt.Key_Z, Qt.ControlModifier)
    pump(app, 0.3)
    if pegado != "Hola mundo!XYZ" or contenido() != "Hola mundo!":
        fallos.append(f"pegar no es un paso propio: tras pegar {pegado!r}, tras Ctrl+Z {contenido()!r} "
                      "(esperaba 'Hola mundo!XYZ' y 'Hola mundo!')")
    else:
        print("✓ pegar es un paso propio: Ctrl+Z quita solo lo pegado")
    QTest.keyClick(ins.text_edit, Qt.Key_Escape)
    ctrl.delete_clips([i for i in ctrl.project.clips if i not in antes])

    # 🤖 lo de la IA y lo automático NO abre nada ni quita el foco
    def sin_abrir(nombre, fn):
        peor_caso()
        antes = set(ctrl.project.clips)
        fn()
        pump(app, 0.4)
        nuevos = [i for i in ctrl.project.clips if i not in antes]
        abiertos = [k for k, d in win.docks.items() if k != "timeline" and not d.isHidden()]
        ok = bool(nuevos) and not abiertos and win.timeline.hasFocus()
        if not ok:
            fallos.append(f"{nombre}: creó {len(nuevos)}, abrió {abiertos}, foco en la línea de tiempo = "
                          f"{win.timeline.hasFocus()}")
        print(("✓ " if ok else "✗ ") + nombre + " no abre nada ni roba el foco", flush=True)
        if nuevos:
            ctrl.delete_clips(nuevos)

    sin_abrir("texto de la IA (origin=ai)", lambda: ctrl.add_text(1.0, 3.0, "IA", origin=ORIGIN_AI))

    def _auto():
        with ctrl.sin_abrir_editor():
            ctrl.add_text(1.0, 3.0, "Automático")
            ctrl.add_generator({"kind": "adjust"}, 1.0, 3.0)
    sin_abrir("proceso automático (ctrl.sin_abrir_editor)", _auto)
    from editoria.ui.claude_bridge import ClaudeBridge
    puente = ClaudeBridge(win)
    respuestas = []
    sin_abrir("puente de Claude (texto)", lambda: puente.ejecutar(puente.t_texto, {"inicio": 1.0, "contenido": "Claude"},
                                                                   lambda *a: respuestas.append(a)))

    # 🔎 que nadie añada una acción sin decidir qué abre: TODOS los botones de la barra de la línea de tiempo (también
    #    los de solo icono, por su tooltip) con sus menús, y TODOS los menús de la barra de arriba
    en_tabla = {"T", "Títulos", "Timeline/T Añadir texto en el cabezal", "Timeline/🅣 Plantillas de título/*",
                "Timeline/🎨 Añadir capa de ajuste (color y efectos a todo lo de debajo)",
                "IA/Buscar clips por contenido", "IA/🔎 Buscar momentos en mis medios…",
                "Voz/🔎 Buscar en lo que dijiste", "Editar/Velocidad del clip…"}
    conocidos = set(CLASIFICADOS) | en_tabla
    ignorar = {win._act_deshacer, win._act_rehacer} | {d.toggleViewAction() for d in win.docks.values()}

    def clave_boton(b):
        t = win._tl_compact.get(b, (b.text(),))[0].replace(" 〰", "").strip()
        if t:
            return t
        tip = (b.toolTip() or "").split("\n")[0].strip()
        return "tip:" + tip if tip else "obj:" + (b.objectName() or type(b).__name__)

    def revisar():
        sin, botones, acciones = [], set(), [0]

        def menu_de(menu, prefijo, pon_prefijo):
            for a in menu.actions():
                if a.isSeparator() or not a.text() or a in ignorar:
                    continue
                k = prefijo + a.text().replace("&", "")
                acciones[0] += 1
                if k + "/*" in conocidos:                # (un submenú clasificado entero: sus opciones, igual)
                    continue
                if k not in conocidos:
                    sin.append(k)
                if a.menu() is not None:
                    menu_de(a.menu(), k + "/" if pon_prefijo else "", pon_prefijo)

        for b in win._tl_bar.findChildren(QPushButton) + win._tl_bar.findChildren(QToolButton):
            if id(b) in botones:
                continue
            botones.add(id(b))
            k = clave_boton(b)
            if k not in conocidos:
                sin.append(k)
            if b.menu() is not None and k != "Títulos":       # (Títulos: sus plantillas, todas por el mismo camino)
                menu_de(b.menu(), "", False)
        for top in win.menuBar().actions():
            if top.menu() is not None:
                menu_de(top.menu(), top.text().replace("&", "") + "/", True)
        return sin, len(botones), acciones[0]

    sin_decidir, n_botones, n_acciones = revisar()
    if os.environ.get("RECLAIMER_VOLCAR"):
        print("\n".join(f'    "{k}": "",' for k in sin_decidir))
    if sin_decidir:
        fallos.append("acciones nuevas sin decidir qué abren (ponlas en la TABLA o en CLASIFICADOS): "
                      + " · ".join(sin_decidir))
    elif n_botones < MIN_BOTONES or n_acciones < MIN_ACCIONES:
        fallos.append(f"se vieron solo {n_botones} botones y {n_acciones} acciones (mínimo {MIN_BOTONES} y "
                      f"{MIN_ACCIONES}): ¿cambió dónde viven? la prueba no puede pasar en vacío")
    else:
        print(f"✓ {n_botones} botones de la barra y {n_acciones} acciones de los menús: todos en la tabla o "
              "clasificados")
    # 🧪 y la propia revisión funciona: un botón nuevo de SOLO ICONO y una acción nueva en «Editar» se detectan
    falso = QToolButton()
    falso.setToolTip("🆕 Botón de prueba solo icono")
    win._tl_bar.layout().addWidget(falso)
    menu_ed = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Editar")
    falsa = menu_ed.addAction("🆕 Acción de prueba")
    sin_m, _nb, _na = revisar()
    if "tip:🆕 Botón de prueba solo icono" not in sin_m or "Editar/🆕 Acción de prueba" not in sin_m:
        fallos.append(f"la revisión no detecta un botón de solo icono ni una acción nueva en «Editar»: {sin_m}")
    else:
        print("✓ la revisión detecta un botón nuevo de solo icono y una acción nueva en «Editar»")
    menu_ed.removeAction(falsa)
    falso.setParent(None)
    falso.deleteLater()

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    if fallos:
        print("\n✗ FALLOS:\n  " + "\n  ".join(fallos))
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
