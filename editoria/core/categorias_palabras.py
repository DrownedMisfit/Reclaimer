"""
🔑 Categorías de palabras: qué se dice en la narración y qué significa para una escena o para el 🎭 PNGTuber.

Dos tablas que comparten la misma forma de buscar:
  ESCENAS    lo que PASA en la historia («premiación», «disparos», «huyó», «explotó»…) → escenas ⚡ prehechas
             sugeridas (core/escenas_prehechas.py), rotando variantes para no repetir la misma animación seguida.
  PNGTUBER   cómo SUENA lo que dices («hola», «genial», «¿qué?», «qué pena», «jaja»…) → una reacción del avatar
             (saluda, salta de alegría, se sobresalta, se encoge, tiembla…; core/pngtuber.py).

Cada categoría: {"clave", "nombre", "patrones" (expresiones regulares sobre UNA palabra ya normalizada: minúsculas,
sin tildes, solo letras; se exige que encaje entera), "frases" (varias palabras seguidas, normalizadas), y lo suyo:
"prehechas" + "buscar" (qué buscar en 🌐 Internet) en ESCENAS; "reaccion" + "dur" en PNGTUBER}.

  normalizar(texto) -> str                     «¡Disparó!» → «disparo»
  palabras_linea(p, a=None, b=None) -> [(t0, t1, texto)]   lo que suena en la línea de tiempo (todas las
                                               transcripciones; solo el tramo [a, b] si se da)
  detectar(palabras, categorias) -> [{"cat", "palabra", "texto", "t", "t1"}]   en orden de tiempo
  agrupar(menciones) -> [{"cat", "veces", "palabras": {palabra dicha: [t…]}, "ts": [t…]}]   de más a menos veces
  dicha(mencion) -> str                        la palabra tal como se dijo («ganó»)
  rotacion(cat, elegida) -> [claves]           la elegida primero y luego las otras sugeridas (sin repetir)
  plan_escenas(menciones, elegir, largo, ocupado) -> [(t, cat, clave)]   dónde va cada escena, sin solaparse y sin
                                               repetir la misma prehecha seguida
Sin Qt (lo usan ui/scenes_page.py, ui/pngtuber_dialog.py y las pruebas).
"""
from __future__ import annotations

import re
import unicodedata

