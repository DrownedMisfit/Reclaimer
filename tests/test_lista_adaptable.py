"""
▦ PRUEBA de la «lista adaptable» (ui/diseno.py: ListaAdaptable y ColumnasEnlazadas) y de dónde se usa (20/11; lo pidió
el usuario con una captura de «Transiciones y efectos»: una columna estrecha y mucho espacio vacío a la derecha):
  1) columnas según el ancho (1 → 2 → 3), cada columna con su mínimo, ningún nombre cortado (se parten en líneas) y
     nada fuera de lo visible;
  2) el orden de lectura no cambia (izquierda → derecha, luego abajo);
  3) arrastrar (mimeData y banderas), clic derecho (el elemento de debajo, también en la 2.ª columna), doble clic,
     selección y teclado (← → en orden, ↑ ↓ por filas; nunca una cabecera);
  4) 🔗: por separado cada una con su barra; juntas, en proporción;
  5) recuerdo (QSettings): grupos plegados, el elemento elegido, por dónde ibas y el 🔗;
  6) rendimiento con cientos (y miles) de elementos: abrir y redimensionar (medido);
  7) en Reclaimer: «Transiciones y efectos» (cuadrícula y, con mucho ancho, Transiciones | Efectos lado a lado),
     «Sonidos», «Sugerencias» de Limpieza (iconos, filas de 22 px) y el subrayado de la pestaña activa con el acento;
     sin cortes a 200, 360 y 520 px (la misma revisión que test_paneles_sin_cortes).
Ejecutar:  .venv/Scripts/python.exe tests/test_lista_adaptable.py <carpeta_salida>
"""
from __future__ import annotations

import os
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QListWidgetItem, QVBoxLayout, QWidget  # noqa: E402


