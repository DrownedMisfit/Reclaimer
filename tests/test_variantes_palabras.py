"""
Variantes de TODA palabra clave (20/11; el usuario: «a veces da "GTA 5" y a veces "GTA cinco"… que valga para
cualquier tipo de palabra clave»). Casos que SÍ se unen y casos que NO:
  · números hasta 9999 en palabras (español e inglés), sin espacios, apóstrofos, «&»/«and»/«y», artículo inicial;
  · siglas de un nombre conocido (un solo candidato), plurales y grafías de palabras corrientes, errores de Whisper;
  · NO: «Xbox Series X» ≠ «Xbox 10», «Halo» ≠ «Hola», «Mario» ≠ «María», «Doom» ≠ «Dome» (salvo «Unir con…»),
    sagas distintas con número, «un segundo» de tiempo;
  · «Separar…» y «Unir con…» se recuerdan (glosario) y salen en el clic derecho de «Dijiste…» y 🔑 Palabras clave;
  · el tooltip dice «También dicho: …»;
  · rendimiento: una narración de 2 h → find_mentions < 150 ms.
Ejecutar (con el turno):  turno.py tests/test_variantes_palabras.py
"""
from __future__ import annotations

import os
import random
import sys
import time


# 🔒 datos de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar)
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
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.ai import keyword_glossary as KG  # noqa: E402
from editoria.ai import mentions as M  # noqa: E402
from editoria.ai.keyword_variants import Variantes  # noqa: E402
from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core.model import Project  # noqa: E402

FALLOS = []
VACIO = {"si": {}, "no": [], "web": {}}


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def _palabras(texto: str) -> list:
    """0,35 s por palabra y 0,05 s entre ellas. «|» = pausa de 1,2 s."""
    out, t = [], 0.0
    for tok in texto.split():
        if tok == "|":
            t += 1.2
            continue
        out.append([round(t, 2), round(t + 0.35, 2), tok, 0.9])
        t += 0.4
    return out


def _fm(texto: str, **kw) -> list:
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(texto)}}
    kw.setdefault("glossary", dict(VACIO))
    return M.find_mentions(p, **kw)


def _t(res, term):
    return next((m for m in res if m["term"] == term), None)


def _terms(res):
    return [(m["term"], m["count"]) for m in res]