# ============================================================================================ 🎬 escenas
ESCENAS = [
    dict(clave="premio", nombre="🏆 Premiación y victoria", buscar="trofeo",
         prehechas=["victoria", "saltan", "ganador_perdedor"],
         patrones=[r"premi\w*", r"galardon\w*", r"trofeo\w*", r"copa", r"campeon\w*", r"campeonato\w*",
                   r"victoria\w*", r"victorios\w*", r"medalla\w*", r"triunf\w*", r"coron(o|aron|ado|ada|ados|acion)",
                   r"gan(o|aron|amos|a|an|e|en|ar|aste|ando|ado|ador|adora|adores|adoras)"],
         frases=["primer lugar", "se llevo el premio"]),
    dict(clave="disparos", nombre="🔫 Disparos", buscar="pistola",
         prehechas=["tiroteo", "duelo", "contra_grupo"],
         patrones=[r"dispar\w*", r"balacera\w*", r"balazo\w*", r"balas?", r"tirote\w*", r"tiros?", r"rafagas?",
                   r"escopetaz\w*", r"francotirador\w*", r"ametrall\w*", r"metralla\w*", r"fusil\w*",
                   r"pistola\w*", r"rifle\w*", r"revolver\w*", r"pium"],
         frases=["abre fuego", "abrio fuego", "abrieron fuego", "le dispara", "le disparo"]),
    dict(clave="pelea", nombre="👊 Pelea y golpes", buscar="luchador",
         prehechas=["pelea", "intercambio", "golpe_y_cae"],
         patrones=[r"pelea\w*", r"pele(o|aron|an|ar|ando|amos)", r"golpe\w*", r"golpea\w*", r"punetaz\w*",
                   r"patada\w*", r"combate\w*", r"combat(e|en|io|ieron|ir|iendo)", r"lucha\w*",
                   r"luch(o|aron|an|ar|ando)", r"enfrent\w*", r"batalla\w*", r"madraz\w*", r"bofetad\w*",
                   r"cachetad\w*", r"pelotera\w*", r"rina\w*", r"zurra\w*"],
         frases=["a golpes", "a punetazos", "se agarraron"]),
    dict(clave="huida", nombre="🏃 Huida y persecución", buscar="persona corriendo",
         prehechas=["persecucion", "huida", "persigue_grupo", "carrera"],
         patrones=[r"hu(ye|yen|yo|yeron|ir|yendo|ida|imos)", r"escap\w*", r"persecucion\w*", r"persig\w*",
                   r"persegu\w*", r"fuga\w*", r"fug(o|aron|arse|ado|ados)", r"corr(e|en|io|ieron|iendo|er)",
                   r"carrera\w*", r"estampida\w*"],
         frases=["salio corriendo", "salieron corriendo", "sale corriendo", "a toda prisa"]),
    dict(clave="muerte", nombre="💀 Muerte y caída", buscar="soldado",
         prehechas=["golpe_y_cae", "derrota", "duelo"],
         patrones=[r"muri(o|eron|endo)", r"muer(e|en)", r"muert(e|es|o|os|a|as)", r"morir\w*", r"fallec\w*",
                   r"mat(o|aron|a|an|ar|ando|ado|ados|arlo|arla)", r"asesin\w*", r"elimin\w*",
                   r"ca(e|en|er|yo|yeron|ida|ido)", r"desplom\w*", r"abatid\w*", r"cadaver\w*"],
         frases=["lo mata", "la mata", "los mata", "se murio"]),
    dict(clave="explosion", nombre="💥 Explosión", buscar="barril",
         prehechas=["explota"],
         patrones=[r"explo(t|si)\w*", r"estall\w*", r"revent\w*", r"bomba\w*", r"bombaz\w*", r"granada\w*",
                   r"deton\w*", r"dinamita\w*", r"kaboom", r"boom", r"bum", r"pum"],
         frases=["salto por los aires", "volo por los aires"]),
    dict(clave="llegada", nombre="⭐ Llegada y presentación", buscar="personaje",
         prehechas=["protagonista", "impacto", "acerca_y_va"],
         patrones=[r"lleg(a|an|o|aron|ando|ada|ue|ara)", r"aparec\w*", r"aparicion\w*", r"entr(a|an|o|aron|ando)",
                   r"entrada", r"present(a|an|o|aron|ando|acion|amos)", r"debut\w*", r"protagonista\w*",
                   r"regres\w*", r"estren\w*"],
         frases=["hace su aparicion", "entra en escena", "por fin llega"]),
    dict(clave="sorpresa", nombre="😱 Sorpresa y susto", buscar="persona asustada",
         prehechas=["sorpresa", "aparece_golpe"],
         patrones=[r"sorpres\w*", r"sorprend\w*", r"sust(o|os)", r"asust\w*", r"espant\w*", r"miedo\w*",
                   r"terror\w*", r"aterr\w*", r"panico", r"impactad\w*", r"impactant\w*", r"wow", r"guau"],
         frases=["no puede ser", "de repente", "de golpe", "sin previo aviso"]),
    dict(clave="emboscada", nombre="🎯 Emboscada y trampa", buscar="enemigo",
         prehechas=["emboscada", "contra_grupo"],
         patrones=[r"embosc\w*", r"trampa\w*", r"acorral\w*", r"rode(a|an|o|aron|ado|ados|ada)", r"cerc(o|aron|ado)",
                   r"atrapad\w*", r"atrap(o|aron|a|an)"],
         frases=["lo rodean", "los rodean", "sin salida"]),
    dict(clave="discusion", nombre="💬 Discusión", buscar="persona enfadada",
         prehechas=["discuten"],
         patrones=[r"discut\w*", r"discusion\w*", r"debat\w*", r"grit(a|an|o|aron|ando|os)", r"insult\w*",
                   r"reclam\w*", r"regan\w*", r"acus(a|an|o|aron|ando|acion)", r"pleito\w*", r"polemica\w*"],
         frases=["se pelean de palabra", "le dice que"]),
    dict(clave="risa", nombre="😂 Risa y broma", buscar="persona riendo",
         prehechas=["risa", "saltan"],
         patrones=[r"(?:ja|je|ji|js){2,}h?", r"risa\w*", r"rie(n|ndo)?", r"reir\w*", r"carcajad\w*",
                   r"broma\w*", r"brome\w*", r"chiste\w*", r"burl\w*", r"gracios\w*", r"xd"],
         frases=["muerto de risa", "se partio de risa", "se rio", "se rieron"]),
    dict(clave="derrota", nombre="😞 Derrota y fracaso", buscar="persona triste",
         prehechas=["derrota", "ganador_perdedor"],
         patrones=[r"perd(io|ieron|imos|i|er|edor|edora|edores|ida|ido)", r"pierd(e|en|o)", r"derrot\w*",
                   r"fracas\w*", r"trist\w*", r"humill\w*", r"rendi(do|dos|rse)", r"rind(e|en|io|ieron)"],
         frases=["se rinde", "se rindieron", "no lo logro"]),
    dict(clave="rivales", nombre="🆚 Rivales y desafío", buscar="guerrero",
         prehechas=["cara_a_cara", "duelo"],
         patrones=[r"rival\w*", r"versus", r"vs", r"enemig\w*", r"duelo\w*", r"desafi\w*", r"ret(a|an|o|aron)",
                   r"nemesis", r"contrincante\w*", r"adversari\w*", r"oponente\w*"],
         frases=["cara a cara", "frente a frente", "uno contra uno"]),
    dict(clave="grupo", nombre="👥 Grupo y equipo", buscar="soldados",
         prehechas=["presenta_grupo", "persigue_grupo", "contra_grupo"],
         patrones=[r"equipo\w*", r"grupo\w*", r"banda\w*", r"escuadr\w*", r"pandilla\w*", r"ejercito\w*",
                   r"horda\w*", r"zombi\w*", r"multitud\w*", r"tropa\w*", r"clan(es)?", r"aliad\w*"],
         frases=["todos juntos", "un monton de"]),
    dict(clave="vehiculo", nombre="🚗 Vehículos", buscar="coche",
         prehechas=["vehiculo", "carrera"],
         patrones=[r"coches?", r"carros?", r"autos?", r"automovil\w*", r"camion\w*", r"motos?", r"motocicleta\w*",
                   r"vehiculo\w*", r"tanques?", r"naves?", r"avion\w*", r"helicoptero\w*", r"fren(a|an|o|aron|azo)",
                   r"aceler\w*", r"conduc\w*", r"manej(a|an|o|aron|ando)", r"derrap\w*"],
         frases=["a toda velocidad", "piso el acelerador"]),
]