NOMBRES = ["Disolver", "Fundido a negro", "Destello blanco", "Disolver con grano", "Latigazo",
           "Zoom de entrada muy largo con un nombre que no cabe en una línea", "Barrido", "X",
           "palabra_larguisima_sin_espacios_que_no_cabe_en_ninguna_columna_estrecha"]


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def esperar(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def lista_de_prueba(D, n_grupos=0, por_grupo=0, nombres=NOMBRES, clave=""):
    L = D.ListaAdaptable(clave=clave)
    if n_grupos:
        for g in range(n_grupos):
            cab = L.agregar_grupo(f"Grupo {g}")
            for k in range(por_grupo):
                it = QListWidgetItem(nombres[k % len(nombres)] + f" {g}.{k}")
                it.setData(Qt.UserRole, f"g{g}k{k}")
                L.agregar(it, cab)
    else:
        for k, n in enumerate(nombres):
            it = QListWidgetItem(n)
            it.setData(Qt.UserRole, f"k{k}")
            L.addItem(it)
    return L


def filas_visuales(L):
    """{top: [(fila del modelo, left, right)]} de lo que se ve."""
    filas = {}
    for i in range(L.count()):
        if L.isRowHidden(i):
            continue
        r = L.visualItemRect(L.item(i))
        filas.setdefault(r.top(), []).append((i, r.left(), r.right()))
    return dict(sorted(filas.items()))


def comprobar_sin_cortes(L, donde=""):
    malos = [L.item(i).text() for i in range(L.count()) if not L.isRowHidden(i) and not L.texto_cabe(L.item(i))]
    assert not malos, f"{donde}: nombres cortados {malos[:3]}"


# ---------------------------------------------------------------------------------------------------- 1) y 2)
def prueba_columnas_y_orden(app, D):
    caja = QWidget()
    v = QVBoxLayout(caja)
    v.setContentsMargins(0, 0, 0, 0)
    L = lista_de_prueba(D, nombres=NOMBRES * 4)
    v.addWidget(L)
    caja.show()
    vistas = {}
    for ancho in (160, 200, 360, 520, 800, 1400):
        caja.resize(ancho, 500)
        pump(app)
        filas = filas_visuales(L)
        n = L.columnas()
        vistas[ancho] = n
        por_fila = [len(f) for f in filas.values()]
        assert all(x == n for x in por_fila[:-1]) and 0 < por_fila[-1] <= n, (ancho, n, por_fila)
        assert L.ancho_columna() * n < L.ancho_disponible() + 1, (ancho, L.ancho_columna(), n)
        if n > 1:
            assert L.ancho_columna() >= D.px(150), (ancho, L.ancho_columna())
        der = max(r for f in filas.values() for _i, _l, r in f)
        assert der < L.viewport().width(), (ancho, der, L.viewport().width())
        comprobar_sin_cortes(L, f"{ancho} px")
        orden = [i for f in filas.values() for i, _l, _r in sorted(f, key=lambda x: x[1])]
        assert orden == [i for i in range(L.count())], f"{ancho} px: el orden de lectura cambió"
    assert vistas[160] == 1 and vistas[200] == 1 and vistas[360] == 2 and vistas[520] == 3 and vistas[1400] == 3, \
        vistas
    # un nombre largo ocupa varias líneas y la fila entera mide lo que él (los de su fila, igual de altos)
    caja.resize(360, 500)
    pump(app)
    largo = next(L.item(i) for i in range(L.count()) if L.item(i).text().startswith("Zoom"))
    corto = L.item(L.row(largo) - 1)
    assert L.visualItemRect(largo).height() > D.px(D.ALTO_FILA) + 4, "el nombre largo no se partió en líneas"
    assert L.visualItemRect(corto).height() == L.visualItemRect(largo).height(), "la fila no tiene un solo alto"
    print(f"✓ 1) columnas según el ancho {vistas} (mín. {D.px(150)} px cada una), ningún nombre cortado "
          "(los largos en varias líneas, también una palabra sin espacios) y nada fuera de lo visible")
    print("✓ 2) el orden de lectura no cambia (izquierda → derecha, luego abajo) a ningún ancho")
    caja.deleteLater()


# ---------------------------------------------------------------------------------------------------- 3)
def prueba_uso(app, D):
    caja = QWidget()
    v = QVBoxLayout(caja)
    v.setContentsMargins(0, 0, 0, 0)
    L = lista_de_prueba(D, n_grupos=3, por_grupo=7)
    v.addWidget(L)
    caja.resize(560, 600)
    caja.show()
    pump(app)
    assert L.columnas() == 3
    dobles, clics, menus = [], [], []
    L.itemDoubleClicked.connect(lambda it: dobles.append(it.data(Qt.UserRole)))
    L.itemClicked.connect(lambda it: clics.append(it.data(Qt.UserRole)))
    L.setContextMenuPolicy(Qt.CustomContextMenu)
    L.customContextMenuRequested.connect(lambda pos: menus.append(L.itemAt(pos).data(Qt.UserRole)
                                                                  if L.itemAt(pos) else None))
    cab0 = L.item(0)
    assert L.es_grupo(cab0) and not (cab0.flags() & Qt.ItemIsSelectable) and not (cab0.flags() & Qt.ItemIsDragEnabled)
    it = L.item(2)                                      # (2.ª columna de la primera fila)
    centro = L.visualItemRect(it).center()
    QTest.mouseClick(L.viewport(), Qt.LeftButton, Qt.NoModifier, centro)
    assert L.currentItem() is it and it.isSelected() and clics[-1] == "g0k1", (clics, L.currentRow())
    QTest.mouseDClick(L.viewport(), Qt.LeftButton, Qt.NoModifier, centro)
    assert dobles and dobles[-1] == "g0k1", dobles
    L.customContextMenuRequested.emit(centro)
    assert menus[-1] == "g0k1", menus
    assert L.dragEnabled() or True                      # (lo decide quien la usa: ver _FxList y _SoundTree)
    print("✓ 3) clic (selecciona), doble clic y clic derecho dan el elemento de debajo, también en la 2.ª columna")
    # teclado: ← → en orden de lectura; ↑ ↓ por filas; nunca una cabecera
    L.setFocus()
    L.setCurrentItem(L.item(1))                         # g0k0 (fila 0, columna 0)

    def tecla(k):
        QTest.keyClick(L, k)
        return L.currentItem().data(Qt.UserRole)
    assert tecla(Qt.Key_Right) == "g0k1" and tecla(Qt.Key_Right) == "g0k2" and tecla(Qt.Key_Right) == "g0k3", \
        "→ sigue el orden de lectura (y salta a la fila de abajo)"
    assert tecla(Qt.Key_Left) == "g0k2"
    L.setCurrentItem(L.item(1))
    assert tecla(Qt.Key_Down) == "g0k3", "↓ = la de abajo, misma columna"
    assert tecla(Qt.Key_Down) == "g0k6"
    assert tecla(Qt.Key_Down) == "g1k0", "↓ salta la cabecera del grupo siguiente"
    assert tecla(Qt.Key_Up) == "g0k6" and tecla(Qt.Key_Up) == "g0k3"
    L.setCurrentItem(L.item(7))                         # g0k6 (último del grupo 0)
    assert tecla(Qt.Key_Right) == "g1k0", "→ salta la cabecera"
    assert tecla(Qt.Key_Home) == "g0k0", "Inicio: el primero que se puede elegir (no la cabecera)"
    # una sola columna: ↑ ↓ como la lista de siempre
    caja.resize(180, 600)
    pump(app)
    assert L.columnas() == 1
    L.setCurrentItem(L.item(1))
    assert tecla(Qt.Key_Down) == "g0k1" and tecla(Qt.Key_Up) == "g0k0"
    print("✓ 3) teclado: ← → en orden de lectura, ↑ ↓ por filas (con una columna, como la lista de siempre); nunca "
          "una cabecera")
    # clic en una cabecera: pliega y abre su grupo
    caja.resize(560, 600)
    pump(app)
    cab1 = next(L.item(i) for i in range(L.count()) if L.item(i).text() == "Grupo 1")
    QTest.mouseClick(L.viewport(), Qt.LeftButton, Qt.NoModifier, L.visualItemRect(cab1).center())
    pump(app)
    assert all(m.isHidden() for m in L.miembros(cab1)) and not cab1.isSelected()
    L.filtrar("1.3")
    assert [L.item(i).data(Qt.UserRole) for i in range(L.count()) if not L.isRowHidden(i) and
            not L.es_grupo(L.item(i))] == ["g1k3"], "buscar enseña lo que coincide aunque su grupo esté plegado"
    assert L.isRowHidden(0) and not cab1.isHidden(), "las cabeceras sin nada a la vista se esconden"
    L.filtrar("")
    assert all(m.isHidden() for m in L.miembros(cab1)) and not any(m.isHidden() for m in L.miembros(L.item(0)))
    QTest.mouseClick(L.viewport(), Qt.LeftButton, Qt.NoModifier, L.visualItemRect(cab1).center())
    pump(app)
    assert not any(m.isHidden() for m in L.miembros(cab1))
    print("✓ 3) cabeceras de grupo: toda la fila, no se eligen ni se arrastran; clic = plegar/abrir; buscar filtra")
    caja.deleteLater()


# ---------------------------------------------------------------------------------------------------- 4)
def prueba_enlace(app, D):
    st = QSettings("EditorIA", "EditorIA")
    st.remove("prueba/columnas/enlazadas")
    st.remove("prueba/columnas/desplazamiento")

    def contenido(n):
        w = QWidget()
        v = QVBoxLayout(w)
        for k in range(n):
            lb = QLabel(f"línea {k}")
            lb.setFixedHeight(30)
            v.addWidget(lb)
        return w
    C = D.ColumnasEnlazadas("prueba/columnas", ["Transiciones", "Efectos"])
    C.poner_contenido(0, contenido(60))
    C.poner_contenido(1, contenido(120))
    C.resize(800, 400)
    C.show()
    esperar(app, 0.15)
    a, b = (z.verticalScrollBar() for z in C.zonas)
    assert a.maximum() > 0 and b.maximum() > a.maximum(), (a.maximum(), b.maximum())
    assert not C.enlazadas() and C.boton_enlace.nombre_icono() == "unlink" and C.boton_enlace.toolTip()
    a.setValue(a.maximum() // 2)
    assert b.value() == 0, "por separado: cada una con su barra"
    C.boton_enlace.click()
    assert C.enlazadas() and C.boton_enlace.nombre_icono() == "link"
    a.setValue(a.maximum())
    assert abs(b.value() - b.maximum()) <= 1, (b.value(), b.maximum())
    b.setValue(b.maximum() // 4)
    assert abs(a.value() / a.maximum() - 0.25) < 0.03, (a.value(), a.maximum())
    print("✓ 4) 🔗: por separado cada una con su barra; juntas, se desplazan en proporción (icono y tooltip cambian)")
    esperar(app, 0.6)                                   # (el desplazamiento se guarda al parar)
    C.deleteLater()
    pump(app)
    C2 = D.ColumnasEnlazadas("prueba/columnas", ["Transiciones", "Efectos"])
    C2.poner_contenido(0, contenido(60))
    C2.poner_contenido(1, contenido(120))
    C2.resize(800, 400)
    C2.show()
    esperar(app, 0.4)
    a2, b2 = (z.verticalScrollBar() for z in C2.zonas)
    assert C2.enlazadas(), "el 🔗 se recuerda"
    assert abs(a2.value() / a2.maximum() - 0.25) < 0.05, (a2.value(), a2.maximum())
    print("✓ 5) ColumnasEnlazadas recuerda el 🔗 y por dónde ibas en cada columna")
    C2.deleteLater()


# ---------------------------------------------------------------------------------------------------- 5)
def prueba_recuerdo(app, D):
    st = QSettings("EditorIA", "EditorIA")
    for k in ("plegados", "actual", "desplazamiento"):
        st.remove(f"listas/prueba_recuerdo/{k}")
    L = lista_de_prueba(D, n_grupos=6, por_grupo=12, clave="prueba_recuerdo")
    L.resize(400, 300)
    L.show()
    pump(app)
    L.plegar(L.item(0), True)                           # «Grupo 0» plegado
    pump(app)
    elegido = next(L.item(i) for i in range(L.count()) if L.item(i).data(Qt.UserRole) == "g3k5")
    L.setCurrentItem(elegido)
    pump(app)
    sb = L.verticalScrollBar()
    assert sb.maximum() > 0
    sb.setValue(sb.maximum() // 2)
    esperar(app, 0.6)
    L.deleteLater()
    pump(app)
    L2 = lista_de_prueba(D, n_grupos=6, por_grupo=12, clave="prueba_recuerdo")
    L2.resize(400, 300)
    L2.show()
    esperar(app, 0.2)
    assert L2.item(0).data(D.ROL_PLEGADO) and all(m.isHidden() for m in L2.miembros(L2.item(0))), \
        "el grupo plegado sigue plegado"
    assert L2.currentItem() is not None and L2.currentItem().data(Qt.UserRole) == "g3k5", "el elegido se recuerda"
    sb2 = L2.verticalScrollBar()
    assert sb2.maximum() > 0 and abs(sb2.value() / sb2.maximum() - 0.5) < 0.08, (sb2.value(), sb2.maximum())
    print("✓ 5) ListaAdaptable recuerda los grupos plegados, el elemento elegido y por dónde ibas")
    L2.deleteLater()


# ---------------------------------------------------------------------------------------------------- 6)
def prueba_rendimiento(app, D):
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(48, 27)
    pm.fill(Qt.gray)
    ic = QIcon(pm)
    resultados = []
    for n_total, por_grupo, con_iconos in ((500, 50, True), (3000, 100, False)):
        caja = QWidget()
        v = QVBoxLayout(caja)
        v.setContentsMargins(0, 0, 0, 0)
        t0 = time.perf_counter()
        L = D.ListaAdaptable()
        if con_iconos:
            L.setIconSize(pm.size())
        L.setUpdatesEnabled(False)
        for g in range(n_total // por_grupo):
            cab = L.agregar_grupo(f"Grupo {g}")
            for k in range(por_grupo):
                it = QListWidgetItem(NOMBRES[k % len(NOMBRES)] + f" {g}.{k}")
                if con_iconos:
                    it.setIcon(ic)
                L.agregar(it, cab)
        L.setUpdatesEnabled(True)
        v.addWidget(L)
        caja.resize(420, 700)
        caja.show()
        pump(app, 3)
        caja.grab()
        abrir = time.perf_counter() - t0
        tiempos = []
        for ancho in list(range(300, 1300, 50)) + list(range(1300, 300, -50)):
            t1 = time.perf_counter()
            caja.resize(ancho, 700)
            pump(app, 2)
            caja.grab()
            tiempos.append(time.perf_counter() - t1)
        esperar(app, 0.2)                               # (con miles, se coloca al parar de arrastrar)
        t2 = time.perf_counter()
        caja.resize(777, 700)
        while abs(L.ancho_disponible() - (L.ancho_columna() * L.columnas() + 1)) > L.columnas() + 1 and \
                time.perf_counter() - t2 < 2:
            app.processEvents()
        caja.grab()
        al_parar = time.perf_counter() - t2
        comprobar_sin_cortes(L, f"{n_total} elementos")
        medio, peor = sum(tiempos) / len(tiempos), max(tiempos)
        colocar = sorted(L.medidas_colocar)[len(L.medidas_colocar) // 2]
        resultados.append((n_total, abrir, medio, peor, colocar))
        print(f"  · {n_total}: al soltar el borde, colocado y pintado en {al_parar * 1000:.0f} ms")
        print(f"  · {n_total} elementos{' con miniatura' if con_iconos else ''}: abrir {abrir * 1000:.0f} ms · "
              f"redimensionar {medio * 1000:.1f} ms de media (peor {peor * 1000:.0f} ms, {len(tiempos)} anchos) · "
              f"calcular columnas {colocar * 1000:.1f} ms")
        caja.deleteLater()
        pump(app)
    (n1, ab1, m1, p1, _c1), (n2, ab2, m2, p2, _c2) = resultados
    assert ab1 < 0.6 and m1 < 0.05, f"{n1} elementos: abrir {ab1:.3f} s, redimensionar {m1:.3f} s"
    assert ab2 < 2.5 and m2 < 0.06, f"{n2} elementos: abrir {ab2:.3f} s, redimensionar {m2:.3f} s"
    print(f"✓ 6) rendimiento: {n1} elementos se abren en {ab1 * 1000:.0f} ms y se redimensionan en "
          f"{m1 * 1000:.1f} ms de media; {n2}, en {ab2 * 1000:.0f} ms y {m2 * 1000:.1f} ms")
    return resultados


# ---------------------------------------------------------------------------------------------------- 7) en Reclaimer
def listas_de(raiz, D):
    return [w for w in raiz.findChildren(D.ListaAdaptable) if w.isVisibleTo(raiz)]


def prueba_en_reclaimer(app, D, out):
    import test_paneles_sin_cortes as SC
    from editoria.ui import theme as T
    from editoria.ui.common import EFFECT_MIME, MEDIA_MIME
    from editoria.ui.main_window import MainWindow
    T.apply_dark_theme(app)
    SC.contar_pintados()
    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    esperar(app, 0.6)
    fx = win.effects
    # (clic derecho: el menú ⭐ se apunta en vez de abrirse —con PySide 6.11, QMenu.exec no se puede sustituir—)
    menus = []
    fx._star_menu = lambda key, _pos: menus.append(key)
    try:
        # ---- Transiciones y efectos
        d = win.docks["effects"]
        d.setFloating(True)
        d.show()
        tl = fx.trans_list
        assert isinstance(tl, D.ListaAdaptable) and isinstance(fx.mem_list, D.ListaAdaptable)
        cols = {}
        for ancho in (200, 360, 520):
            d.resize(ancho, 900)
            d.raise_()
            esperar(app, 0.25)
            SC.abrir_todo(d)
            esperar(app, 0.2)
            assert not fx._modo_ancho
            cols[ancho] = (d.width(), tl.columnas())
            cortes, vistos = {}, set()
            SC.revisar(d, cortes, vistos, f"Transiciones y efectos {ancho} px")
            assert not cortes, "\n".join(cortes.values())
            for L in listas_de(d, D):
                comprobar_sin_cortes(L, f"Transiciones y efectos {ancho} px")
            d.grab().save(os.path.join(out, f"efectos_{ancho}.png"))
        assert cols[520][1] >= 2, cols
        print(f"✓ 7) «Transiciones y efectos» a 200/360/520 px: columnas de transiciones "
              f"{[c[1] for c in cols.values()]}, sin cortes")
        # arrastrar, clic derecho y doble clic en la cuadrícula
        d.resize(520, 900)
        esperar(app, 0.3)
        assert tl.dragEnabled() and tl.item(1).flags() & Qt.ItemIsDragEnabled
        md = tl.mimeData([tl.item(1)])
        assert bytes(md.data(EFFECT_MIME)).decode() == "trans:" + tl.item(1).data(Qt.UserRole)
        segunda = tl.item(1)
        r = tl.visualItemRect(segunda)
        assert r.left() > 0, "la 2.ª transición está en la 2.ª columna"
        tl.customContextMenuRequested.emit(r.center())
        assert menus and menus[-1] == "trans:" + segunda.data(Qt.UserRole), menus
        puestas = []
        fx.apply_transition = lambda remove=False: puestas.append(tl.currentItem().data(Qt.UserRole))
        QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, r.center())   # (Qt: clic y luego doble clic)
        QTest.mouseDClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, r.center())
        assert puestas == [segunda.data(Qt.UserRole)], puestas
        del fx.apply_transition
        print("✓ 7) transiciones: arrastrar (mimeData «trans:…»), clic derecho (⭐) y doble clic (poner) en la "
              "2.ª columna")
        # vista previa al pasar el ratón (itemEntered): la animación de esa transición
        from editoria.ui import fx_preview_ui as FXP
        QTest.mouseMove(tl.viewport(), r.center())
        pump(app)
        if not FXP.popup().isVisible():                 # (sin ratón de verdad, Qt no siempre manda «entered»)
            tl.itemEntered.emit(segunda)
            pump(app)
        assert FXP.popup().isVisible() and FXP.popup().key == ("trans", segunda.data(Qt.UserRole)), FXP.popup().key
        FXP.hide()
        print("✓ 7) al pasar el ratón por una transición de la 2.ª columna, su vista previa animada")
        # lado a lado con mucho ancho (y al volver, cada sección abierta o cerrada como estaba, sin tocar lo recordado)
        st = QSettings("EditorIA", "EditorIA")
        abiertas0 = [s_.is_open() for s_ in fx.tabs.secciones()]
        recordado0 = {k: st.value(k) for k in st.allKeys() if k.startswith("secciones/efectos2/")}
        d.resize(1100, 900)
        esperar(app, 0.4)
        assert fx._modo_ancho and fx._lado is not None and fx._lado.isVisible(), d.width()
        izq = fx._lado.contenido(0)
        for clave in ("trans", "filtros", "figuras"):
            assert izq.isAncestorOf(fx._huecos[clave]), f"lado a lado, «{clave}» va en la columna izquierda"
        assert fx.tabs.parentWidget() is fx._lado.contenido(1)
        assert not fx.tabs.isTabVisible(fx._indice_trans())
        assert all(not fx.tabs.isTabVisible(fx._indice_de(t)) for _c, t in fx.BAJO_TRANS)
        t_izq, t_der = fx._lado.titulos
        assert t_izq.mapTo(fx._lado, t_izq.rect().topLeft()).x() + t_izq.contentsMargins().left() >= D.px(D.M2) and \
            t_izq.contentsMargins().left() == t_der.contentsMargins().left(), "los dos títulos con la misma sangría"
        assert all(z.verticalScrollBar() is not None for z in fx._lado.zonas) and len(fx._lado.zonas) == 2
        assert fx._lado.boton_enlace.isVisible() and fx._lado.boton_enlace.toolTip()
        assert tl.columnas() >= 2, tl.columnas()
        comprobar_sin_cortes(tl, "lado a lado")
        d.grab().save(os.path.join(out, "efectos_1100_lado_a_lado.png"))
        d.resize(400, 900)
        esperar(app, 0.4)
        assert not fx._modo_ancho and fx.tabs.isTabVisible(fx._indice_trans())
        assert fx._huecos["trans"].parentWidget() is fx.tabs.widget(fx._indice_trans())
        for clave, t in fx.BAJO_TRANS:
            k = fx._indice_de(t)
            assert fx.tabs.isTabVisible(k) and fx._huecos[clave].parentWidget() is fx.tabs.widget(k), clave
        assert fx.tabs.parentWidget() is fx and not fx._lado.isVisible()
        assert [s_.is_open() for s_ in fx.tabs.secciones()] == abiertas0, "al estrechar, las secciones como estaban"
        assert {k: st.value(k) for k in st.allKeys() if k.startswith("secciones/efectos2/")} == recordado0, \
            "lo recordado de las secciones no se pisa"
        print("✓ 7) con mucho ancho, Transiciones (+ Filtros y Figuras debajo) | Efectos lado a lado, cada una con su "
              "barra y 🔗, títulos con la misma sangría; al estrechar, una debajo de otra con cada sección como estaba "
              "y sin tocar lo recordado")
        d.setFloating(False)

        # ---- Sonidos
        ds = win.docks["sounds"]
        ds.setFloating(True)
        ds.show()
        tree = fx.tree
        assert isinstance(tree, D.ListaAdaptable) and tree.topLevelItemCount() > 0
        for ancho in (200, 360, 520):
            ds.resize(ancho, 800)
            ds.raise_()
            esperar(app, 0.3)
            cortes, vistos = {}, set()
            SC.revisar(ds, cortes, vistos, f"Sonidos {ancho} px")
            assert not cortes, "\n".join(cortes.values())
            comprobar_sin_cortes(tree, f"Sonidos {ancho} px")
            ds.grab().save(os.path.join(out, f"sonidos_{ancho}.png"))
        assert tree.columnas() >= 2, tree.columnas()
        if not tree.topLevelItem(0).isExpanded():       # (plegado se recuerda: el grupo, abierto para probarlo)
            tree.topLevelItem(0).setExpanded(True)
            esperar(app, 0.3)
        hoja = tree.topLevelItem(0).child(0)
        assert not hoja.isHidden() and not tree.visualItemRect(hoja).isEmpty(), "el primer sonido, a la vista"
        assert hoja.data(0, Qt.UserRole).startswith("sfx:") and hoja.text(1), "data(0, rol) y text(1) de siempre"
        assert hoja.toolTip() == hoja.text(1), "«para qué», en el tooltip"
        assert tree.dragEnabled() and hoja.flags() & Qt.ItemIsDragEnabled
        assert not (tree.topLevelItem(0).flags() & Qt.ItemIsDragEnabled)
        md = tree.mimeData([hoja])
        assert bytes(md.data(MEDIA_MIME)).decode() in win.ctrl.project.media, "arrastrar = importar y su id"
        tree.customContextMenuRequested.emit(tree.visualItemRect(hoja).center())
        assert menus and menus[-1] == hoja.data(0, Qt.UserRole), menus
        escuchados = []
        fx.player.setSource = lambda url: escuchados.append(url.toLocalFile())
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, tree.visualItemRect(hoja).center())
        assert escuchados, "clic = escuchar"
        del fx.player.setSource
        print(f"✓ 7) «Sonidos» a 200/360/520 px sin cortes ({tree.columnas()} columnas a 520 px); clic = escuchar, "
              "arrastrar, clic derecho (⭐) y la forma de usar de antes")
        ds.setFloating(False)

        # ---- Sugerencias (Limpieza)
        from types import SimpleNamespace
        from editoria.core.model import SUG_PENDING, SUG_REJECTED
        from editoria.ui import voice_panel as VP
        vp = win.voice
        da = win.abrir_seccion("audio", "limpieza")
        for i in range(vp.tabs.count()):
            if vp.tabs.tabText(i) == "Sugerencias":
                vp.tabs.setCurrentIndex(i)
        da.setFloating(True)
        da.show()
        assert [b.nombre_icono() for b in (vp.btn_listen, vp.btn_apply, vp.btn_reject, vp.btn_restore)] == \
            ["play", "check", "x", "rotate-ccw"]
        assert vp.btn_quick.text() == "Revisión guiada" and not vp.btn_quick.icon().isNull(), "con su nombre"
        for b in (vp.btn_listen, vp.btn_apply, vp.btn_reject, vp.btn_restore, vp.btn_quick, vp.btn_apply_all):
            assert b.toolTip().strip(), b
        caja = vp.tree.parentWidget()
        from PySide6.QtWidgets import QAbstractButton
        textos = [w.text() for w in caja.findChildren(QLabel) + caja.findChildren(QAbstractButton)
                  if w.isVisibleTo(caja)]
        assert not [t for t in textos if any(e in t for e in "▶✓✗↺↶")], textos
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtWidgets import QStyleOptionViewItem
        da.resize(360, 900)
        esperar(app, 0.3)
        vp._list_timer.stop()
        vp.tree.addTopLevelItem(QTreeWidgetItem(["0:01", "Muletilla «eh»", "Pendiente"]))
        vp.tree.doItemsLayout()                         # (sin dejar que la lista se rehaga: la fila de prueba)
        alto = vp.tree.itemDelegate().sizeHint(QStyleOptionViewItem(), vp.tree.indexFromItem(
            vp.tree.topLevelItem(0))).height()
        visto = vp.tree.visualItemRect(vp.tree.topLevelItem(0)).height()
        assert alto == D.px(D.ALTO_FILA) and (visto == alto or not vp.tree.isVisible()), (alto, visto,
                                                                                           vp.tree.isVisible())
        sug = lambda st_, kind="filler": SimpleNamespace(id="s", status=st_, kind=kind, cuttable=True, label="x",  # noqa: E731
                                                          detail="", media_id="m")
        vp._selected = lambda: [sug(SUG_REJECTED)]
        vp._on_selection()
        assert vp.btn_reject.nombre_icono() == "undo-2" and vp.btn_reject.toolTip() == VP.TIP_RECUPERAR
        vp._selected = lambda: [sug(SUG_PENDING, "retake")]
        vp._on_selection()
        assert vp.btn_reject.nombre_icono() == "x" and vp.btn_apply.toolTip() == VP.TIP_ELEGIR_TOMA and \
            vp.btn_listen.toolTip() == VP.TIP_COMPARAR
        assert (vp.btn_apply.nombre_icono(), vp.btn_listen.nombre_icono()) == ("list-checks", "columns-2"), \
            "cada acción con su propio icono"
        vp._selected = lambda: [sug(SUG_PENDING)]
        vp._on_selection()
        assert (vp.btn_apply.nombre_icono(), vp.btn_listen.nombre_icono()) == ("check", "play")
        del vp._selected
        vp._rebuild_list()
        for ancho in (200, 360, 520):
            da.resize(ancho, 900)
            da.raise_()
            esperar(app, 0.3)
            cortes, vistos = {}, set()
            SC.revisar(da, cortes, vistos, f"Limpieza → Sugerencias {ancho} px")
            assert not cortes, "\n".join(cortes.values())
            caja.grab().save(os.path.join(out, f"sugerencias_{ancho}.png"))
        print("✓ 7) «Sugerencias»: iconos monocromos (▶ ✓ ✗ ↺ → play, check, x/undo, rotate) con su tooltip, filas de "
              f"{D.px(D.ALTO_FILA)} px, todas las acciones; sin cortes a 200/360/520 px")
        da.setFloating(False)

        # ---- subrayado de la pestaña activa = el acento
        bar = win.workspaces.bar
        assert "#e8833a" not in bar.styleSheet().lower() and T.ACCENT.lower() in bar.styleSheet().lower()
        antes = T.ACCENT
        clave0 = str(QSettings("EditorIA", "EditorIA").value(T.ACENTO_KEY, "")) or None
        for k in T.ACENTOS:
            T.poner_acento(k, guardar=False)
            if T.ACCENT.lower() != antes.lower():
                break
        assert T.ACCENT.lower() in bar.styleSheet().lower() and antes.lower() not in bar.styleSheet().lower(), \
            (T.ACCENT, bar.styleSheet())
        print(f"✓ 7) la pestaña activa de arriba se subraya con el acento ({antes} → {T.ACCENT}, al momento)")
        if clave0 in T.ACENTOS:
            T.poner_acento(clave0, guardar=False)
    finally:
        del fx._star_menu
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()


def main():
    import faulthandler
    faulthandler.dump_traceback_later(420, exit=True)   # (si algo se quedara esperando, no ocupa el turno 14 min)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_lista_adaptable")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import diseno as D
    from editoria.ui import theme as T
    T.apply_dark_theme(app)
    prueba_columnas_y_orden(app, D)
    prueba_uso(app, D)
    prueba_enlace(app, D)
    prueba_recuerdo(app, D)
    prueba_rendimiento(app, D)
    prueba_en_reclaimer(app, D, out)
    print("TODO OK")


if __name__ == "__main__":
    main()