def main():
    print("— 1–3. claves: números, sin espacios, apóstrofos, «&», artículo —")
    si = [("GTA 5", "gta cinco"), ("GTA V", "gta5"), ("Cyberpunk 2077", "Cyberpunk dos mil setenta y siete"),
          ("Halo 23", "Halo veintitrés"), ("Battlefield 2042", "Battlefield two thousand forty two"),
          ("FIFA 2020", "FIFA twenty twenty"), ("Resident Evil 31", "Resident Evil treinta y uno"),
          ("Top 100", "Top cien"), ("Final Fantasy XVI", "Final Fantasy dieciséis"),
          ("Age 1998", "Age mil novecientos noventa y ocho"), ("Saga 1984", "Saga nineteen eighty four"),
          ("Juego 205", "Juego two hundred and five"), ("Juego 101", "Juego ciento uno"),
          ("Spider-Man", "spiderman"), ("Spider Man", "Spider-Man"), ("Assassin's Creed", "Assassins Creed"),
          ("Ratchet & Clank", "Ratchet and Clank"), ("Ratchet & Clank", "Ratchet y Clank"),
          ("The Witcher", "Witcher"), ("El Padrino", "Padrino"), ("Halo segundo", "Halo 2"),
          ("Baldur's Gate 3", "baldurs gate tres")]
    for a, b in si:
        chk(KF.compacta(a) == KF.compacta(b), f"SÍ: «{a}» = «{b}» ({KF.compacta(a)!r})")
    no = [("Xbox Series X", "Xbox 10"), ("Halo 2", "Halo 3"), ("La X", "X"), ("un segundo", "segundo"),
          ("Halo 2", "Gears 2"), ("Resident Evil 4", "Resident Evil 5"), ("Dos Mundos", "2 Mundos 2")]
    for a, b in no:
        chk(KF.compacta(a) != KF.compacta(b), f"NO: «{a}» ≠ «{b}» ({KF.compacta(a)!r} / {KF.compacta(b)!r})")
    chk(KF.canon("el segundo") == "el segundo" and KF.canon("un segundo") == "un segundo",
        f"«el segundo» y «un segundo» no son números ({KF.canon('el segundo')!r})")
    chk(KF.leer_numero("dos mil setenta y siete".split()) == (2077, 5) and KF.leer_numero(["hola"]) is None,
        "leer_numero: «dos mil setenta y siete» → 2077 (5 palabras); «hola» → nada")
    carpetas = [{"name": "Spider-Man", "label": "Spider-Man", "keys": KF.folder_keys("Spider-Man"), "path": "s"},
                {"name": "The Witcher", "label": "The Witcher", "keys": KF.folder_keys("The Witcher"), "path": "w"}]
    chk((KF.match("spiderman", carpetas) or {}).get("path") == "s"
        and (KF.match("Witcher", carpetas) or {}).get("path") == "w", "KF.match: «spiderman» y «Witcher» → su carpeta")

    print("— 4–6. agrupador: siglas, plurales y grafías, errores de Whisper —")
    V = Variantes({"Zombis": 2, "Halo": 2, "Fortnite": 2, "Mario": 2, "Doom": 2, "Dark Souls": 2,
                   "Death Stranding": 2, "Dead Space": 2, "Xbox Series X": 2, "Xbox": 2, "Destiny": 2,
                   "Call of Duty": 2, "GTA": 2, "Grand Theft Auto": 2, "Elden Ring": 2, "League of Legends": 2,
                   "Minecraft": 2}, M._comun_exacta)
    pares_si = [("Fortnight", "Fortnite"), ("Elder Ring", "Elden Ring"), ("zombie", "Zombis"),
                ("zombies", "Zombis"), ("Zombi", "Zombis"), ("GTA 5", "Grand Theft Auto V"),
                ("Fortnight 2", "Fortnite 2")]
    for a, b in pares_si:
        chk(V.clave(a) == V.clave(b), f"SÍ: «{a}» = «{b}»")
    chk(V.clave("COD", sigla=True) == V.clave("Call of Duty"), "SÍ: «COD» (en mayúsculas) = «Call of Duty»")
    chk(V.clave("LOL", sigla=True) == V.clave("League of Legends"), "SÍ: «LOL» = «League of Legends»")
    chk(V.nombre_de(V.clave("Fortnight")) == "Fortnite", "el grupo de «Fortnight» se llama «Fortnite»")
    pares_no = [("Hola", "Halo"), ("María", "Mario"), ("Dome", "Doom"), ("Xbox 10", "Xbox Series X"),
                ("Halo 2", "Halo 3"), ("Destino", "Destiny"), ("Fortnite 2", "Fortnite 3"), ("Minecraft", "Mario")]
    for a, b in pares_no:
        chk(V.clave(a) != V.clave(b), f"NO: «{a}» ≠ «{b}»")
    chk(V.clave("DS", sigla=True) == "ds", "NO: «DS» con tres candidatos (Dark Souls, Death Stranding, Dead Space)")
    chk(V.clave("cod") != V.clave("Call of Duty"), "NO: «cod» en minúsculas no es sigla")
    V2 = Variantes({"Doom": 2}, M._comun_exacta, unir={"Dome": "Doom"})
    chk(V2.clave("Dome") == V2.clave("Doom"), "«Dome» = «Doom» solo si se unió a mano (Unir con…)")

    print("— «Dijiste…»: lo que SÍ se une —")
    res = _fm("me gusta Spider-Man mucho y el spiderman nuevo y luego Spider Man otra vez")
    g = _t(res, "Spider-Man")
    chk(g is not None and g["count"] == 3, f"«Spider-Man», «spiderman», «Spider Man» → un grupo ×3 ({_terms(res)})")
    chk(g is not None and "spiderman" in g["variantes"], f"…con «spiderman» en sus variantes ({g and g['variantes']})")
    res = _fm("ayer jugué Fortnite con amigos y luego Fortnight otra vez")
    g = _t(res, "Fortnite")
    chk(g is not None and g["count"] == 2 and _t(res, "Fortnight") is None,
        f"«Fortnight» (error de Whisper) → «Fortnite» ×2 ({_terms(res)})")
    chk(g is not None and g["variantes"] == ["Fortnight"], f"…variantes = [Fortnight] ({g and g['variantes']})")
    res = _fm("por fin salió Cyberpunk dos mil setenta y siete. | Y Cyberpunk 2077 sigue")
    chk(_t(res, "Cyberpunk 2077") is not None and _t(res, "Cyberpunk 2077")["count"] == 2,
        f"«Cyberpunk dos mil setenta y siete.» (cerrando la frase) = «Cyberpunk 2077» ({_terms(res)})")
    res = _fm("ya salió Cyberpunk dos mil setenta y siete por fin", extra_terms=["Cyberpunk 2077"])
    chk(_t(res, "Cyberpunk 2077") is not None, f"…y a media frase si es tu carpeta «Cyberpunk 2077» ({_terms(res)})")
    res = _fm("ayer jugué Halo tres con mi primo y GTA cinco es increíble")
    chk(_t(res, "Halo 3") is not None and _t(res, "GTA 5") is not None,
        f"número pequeño en palabras a media frase sí es la entrega («Halo tres con…») ({_terms(res)})")
    res = _fm("Jugué Fortnight ayer. | Fortnite es bueno.")
    chk(_t(res, "Fortnite") is not None and _t(res, "Fortnite")["count"] == 2, f"«Jugué Fortnight» (verbo al empezar) "
        f"→ «Fortnite» ({_terms(res)})")
    res = _fm("Jugué Maincraft ayer. | Minecraft es bueno.")
    chk(_t(res, "Minecraft") is not None and _t(res, "Minecraft")["count"] == 2, f"«Jugué Maincraft» → «Minecraft» "
        f"({_terms(res)})")
    res = _fm("The Last of Us dos es duro. | Last of Us Parte dos también. | The Last of Us 2.")
    chk(_t(res, "The Last of Us 2") is not None and _t(res, "The Last of Us 2")["count"] == 3,
        f"«Last of Us Parte dos» → «The Last of Us 2» ({_terms(res)})")
    res = _fm("ayer vi Elder Ring en casa y luego Elden Ring en la tele")
    chk(_t(res, "Elden Ring") is not None and _t(res, "Elden Ring")["count"] == 2, f"«Elder Ring» → «Elden Ring» "
        f"({_terms(res)})")
    res = _fm("juego COD todos los días y también Call of Duty en casa")
    chk(_t(res, "Call of Duty") is not None and _t(res, "Call of Duty")["count"] == 2,
        f"«COD» = «Call of Duty» ({_terms(res)})")
    res = _fm("me gusta Witcher mucho y también The Witcher tres con mods")
    chk(_t(res, "The Witcher") is not None and _t(res, "The Witcher 3") is not None,
        f"«Witcher» → «The Witcher»; «The Witcher tres» → «The Witcher 3» ({_terms(res)})")
    res = _fm("hoy jugué Ratchet and Clank con mi primo y Ratchet y Clank otra vez",
              extra_terms=["Ratchet & Clank"])
    chk(_t(res, "Ratchet & Clank") is not None and _t(res, "Ratchet & Clank")["count"] == 2,
        f"carpeta «Ratchet & Clank» ← «Ratchet and Clank» y «Ratchet y Clank» ({_terms(res)})")
    res = _fm("salió un zombie en el mapa y luego los zombies y más zombis por todas partes",
              extra_terms=["Zombis"])
    chk(_t(res, "Zombis") is not None and _t(res, "Zombis")["count"] == 3,
        f"carpeta «Zombis» ← «zombie», «zombies», «zombis» ({_terms(res)})")
    res = _fm("me encanta The Last of Us de verdad y el last of us dos también")
    chk(_t(res, "The Last of Us") is not None, f"«last of us» sin artículo → «The Last of Us» ({_terms(res)})")

    print("— «Dijiste…»: lo que NO se une —")
    for texto, saga in [("Jugué Halo cuarenta horas seguidas y me encantó.", "Halo"),
                        ("Jugué a GTA cien veces este mes.", "GTA"),
                        ("Jugué Resident Evil trescientas horas.", "Resident Evil"),
                        ("Vendió GTA ciento veinte millones de copias.", "GTA"),
                        ("Jugué Doom treinta y cinco minutos.", "Doom"),
                        ("Jugué Halo veinte horas.", "Halo"), ("Jugué Halo dos horas seguidas.", "Halo"),
                        ("Con Halo siete de cada diez dicen que sí.", "Halo"),
                        ("Compré Halo, tres copias.", "Halo"), ("Vi Battlefield mil veces.", "Battlefield"),
                        ("Halo dos o tres veces al día.", "Halo"), ("Subió GTA veinte por ciento.", "GTA"),
                        ("Cyberpunk dos mil setenta y siete es bueno.", "Cyberpunk"),
                        ("Tengo dos mil problemas con Halo y no sé qué hacer.", "Halo")]:
        res = _fm(texto)
        chk([t for t, _c in _terms(res)] == [saga], f"cantidad, no entrega: «{texto}» → {_terms(res)}")
    for carpeta, texto in [("Dios", "Me dio miedo y luego le dio igual."),
                           ("Marte", "El martes jugué mucho y otro martes más."),
                           ("Dados", "Me ha dado igual y el dado cayó."),
                           ("Celos", "Tiene mucho celo en su trabajo."),
                           ("Andes", "Que ande con cuidado siempre."),
                           ("Marcos", "En el marco de la feria hay de todo.")]:
        res = _fm(texto, extra_terms=[carpeta])
        chk(_t(res, carpeta) is None, f"carpeta «{carpeta}» no recorta la «s»: «{texto}» → {_terms(res)}")
    for carpeta, texto in [("Persona", "Llegaron dos personas y las personas juegan."),
                           ("Control", "Los controles fallan y los controles no van."),
                           ("Portal", "Abrí dos portales y los portales brillan."),
                           ("Sol", "Vi dos soles y los soles brillan."),
                           ("Rosa", "Compré rosas rojas y las rosas huelen."),
                           ("Mercedes", "Quedó a merced del viento.")]:
        res = _fm(texto, extra_terms=[carpeta])
        chk(_t(res, carpeta) is None, f"carpeta en singular no atrapa el plural en minúscula: «{carpeta}» / «{texto}» "
            f"→ {_terms(res)}")
    res = _fm("hoy jugué con Personas raras y luego con mi Persona favorita", extra_terms=["Persona"])
    chk(_t(res, "Persona") is not None and _t(res, "Persona")["count"] == 2,
        f"…pero «Personas» con mayúscula a media frase sí se une ({_terms(res)})")
    res = _fm("hoy toca Ángeles vino ayer y Ángeles juega.", extra_terms=["Ángeles"],
              glossary={"si": {}, "no": ["los angeles"], "web": {}})
    chk(_t(res, "Ángeles") is not None, f"«no» a «Los Ángeles» no borra la carpeta «Ángeles» (2) ({_terms(res)})")
    res = _fm("Ángeles vino ayer y Ángeles juega.", extra_terms=["Ángeles"],
              glossary={"si": {}, "no": ["los angeles"], "web": {}})
    chk(_t(res, "Ángeles") is not None, f"«no» a «Los Ángeles» no borra la carpeta «Ángeles» ({_terms(res)})")
    res = _fm("La Tierra gira y La Tierra es redonda.", extra_terms=["La Tierra"],
              glossary={"si": {}, "no": ["tierra"], "web": {}})
    chk(_t(res, "La Tierra") is not None, f"«no» a «tierra» no borra la carpeta «La Tierra» ({_terms(res)})")
    chk(not KG.is_no("Ángeles", {"si": {}, "no": ["los angeles"], "web": {}}, exacto=True),
        "is_no(exacto) de la carpeta «Ángeles» con «no» a «Los Ángeles» → no")
    for carpeta, texto in [("Dark Lands Castle", "El DLC es caro y otro DLC más."),
                           ("Gran Aventura Total Online", "Mi GATO duerme y el GATO come."),
                           ("Call of Duty", "El COD es un pez y comí cod."),
                           ("Lost Ark", "Vive en LA desde hace años y LA es enorme."),
                           ("Personal Computer", "Lo juego en PC y en PC va mejor.")]:
        res = _fm(texto, extra_terms=[carpeta])
        chk(_t(res, carpeta) is None, f"sigla sin su nombre dicho o sigla común: «{texto}» → {_terms(res)}")
    res = _fm("tengo una Xbox Series X en casa y la Xbox diez no existe")
    chk(_t(res, "Xbox Series X") is not None and not any("10" in t for t, _c in _terms(res)
                                                         if t.startswith("Xbox Series")),
        f"«Xbox Series X» ≠ «Xbox 10» ({_terms(res)})")
    res = _fm("hoy jugamos Halo con amigos y luego dije Hola a todos")
    chk(_t(res, "Halo") is not None and _t(res, "Halo")["count"] == 1, f"«Halo» ≠ «Hola» ({_terms(res)})")
    res = _fm("ayer me pasé Mario otra vez y luego vino María a casa")
    chk(_t(res, "Mario") is not None and _t(res, "Mario")["count"] == 1, f"«Mario» ≠ «María» ({_terms(res)})")
    res = _fm("hoy toca Doom en casa y luego Dome en la tele")
    chk(_t(res, "Doom") is not None and _t(res, "Doom")["count"] == 1, f"«Doom» ≠ «Dome» ({_terms(res)})")
    res = _fm("hoy toca Doom en casa y luego Dome en la tele",
              glossary={"si": {}, "no": [], "web": {}, "unir": {"dome": "Doom"}, "separar": []})
    chk(_t(res, "Doom") is not None and _t(res, "Doom")["count"] == 2, f"…salvo «Unir con…» ({_terms(res)})")
    res = _fm("jugué GTA cinco toda la tarde y luego Halo cinco con mi primo")
    chk(_t(res, "GTA 5") is not None and _t(res, "Halo 5") is not None, f"dos sagas con número no se mezclan "
        f"({_terms(res)})")
    res = _fm("jugué Resident Evil cuatro ayer y hoy Resident Evil cinco por fin")
    chk(_t(res, "Resident Evil 4") is not None and _t(res, "Resident Evil 5") is not None,
        f"«Resident Evil 4» ≠ «Resident Evil 5» ({_terms(res)})")
    res = _fm("en Halo espera un segundo que vuelvo y Halo segundo a segundo mejora")
    chk(_t(res, "Halo 2") is None and _t(res, "Halo") is not None, f"«un segundo» / «segundo a segundo» no es "
        f"«Halo 2» ({_terms(res)})")
    res = _fm("el mejor es Halo segundo. | Lo jugué mucho.")
    chk(_t(res, "Halo 2") is not None, f"«Halo segundo.» (cerrando la frase) sí es «Halo 2» ({_terms(res)})")
    res = _fm("jugué GTA dos mil horas seguidas")
    chk(not any(t.startswith("GTA 2") for t, _c in _terms(res)), f"«GTA dos mil horas» no es «GTA 2000» ni «GTA 2» "
        f"({_terms(res)})")
    res = _fm("ayer jugué Fortnite y luego Fortnight otra vez", glossary={"si": {}, "no": ["fortnight"], "web": {}})
    chk(_t(res, "Fortnite") is not None and _t(res, "Fortnite")["count"] == 1,
        f"«No es palabra clave» en «Fortnight» quita solo esas veces ({_terms(res)})")

    print("— «Separar…» y «Unir con…» se recuerdan —")
    texto = "ayer jugué Fortnite con amigos y luego Fortnight otra vez y hoy toca Doom y luego Dome en la tele"
    KG.add_separacion("Fortnight")
    g = KG.load()
    chk("fortnight" in g["separar"], f"Separar guarda «fortnight» en el glosario ({g.get('separar')})")
    res = _fm(texto, glossary=KG.load())
    chk(_t(res, "Fortnite") is not None and _t(res, "Fortnite")["count"] == 1 and _t(res, "Fortnight") is not None,
        f"…y «Fortnight» sale aparte ({_terms(res)})")
    KG.add_union(["Dome"], "Doom")
    res = _fm(texto, glossary=KG.load())
    chk(_t(res, "Doom") is not None and _t(res, "Doom")["count"] == 2 and _t(res, "Dome") is None,
        f"Unir con… «Dome» → «Doom» se recuerda ({_terms(res)}; {KG.load().get('unir')})")
    KG.add_union(["Fortnight"], "Fortnite")
    res = _fm(texto, glossary=KG.load())
    chk(_t(res, "Fortnite") is not None and _t(res, "Fortnite")["count"] == 2,
        f"unir a mano deshace el «Separar» ({_terms(res)}; separar={KG.load().get('separar')})")
    KG.add_separacion("Dome")
    res = _fm(texto, glossary=KG.load())
    chk(_t(res, "Doom")["count"] == 1 and _t(res, "Dome") is not None, f"separar deshace el «Unir con…» "
        f"({_terms(res)}; unir={KG.load().get('unir')})")
    KG.remove("Dome")
    KG.remove("Fortnight")
    g = KG.load()
    chk(not g.get("unir") and not g.get("separar"), f"«↺ Quitar del glosario» olvida uniones y separaciones ({g})")
    KG.add_separacion("gta cinco")
    res = _fm("jugamos gta5 con amigos y luego gta cinco otra vez", glossary=KG.load())
    chk(_t(res, "GTA 5") is not None and _t(res, "GTA 5")["count"] == 1 and _t(res, "gta cinco") is not None,
        f"se puede separar hasta una variante de número («gta cinco») ({_terms(res)})")
    KG.remove("gta cinco")

    print("— interfaz: tooltip y clic derecho —")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui import clips_panel as CP
    win = MainWindow()
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(
        "ayer jugué Fortnite con amigos y luego Fortnight otra vez y hoy toca Doom y luego Dome en la tele "
        "y gta5 y gta cinco y GTA V también")}}
    win.ctrl.project.transcripts = p.transcripts
    panel = win.clips
    panel.raiz = os.path.join(os.environ["LOCALAPPDATA"], "carpetas")
    panel._firma_ultima = None
    panel.recalcular()
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "GTA 5")
    it = next(panel.lista_menciones.item(r) for r in range(panel.lista_menciones.count())
              if panel.lista_menciones.item(r).data(0x0100) == fila)
    chk("También dicho: gta5, gta cinco, GTA V" in it.toolTip(), f"tooltip «También dicho: …» ({it.toolTip()!r})")
    chk(CP.texto_variantes({"term": "X", "variantes": []}) == "", "sin variantes, sin línea en el tooltip")
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Fortnite")
    it = next(panel.lista_menciones.item(r) for r in range(panel.lista_menciones.count())
              if panel.lista_menciones.item(r).data(0x0100) == fila)
    menu = panel._menu_mencion(it)
    subs = {a.text(): a for a in menu.actions()}
    chk("✂ Separar…" in subs and "🔗 Unir con…" in subs, f"clic derecho: «✂ Separar…» y «🔗 Unir con…» "
        f"({list(subs)})")
    sep = subs["✂ Separar…"].menu()
    chk([a.text() for a in sep.actions()] == ["«Fortnight»"], f"Separar… lista lo oído ({[a.text() for a in sep.actions()]})")
    sep.actions()[0].trigger()
    chk("fortnight" in KG.load()["separar"], "…y al elegirlo se guarda")
    for _ in range(40):
        app.processEvents()
        time.sleep(0.01)
    chk(_t(panel.menciones, "Fortnight") is not None, f"…y «Dijiste…» lo saca aparte ({_terms(panel.menciones)})")
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Dome")
    it = next(panel.lista_menciones.item(r) for r in range(panel.lista_menciones.count())
              if panel.lista_menciones.item(r).data(0x0100) == fila)
    menu = panel._menu_mencion(it)
    unir = {a.text(): a for a in menu.actions()}["🔗 Unir con…"].menu()
    destino = next((a for a in unir.actions() if a.text() == "Doom"), None)
    chk(destino is not None, f"Unir con… ofrece «Doom» ({[a.text() for a in unir.actions()]})")
    if destino is not None:
        destino.trigger()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.01)
    chk(_t(panel.menciones, "Doom") is not None and _t(panel.menciones, "Doom")["count"] == 2
        and _t(panel.menciones, "Dome") is None, f"…y se unen ({_terms(panel.menciones)})")
    chk(KG.load()["unir"].get("dome") == "Doom", f"…y se recuerda ({KG.load()['unir']})")
    from editoria.ui.keywords_window import KeywordsWindow
    kw = KeywordsWindow(panel)
    kw.refrescar()
    tips = [kw.lista.item(i).toolTip() for i in range(kw.lista.count())
            if kw.lista.item(i).data(0x0100) == "GTA 5"]
    chk(tips and "También dicho:" in tips[0], f"🔑 Palabras clave: el mismo tooltip ({tips})")
    kw.deleteLater()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()

    print("— 8. rendimiento: narración de 2 h —")
    random.seed(3)
    frases = ["hoy vamos a ver el nuevo tráiler de GTA seis que salió ayer",
              "la verdad es que el peor juego del año fue otro", "en Fortnite metieron un mapa nuevo",
              "Red Dead Redemption 2 sigue siendo increíble", "espera cinco minutos que vuelvo",
              "Minecraft y Roblox son los más jugados", "el GTA V ya tiene doce años",
              "ayer vi The Game Awards con mi hermano", "bueno pues seguimos con el video",
              "Elden Ring Nightreign tiene jefes nuevos", "y eso es todo por hoy amigos",
              "el spiderman nuevo y Fortnight y Cyberpunk dos mil setenta y siete",
              "juego COD con los zombies y Witcher tres", "Call of Duty sigue vendiendo mucho"]
    largo = []
    while len(largo) < 19000:
        largo += (random.choice(frases) + ".").split()
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(" ".join(largo))}}
    M.precargar()
    g = {"si": {}, "no": [], "web": {}, "unir": {"dome": "Doom"}, "separar": ["gta cinco"]}
    M.find_mentions(p, extra_terms=["GTA V", "Fortnite", "Zombis"], glossary=g)     # (calienta cachés)
    tiempos = []
    for _ in range(3):
        t0 = time.perf_counter()
        res = M.find_mentions(p, extra_terms=["GTA V", "Fortnite", "Zombis"], glossary=g)
        tiempos.append((time.perf_counter() - t0) * 1000)
    ms = min(tiempos)
    chk(ms < 150, f"find_mentions con {len(largo)} palabras (≈2 h): {ms:.0f} ms (< 150)")
    chk(_t(res, "Fortnite") is not None and "Fortnight" in _t(res, "Fortnite")["variantes"]
        and _t(res, "Spider-Man") is not None and _t(res, "Call of Duty") is not None
        and _t(res, "Cyberpunk 2077") is not None and _t(res, "Zombis") is not None,
        f"…y une lo que toca ({_terms(res)[:12]})")

    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