# ============================================================================================ 🎭 PNGTuber
# (reacción = cómo se mueve el avatar: ver pngtuber.movimiento; dur = segundos que dura)
PNGTUBER = [
    dict(clave="saludo", nombre="👋 Saludos", reaccion="saluda", dur=1.2, ejemplos="hola, buenas, bienvenidos",
         patrones=[r"hola+", r"holi(s|wis)?", r"buenas", r"bienvenid\w*", r"saludos?", r"salud(ar|amos|an)", r"hey",
                   r"ey", r"wenas"],
         frases=["que tal", "que onda", "buenos dias", "buenas tardes", "que hay", "como estan"]),
    dict(clave="despedida", nombre="👋 Despedida", reaccion="despide", dur=1.2, ejemplos="adiós, nos vemos, chao",
         patrones=[r"adios\w*", r"chao", r"chau", r"bye", r"cuidense", r"cuidate"],
         frases=["nos vemos", "hasta luego", "hasta pronto", "hasta la proxima", "hasta manana", "buenas noches"]),
    dict(clave="feliz", nombre="😄 Felicidad", reaccion="feliz", dur=1.0,
         ejemplos="genial, increíble, ganamos, me encanta",
         patrones=[r"genial\w*", r"increible\w*", r"excelente\w*", r"buenisim\w*", r"maravillos\w*",
                   r"fantastic\w*", r"espectacular\w*", r"perfect\w*", r"feliz", r"felices", r"felicidad",
                   r"alegr\w*", r"contento\w*", r"contenta\w*", r"ganamos", r"gane", r"ganaste", r"bravo", r"yei",
                   r"yay", r"brutal\w*", r"epic\w*", r"encant\w*", r"hermos\w*", r"precios\w*", r"emocionad\w*",
                   r"felicidades", r"enhorabuena", r"hurra", r"aleluya"],
         frases=["que bien", "me encanta", "lo logramos", "lo conseguimos", "por fin"]),
    dict(clave="sorpresa", nombre="😲 Sorpresa", reaccion="sobresalto", dur=0.7,
         ejemplos="¿qué?, wow, no puede ser",
         patrones=[r"wow", r"guau", r"uau", r"ostras?", r"sorpres\w*", r"sorprend\w*", r"impresionant\w*",
                   r"impactant\w*", r"queee+", r"increiblemente"],
         frases=["no puede ser", "no me lo creo", "no manches", "que fuerte", "en serio", "dios mio", "madre mia",
                 "de repente"],
         crudos=[r"^[¿¡]+\s*que\s*[?!]+$", r"^que[?!]{1,}$"]),
    dict(clave="triste", nombre="😢 Tristeza", reaccion="encoge", dur=1.2, ejemplos="triste, murió, perdimos",
         patrones=[r"trist\w*", r"lament\w*", r"lastima", r"pena", r"murio", r"murieron", r"muerte", r"perdimos",
                   r"perdi", r"perdio", r"perdieron", r"llor\w*", r"desgracia\w*", r"deprim\w*", r"desafortunad\w*",
                   r"doloros\w*", r"dolor", r"descanse"],
         frases=["que pena", "por desgracia", "en paz descanse", "me duele"]),
    dict(clave="enojo", nombre="😠 Enojo", reaccion="tiembla", dur=0.9, ejemplos="odio, molesto, qué rabia",
         patrones=[r"odi(o|a|an|amos|ar|aba)", r"molest\w*", r"enoj\w*", r"enfad\w*", r"furios\w*", r"furia",
                   r"rabia\w*", r"harto", r"harta", r"hartos", r"maldit\w*", r"asco", r"indign\w*", r"cabre\w*",
                   r"ridicul\w*", r"absurd\w*", r"estupid\w*"],
         frases=["que asco", "que rabia", "ya basta", "no puede ser que"]),
    dict(clave="risa", nombre="😂 Risa", reaccion="rebote", dur=0.9, ejemplos="jaja, qué risa, chiste",
         patrones=[r"(?:ja|je|ji|js){2,}h?", r"risa\w*", r"rei", r"reir\w*", r"rie(n|ndo)?", r"carcajad\w*",
                   r"gracios\w*", r"chiste\w*", r"broma\w*", r"xd", r"lol"],
         frases=["que risa", "me muero de risa", "muerto de risa"]),
    dict(clave="duda", nombre="🤔 Duda", reaccion="inclina", dur=1.1, ejemplos="quizás, ¿por qué?, a lo mejor",
         patrones=[r"quiza\w*", r"supongo", r"dud\w*", r"misteri\w*", r"raro", r"rara", r"extran(o|a|os|as)",
                   r"hmm+", r"mmm+", r"pregunt(o|a|ando|arse)", r"curios\w*", r"sospech\w*"],
         frases=["tal vez", "a lo mejor", "por que", "no lo se", "ni idea", "creo que", "sera que", "me pregunto"]),
    dict(clave="acuerdo", nombre="🙏 Gracias / de acuerdo", reaccion="asiente", dur=0.9,
         ejemplos="gracias, exacto, efectivamente",
         patrones=[r"gracias", r"agradec\w*", r"exacto", r"exactamente", r"efectivamente", r"correcto", r"obvio",
                   r"obviamente", r"totalmente", r"claramente", r"cierto"],
         frases=["claro que si", "por supuesto", "asi es", "tienes razon", "muchas gracias"]),
    dict(clave="miedo", nombre="😨 Miedo", reaccion="miedo", dur=1.0, ejemplos="miedo, terror, qué susto",
         patrones=[r"miedo\w*", r"terror\w*", r"terrorific\w*", r"aterr\w*", r"panico", r"asust\w*", r"susto",
                   r"espant\w*", r"escalofri\w*", r"tembl\w*", r"horror\w*", r"pesadilla\w*", r"tenebros\w*"],
         frases=["que susto", "que miedo", "me da miedo"]),
    dict(clave="carino", nombre="❤ Cariño", reaccion="late", dur=1.0, ejemplos="amor, te quiero, qué lindo",
         patrones=[r"amor\w*", r"ador(o|a|able|ables)", r"lind\w*", r"bonit\w*", r"ternura", r"tiern\w*",
                   r"carino\w*", r"cuqui\w*", r"precioso", r"preciosa"],
         frases=["te quiero", "los quiero", "las quiero", "que lindo", "que bonito", "que tierno"]),
]

