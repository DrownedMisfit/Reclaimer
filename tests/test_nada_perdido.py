"""
Agrupación del 20/11 (notas_claude/PROPUESTA_INTERFAZ.md, «Agrupación 20/11»): que NADA se pierda al reunir paneles y
quitar redundancias. Cada fila de la tabla «antes → después» sigue accesible desde la interfaz (interruptor, sección,
menú o página) y no quedan dos controles iguales a la vista a la vez:
  · fila de paneles: Medios · Efectos · Sonidos · IA · Momentos · Memes · Descargas · Voz y texto | Palabras clave ·
    Audio · Inspector (22/11: «Voz y texto» a la izquierda y «Palabras clave» su propio panel a la derecha);
  · «Voz y texto»: 1 Transcribir · 2 Transcripción · 3 Subtítulos · 4 Voz IA; «Palabras clave»: Dijiste… · Carpetas ·
    Buscar material; «Audio»: 1 Limpieza · 2 Mezcla y música · 3 Sonoridad; Material del clip en Inspector →
    Archivo; Historial y Gráficas en ☰ Paneles y Ventana;
  · una distribución guardada de antes (Voz y texto a la derecha) pasa a la nueva: Voz y texto junto a Medios,
    Palabras clave junto al Inspector, y lo que recordabas por pestaña de Voz y texto vale para Palabras clave;
  · show_panel / go_page de lo de antes llevan a su sitio nuevo (Palabras clave, Transcripción, Audio, Efectos,
    Medios, Montaje guiado, Entrega);
  · abajo: Editar · Escenas · Miniatura · Entrega; 🧭 Montaje guiado en la barra de menús, a la izquierda de 🔄 Reinicio;
  · barra de la línea de tiempo sin B-roll, Escenas, Miniatura ni Exportar (cada uno en su sitio; «✂ Cambios de plano»
    en ⋯ Más) y con ↶ / ↷ activos según la pila;
  · la sonoridad en UN sitio (Audio → Sonoridad): ni en el transporte ni repetida en el Inspector;
  · una distribución guardada con paneles de antes no los vuelve a sacar sueltos.
Pantalla de prueba 1920×1080. Carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_nada_perdido.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
_CFG = f"_pruebas_tmp/pantalla_nada_{os.getpid()}.json"
with open(os.path.join(RAIZ, _CFG), "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96,
                            "dpr": 1}]}, _f)
__import__("atexit").register(lambda: os.path.exists(os.path.join(RAIZ, _CFG)) and os.remove(os.path.join(RAIZ, _CFG)))
os.chdir(RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=os.path.join(RAIZ, "_pruebas_tmp"))
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox  # noqa: E402

FALLOS = []


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def dentro(contenedor, w) -> bool:
    return w is not None and (w is contenedor or contenedor.isAncestorOf(w))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in list(st.allKeys()):
        if k.startswith("paneles_pestana/") or k in ("ventana/paneles", "geometry") or k.startswith("agrupados/"):
            st.remove(k)
    import editoria.ui.audit_dialog as AD
    import editoria.ui.main_window as MW
    AD.revision_previa = lambda _w: True
    exportados = []
    MW.ExportDialog.exec = lambda self: exportados.append(1) or 0
    win = MW.MainWindow()
    win.show()
    win.resize(1916, 1000)
    pump(app, 1.2)
    win.go_page("edit")
    pump(app, 0.5)
    D = win.docks
    vt, au = win.voz_texto, win.audio_panel

    print("— la fila de paneles —")
    izq = [k for k, _n in win.INTERRUPTORES_IZQ]
    der = [k for k, _n in win.INTERRUPTORES_DER]
    for k in ("media", "effects", "sounds", "ai", "moments", "memes", "descargas_web", "voz_texto"):
        chk(k in izq and not win.interruptores[k].isHidden(), f"interruptor «{dict(win.INTERRUPTORES_IZQ)[k]}» a la vista")
    for k in ("palabras", "audio", "inspector"):
        chk(k in der and not win.interruptores[k].isHidden(), f"interruptor «{dict(win.INTERRUPTORES_DER)[k]}» a la vista")
    quitados = ("transcript", "subtitles", "clips", "voz_ia", "voice", "audio_mix", "history", "scopes", "material")
    chk(not any(k in win.interruptores for k in quitados), "sin los interruptores de antes (Transcripción, Subtítulos, "
        "Palabras clave, Voz IA, Limpieza, Mezcla, Historial, Gráficas, Material)")

    print("— «Voz y texto» y «Audio»: cada cosa en su sección —")
    chk(vt.claves() == ["transcribir", "transcripcion", "subtitulos", "voz_ia"],
        f"Voz y texto en el orden de trabajo ({vt.claves()})")
    chk(dentro(vt.widget_de("transcribir"), getattr(win.voice, "sec1", None)),
        "1 · Transcribir: el bloque de transcribir (modelo, idioma, botón)")
    chk(dentro(vt.widget_de("transcripcion"), win.transcript), "2 · Transcripción: el texto")
    chk(dentro(vt.widget_de("subtitulos"), win.subtitles), "3 · Subtítulos")
    pal = D["palabras"].panel
    chk(dentro(pal, win._pal_tabs) and dentro(pal, win.clips) and dentro(pal, win.kw_folders)
        and dentro(pal, D["kw_buscar"].panel), "Palabras clave (su panel): Dijiste…, Carpetas y Buscar material")
    chk(dentro(vt.widget_de("voz_ia"), win.voz_ia), "4 · Voz IA")
    chk(win.dockWidgetArea(D["voz_texto"]) == Qt.LeftDockWidgetArea and
        win.dockWidgetArea(D["palabras"]) == Qt.RightDockWidgetArea,
        "Voz y texto a la izquierda y Palabras clave a la derecha")
    chk(au.claves() == ["limpieza", "mezcla", "sonoridad", "cortes"],
        f"Limpieza y mezcla: Limpieza · Mezcla · Sonoridad · Cortes de audio ({au.claves()})")
    chk(dentro(au.widget_de("cortes"), win.btn_corte_audio), "Limpieza y mezcla → Cortes de audio: su botón")
    chk(dentro(au.widget_de("limpieza"), win.voice), "Audio → Limpieza")
    chk(dentro(au.widget_de("mezcla"), D["audio_mix"].panel), "Audio → Mezcla y música")
    chk(dentro(au.widget_de("sonoridad"), win.ai_panel.loud) and dentro(au.widget_de("sonoridad"), win.btn_sonoridad),
        "Audio → Sonoridad: la casilla −14 LUFS y «Medir»")
    chk(dentro(win.inspector, win.material), "Material del clip dentro del Inspector (Archivo)")

    print("— a un clic desde lo de antes (show_panel / go_page / menús) —")
    for w, panel, sec, nombre in ((win.transcript, "voz_texto", "transcripcion", "Transcripción"),
                                  (win.subtitles, "voz_texto", "subtitulos", "Subtítulos"),
                                  (win.clips, "palabras", None, "Dijiste…"),
                                  (win.kw_folders, "palabras", None, "Carpetas"),
                                  (D["kw_buscar"].panel, "palabras", None, "Buscar material"),
                                  (win.voz_ia, "voz_texto", "voz_ia", "Voz IA"),
                                  (win.voice, "audio", "limpieza", "Limpieza"),
                                  (D["audio_mix"].panel, "audio", "mezcla", "Mezcla y música")):
        win.show_panel(w)
        pump(app, 0.3)
        acordeon = {"voz_texto": vt, "audio": au}.get(panel)
        chk(not D[panel].isHidden() and (acordeon is None or acordeon.abierta() == sec) and w.isVisible(),
            f"show_panel({nombre}) → «{D[panel].nombre}» → {sec or 'su pestaña'}")
    # (los botones de siempre que abren Voz IA y Subtítulos: «🗣 Que lo lea la IA», el 🗣 de la barra de Shorts…)
    for abrir, sec in ((win.open_voz_ia, "voz_ia"), (win.open_subtitles, "subtitulos")):
        win.abrir_seccion("audio", "limpieza")
        D["voz_texto"].hide()
        pump(app, 0.2)
        abrir()
        pump(app, 0.3)
        chk(not D["voz_texto"].isHidden() and vt.abierta() == sec and vt.widget_de(sec).isVisible(),
            f"{abrir.__name__}() → «Voz y texto» → {sec}")
    chk(QSettings("EditorIA", "EditorIA").value(f"paneles_pestana/{win.workspaces.current}/voz_ia") is None,
        "sin la clave vieja paneles_pestana/…/voz_ia")
    # (mostrar_widget: la función pública para la guía y la ayuda)
    for w, nombre, cond in ((win.subtitles, "Subtítulos", lambda: vt.abierta() == "subtitulos"),
                            (win.kw_folders, "Carpetas", lambda: win._pal_tabs.currentWidget() is win.kw_folders),
                            (win.btn_sonoridad, "Medir la sonoridad", lambda: au.abierta() == "sonoridad"),
                            (win.btn_corte_audio, "Abrir «Corte de audio»", lambda: au.abierta() == "cortes")):
        ok = win.mostrar_widget(w)
        pump(app, 0.3)
        chk(ok and w.isVisible() and cond(), f"mostrar_widget({nombre}) → a la vista")
    win._ai_card("audio")
    pump(app, 0.3)
    chk(not D["audio"].isHidden() and au.abierta() == "mezcla", "la tarjeta 🔊 de IA ✨ → Mezcla y música")
    win.abrir_corte_audio()
    pump(app, 0.4)
    dc = D.get("cortes")
    chk(dc is not None and not dc.isHidden() and not any(D.get(k) in win.tabifiedDockWidgets(dc)
                                                         for k in win.interruptores),
        "✂ Corte de audio a la vista, sin fila de pestañas con paneles de arriba")
    if dc is not None:
        dc.hide()
    win._mostrar_desde_menu("history")
    pump(app, 0.3)
    chk(not D["history"].isHidden() and not any(D.get(k) in win.tabifiedDockWidgets(D["history"])
                                                for k in win.interruptores),
        f"Historial: debajo del Inspector, sin repetir la fila «Inspector · Voz y texto · …» "
        f"({[win._nombre_limpio(x) for x in win.tabifiedDockWidgets(D['history'])]}, hidden={D['history'].isHidden()})")
    D["history"].hide()
    win.show_panel(win.material)
    pump(app, 0.3)
    chk(not D["inspector"].isHidden() and not D["inspector"].visibleRegion().isEmpty(),
        "show_panel(Material del clip) → el Inspector (su pestaña Archivo, con un clip elegido)")
    for clave, panel, sec in (("keywords", "palabras", None), ("transcripcion", "voz_texto", "transcripcion"),
                              ("fairlight", "audio", "limpieza")):
        win.go_page(clave)
        pump(app, 0.3)
        acordeon = {"voz_texto": vt, "audio": au}.get(panel)
        chk(not D[panel].isHidden() and (acordeon is None or acordeon.abierta() == sec)
            and win.page_buttons["edit"].isChecked(),
            f"go_page(«{clave}») → «{D[panel].nombre}» → {sec}")
    win.go_page("effects")
    pump(app, 0.3)
    chk(not D["effects"].isHidden() and not D["effects"].visibleRegion().isEmpty(), "go_page(«effects») → el panel "
        "Efectos en Editar")
    win.go_page("media")
    pump(app, 0.3)
    chk(not D["media"].isHidden() and not D["media"].visibleRegion().isEmpty(), "go_page(«media») → el panel Medios")
    acciones = {a.text() for a in win.findChildren(type(win.act_guiado))}
    for t in ("Importar archivos…", "Importar carpeta…"):
        chk(t in acciones, f"Medios: «{t}» sigue en Archivo")
    chk(any(a.text().replace("&", "").startswith("Convertir") for a in win.menuBar().actions()),
        "Medios: el menú Convertir sigue (MP4/MP3, copias ligeras…)")
    chk(any(b.text().endswith("Archivos") for b in win.library.findChildren(QAbstractButton)),
        "Medios: «+ Archivos» en su panel")
    mb = win.menuBar()
    acts = mb.actions()
    i_g = next((i for i, a in enumerate(acts) if a is win.act_guiado), -1)
    i_r = next((i for i, a in enumerate(acts) if a.menu() is not None and "Reinicio" in a.text()), -1)
    chk(0 <= i_g < i_r and i_r == i_g + 1, "🧭 Montaje guiado en la barra de menús, a la izquierda de 🔄 Reinicio")
    win.act_guiado.trigger()
    pump(app, 0.4)
    chk(not D["guided"].isHidden(), "…y abre el Montaje guiado")
    win.go_page("edit")
    pump(app, 0.3)
    win.page_buttons["deliver"].click()
    pump(app, 0.3)
    chk(win.herramientas.abierta("exportar"), "abajo, «Entrega» abre Exportar (pestaña del panel de herramientas)")
    win.herramientas.cerrar("exportar")
    chk(any(a.text().startswith("Exportar video") and a.shortcut().toString() == "Ctrl+E" for a in
            win.findChildren(type(win.act_guiado))), "Ctrl+E (Archivo → Exportar video…) sigue")
    chk(not win.btn_quick_export.isHidden(), "⚡ Exportar rápido sigue arriba (otra función: exporta sin preguntar)")
    win._llenar_menu_paneles()
    textos = [a.text() for a in win._menu_paneles.actions()]
    for nombre in ("Historial", "Gráficas", "Transcribir", "Palabras clave", "Sonoridad", "Cortes de audio"):
        chk(any(nombre in t for t in textos), f"☰ Paneles lleva a «{nombre}»")
    win._llenar_menu_ventana()
    vtx = [a.text() for a in win._menu_ventana.actions()]
    chk(any("Historial" in t for t in vtx) and any("Gráficas" in t for t in vtx), "Ventana: Historial y Gráficas")
    chk(any("Corte de audio" in t for t in vtx), "Ventana: ✂ Corte de audio")
    chk(not any(t in ("Texto", "Transcripción", "Subtítulos", "Limpieza") for t in vtx),
        "Ventana: sin los paneles absorbidos sueltos")

    print("— abajo y en la barra de la línea de tiempo —")
    chk(list(win.page_buttons) == ["edit", "scenes", "thumb", "deliver"], f"abajo: Editar · Escenas · Miniatura · "
        f"Entrega ({list(win.page_buttons)})")
    chk(win._page_bar_w.height() <= 34, f"la barra de abajo, a la mitad de alto ({win._page_bar_w.height()} px)")
    for nombre, b in (("B-roll", win.btn_broll), ("Escenas", win.btn_scenes), ("Miniatura", win.btn_thumb),
                      ("Exportar", win._btn_export_tl)):
        chk(b.isHidden(), f"barra de la línea de tiempo sin «{nombre}»")
    chk([a.text() for a in win.menu_cambios_plano.actions() if a.text()] and
        win.btn_more.menu() is not None and win.menu_cambios_plano.menuAction() in win.btn_more.menu().actions(),
        "«✂ Cambios de plano» (cortar donde cambia la imagen) en ⋯ Más")
    chk("broll" in win.ai_panel._tab_of, "B-roll sigue en IA ✨")
    chk(win.btn_undo.isVisible() and win.btn_redo.isVisible(), "↶ Deshacer y ↷ Rehacer a la vista")
    win.ctrl.undo_stack.clear()
    pump(app, 0.2)
    chk(not win.btn_undo.isEnabled() and not win.btn_redo.isEnabled(), "sin cambios: ↶ y ↷ apagados")
    win.ctrl.add_text(0.0, 2.0, "Hola")
    pump(app, 0.2)
    chk(win.btn_undo.isEnabled(), "tras un cambio: ↶ activo")
    win.btn_undo.click()
    pump(app, 0.2)
    chk(win.btn_redo.isEnabled() and not win.ctrl.project.clips, "↶ deshace y ↷ se activa")
    win.btn_redo.click()
    pump(app, 0.2)
    chk(bool(win.ctrl.project.clips), "↷ rehace")
    win.ctrl.undo_stack.undo()
    pump(app, 0.2)

    print("— ningún control repetido a la vista —")
    win.abrir_seccion("audio", "sonoridad")
    win.inspector.ir_a("proyecto")
    pump(app, 0.4)
    lufs = [w for w in win.findChildren(QCheckBox) if w.isVisible() and "LUFS" in w.text()]
    chk(len(lufs) == 1, f"una sola casilla de −14 LUFS a la vista ({[w.text() for w in lufs]})")
    medir = [w for w in win.findChildren(QAbstractButton) if w.isVisible() and "Medir la sonoridad" in w.text()]
    chk(len(medir) == 1, f"un solo «Medir la sonoridad» a la vista ({len(medir)})")
    chk(not win.preview.btn_lufs.isVisible() and win.preview.btn_vol.isVisible(), "el transporte: solo el volumen de "
        "escucha (sin LUFS)")
    vis = [b.text() for b in win.findChildren(QAbstractButton) if b.isVisible() and b.text()]
    for t in ("⬆ Exportar", "✨ B-roll", "🖼 Miniatura"):
        chk(vis.count(t) == 0, f"«{t}» no está repetido a la vista")
    chk(sum(1 for t in vis if t.endswith("Transcripción")) <= 1, "«Transcripción» no sale dos veces")
    nombres_fila = [win._nombre_limpio(D[k]) for k in win.interruptores]
    chk("Audio" not in nombres_fila and "Efectos" not in nombres_fila,
        f"ningún interruptor se llama como una pestaña del Inspector ({nombres_fila})")
    for b_ in (win.clips.btn_descargas_barra, win.descargas_web.btn_descargas_barra):
        t_ = b_.text()
        chk(t_.startswith(("Descargas en cola", "En cola")) and "en cola" in b_.toolTip(),
            f"el contador se llama «Descargas en cola (n)» (o «En cola (n)» si no cabe): «{t_}»")

    print("— una distribución guardada de antes no saca paneles sueltos —")
    # (como la del 21/11: «Voz y texto» a la derecha, en pestaña con el Inspector y abierto en Video horizontal)
    win.addDockWidget(Qt.RightDockWidgetArea, D["voz_texto"])
    win.tabifyDockWidget(D["inspector"], D["voz_texto"])
    D["voz_texto"].show()
    tab = win.workspaces.current
    st = QSettings("EditorIA", "EditorIA")
    st.setValue(f"paneles_pestana/{tab}/voz_texto", "true")
    st.remove(f"paneles_pestana/{tab}/palabras")
    st.remove("paneles/voz_izq_v1")
    pump(app, 0.2)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.3)
    win = MW.MainWindow()
    win.show()
    win.resize(1916, 1000)
    pump(app, 1.2)
    D = win.docks
    chk(win.dockWidgetArea(D["voz_texto"]) == Qt.LeftDockWidgetArea and not D["voz_texto"].isHidden() and
        D["media"] in win.tabifiedDockWidgets(D["voz_texto"]),
        "distribución vieja → «Voz y texto» a la izquierda, en pestaña con Medios y abierto como estaba")
    chk(win.dockWidgetArea(D["palabras"]) == Qt.RightDockWidgetArea and not D["palabras"].isHidden() and
        st.value(f"paneles_pestana/{tab}/palabras") == "true",
        "…y «Palabras clave» a la derecha, abierto (heredó lo de «Voz y texto» en esta pestaña)")
    sueltos = [k for k in win.ABSORBIDOS if not win.docks[k].isHidden()]
    chk(not sueltos, f"al volver a abrir, ningún panel absorbido a la vista {sueltos}")
    win.restoreState(win._default_state, 3)            # (como una distribución vieja que los traía a la vista)
    for k in ("transcript", "material", "voice"):
        win.docks[k].show()
    pump(app, 0.4)
    sueltos = [k for k in win.ABSORBIDOS if not win.docks[k].isHidden()]
    chk(not sueltos, f"aunque una distribución vieja los enseñe, se vuelven a ocultar {sueltos}")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