# Frases que NO cuentan para ninguna categoría (sus palabras quedan fuera: «vale la pena» no es tristeza)
NEUTRAS = ["vale la pena", "valio la pena", "valdra la pena", "merece la pena", "a duras penas", "tengo ganas",
           "me muero de ganas", "de nada", "por cierto", "esta bien", "muy bien", "corre a cargo", "en cuanto a"]

POR_CLAVE_ESCENA = {c["clave"]: c for c in ESCENAS}
POR_CLAVE_PNGTUBER = {c["clave"]: c for c in PNGTUBER}


# ============================================================================================ buscar
def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes (la ñ pasa a n), solo letras y espacios: «¡Disparó!» → «disparo»."""
    s = "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s)).strip()


def _crudo(texto: str) -> str:
    """Minúsculas y sin tildes, pero con sus signos («¿Qué?» → «¿que?»)."""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower().strip())
                   if unicodedata.category(c) != "Mn")


_CACHE: dict[int, tuple] = {}


def _compilada(cat: dict) -> tuple:
    k = id(cat)
    if k not in _CACHE or _CACHE[k][0] is not cat:
        rx = re.compile("(?:" + "|".join(cat.get("patrones") or ["(?!)"]) + ")")
        frases = [tuple(normalizar(f).split()) for f in cat.get("frases") or [] if normalizar(f)]
        frases.sort(key=len, reverse=True)
        crudos = [re.compile(c) for c in cat.get("crudos") or []]
        _CACHE[k] = (cat, rx, frases, crudos)
    return _CACHE[k][1:]


def palabras_linea(p, a: float | None = None, b: float | None = None,
                   media_id: str | None = None) -> list[tuple[float, float, str]]:
    """Lo que suena en la línea de tiempo: [(inicio, fin, texto)] de todas las transcripciones (o solo de «media_id»),
    por orden; con a/b, solo lo que empieza en ese tramo."""
    from . import subtitles
    out = []
    mids = [media_id] if media_id else list(getattr(p, "transcripts", {}) or {})
    for mid in mids:
        if mid not in getattr(p, "media", {}) or mid not in (getattr(p, "transcripts", {}) or {}):
            continue
        try:
            out += [(float(t0), float(t1), str(txt)) for t0, t1, txt, _i in subtitles.timeline_words(p, mid)]
        except Exception:  # noqa: BLE001 - una transcripción rara no rompe las demás
            continue
    if a is not None:
        out = [w for w in out if w[0] >= a - 1e-6]
    if b is not None:
        out = [w for w in out if w[0] < b]
    out.sort(key=lambda w: w[0])
    return out


def detectar(palabras: list, categorias: list[dict]) -> list[dict]:
    """Cada vez que se dice algo de una categoría: [{"cat", "palabra" (normalizada, la frase entera si son varias),
    "texto" (tal cual), "t", "t1"}], por orden. Una palabra cuenta para UNA categoría por tabla (la primera que la
    tiene, en el orden de la tabla) y las frases ganan a las palabras sueltas."""
    toks = []                                         # (índice en palabras, palabra normalizada) — una por token
    for i, w in enumerate(palabras):
        for parte in normalizar(w[2]).split():
            toks.append((i, parte))
    usados: set[int] = set()
    out = []
    comp = [(c, *_compilada(c)) for c in categorias]
    for fr in sorted((tuple(normalizar(f).split()) for f in NEUTRAS), key=len, reverse=True):
        n = len(fr)
        for j in range(len(toks) - n + 1):
            if tuple(t for _i, t in toks[j:j + n]) == fr:
                usados.update(range(j, j + n))
    # 1) frases (las más largas primero)
    for cat, _rx, frases, _cr in comp:
        for fr in frases:
            n = len(fr)
            for j in range(len(toks) - n + 1):
                if any((j + k) in usados for k in range(n)):
                    continue
                if tuple(t for _i, t in toks[j:j + n]) == fr:
                    i0, i1 = toks[j][0], toks[j + n - 1][0]
                    out.append({"cat": cat["clave"], "palabra": " ".join(fr),
                                "texto": " ".join(str(palabras[x][2]) for x in range(i0, i1 + 1)).strip(),
                                "t": float(palabras[i0][0]), "t1": float(palabras[i1][1])})
                    usados.update(range(j, j + n))
    # 2) lo crudo (con sus signos: «¿qué?») y 3) palabras sueltas
    for j, (i, tok) in enumerate(toks):
        if j in usados:
            continue
        crudo = _crudo(palabras[i][2])
        for cat, rx, _fr, crudos in comp:
            if any(c.search(crudo) for c in crudos) or rx.fullmatch(tok):
                out.append({"cat": cat["clave"], "palabra": tok, "texto": str(palabras[i][2]).strip(),
                            "t": float(palabras[i][0]), "t1": float(palabras[i][1])})
                usados.add(j)
                break
    out.sort(key=lambda m: (m["t"], m["cat"]))
    return out


def dicha(m: dict) -> str:
    """La palabra tal como se dijo, en minúsculas y sin signos («¡Ganó!» → «ganó»)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\wáéíóúüñ ]+", " ", str(m.get("texto") or m.get("palabra") or "").lower())
                  ).strip() or str(m.get("palabra") or "")


def agrupar(menciones: list[dict]) -> list[dict]:
    """Por categoría: cuántas veces, qué palabras (tal como se dijeron, y en qué segundos). De la que más sale a la
    que menos."""
    por: dict[str, dict] = {}
    for m in menciones:
        g = por.setdefault(m["cat"], {"cat": m["cat"], "veces": 0, "palabras": {}, "ts": []})
        g["veces"] += 1
        g["palabras"].setdefault(dicha(m), []).append(m["t"])
        g["ts"].append(m["t"])
    orden = {c["clave"]: i for i, c in enumerate(ESCENAS + PNGTUBER)}
    return sorted(por.values(), key=lambda g: (-g["veces"], orden.get(g["cat"], 99)))


# ============================================================================================ 🎬 acomodar
def rotacion(cat: str, elegida: str | None = None, variar: bool = True) -> list[str]:
    """Las prehechas de esa categoría por turno: la elegida primero y luego las otras sugeridas (sin repetir).
    variar=False: solo la elegida."""
    sug = list(POR_CLAVE_ESCENA.get(cat, {}).get("prehechas") or [])
    primera = elegida or (sug[0] if sug else None)
    if primera is None:
        return []
    if not variar:
        return [primera]
    return [primera] + [s for s in sug if s != primera]


def plan_escenas(menciones: list[dict], elegir: dict[str, list[str]], largo, ocupado=(),
                 margen: float = 0.15) -> tuple[list[tuple[float, str, str]], int]:
    """Dónde va cada escena. menciones: las marcadas (con "cat" y "t"); elegir: {cat: rotación de prehechas};
    largo(clave) -> segundos que dura; ocupado: [(a, b)] tramos donde ya hay escena. Devuelve ([(t, cat, clave)],
    saltadas). No se solapan (la que caería encima de otra se salta) y la misma prehecha no sale dos veces seguidas
    si la categoría tiene otra (dentro de la categoría, por turno; entre categorías, se salta a la siguiente)."""
    tramos = [(float(a), float(b)) for a, b in ocupado]
    turno: dict[str, int] = {}
    ultima = None
    out, saltadas = [], 0
    for m in sorted(menciones, key=lambda x: float(x["t"])):
        rot = [c for c in elegir.get(m["cat"]) or [] if c]
        if not rot:
            continue
        t = max(0.0, float(m["t"]))
        k = turno.get(m["cat"], 0)
        clave = rot[k % len(rot)]
        if clave == ultima and len(rot) > 1:          # (la anterior, de otra categoría, fue la misma: la siguiente)
            k += 1
            clave = rot[k % len(rot)]
        dur = float(largo(clave))
        if any(t < b + margen and t + dur > a - margen for a, b in tramos):
            saltadas += 1
            continue
        turno[m["cat"]] = k + 1
        tramos.append((t, t + dur))
        out.append((round(t, 3), m["cat"], clave))
        ultima = clave
    return out, saltadas
