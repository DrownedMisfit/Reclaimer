"""
«Dijiste…»: qué palabras de tu narración son nombres o temas (Fortnite, Epic Games…) y en qué momentos salen.

  find_mentions(project) -> [{"term", "media_id", "hits": [{"src", "tl", "context", "mods"}], "count", "mods", "known"}]

· Candidatos: nombres propios (palabras con mayúscula fuera del inicio de frase; se unen «Epic Games»),
  palabras de tu vocabulario (editoria/ai/word_fix.py: vocabulary()) y una lista corta de juegos y compañías.
· Juegos con número o subtítulo: «GTA seis», «GTA VI», «G.T.A. 6» son «GTA 6»; «Zelda ocarina of time» es
  «Zelda Ocarina of Time»; «Resident Evil cuatro» es «Resident Evil 4». Los números (en palabras, romanos o
  dígitos) solo se unen tras un nombre conocido, así que «uno de los mejores» no es ningún número.
· «src» = segundo del archivo de narración; «tl» = momento en la línea de tiempo (None si ese tramo está cortado).
· «context» = unas palabras alrededor (±8). «mods» = lo que se hace en ese contexto, en inglés, para buscar
  clips («looteando» → looting). «mods» de la mención = los de todas sus apariciones, por frecuencia.
Sin Qt.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, namedtuple

from ..core.mapping import DeepIndex
from .word_fix import core as _core
from .word_fix import vocabulary
from . import game_lookup
from . import keyword_glossary as _kg

CONTEXTO = 8        # palabras a cada lado que se miran para el contexto
MAX_FRASE = 8       # una frase de la tabla (juego con subtítulo) tiene como mucho 8 palabras
MAX_PROPIO = 4      # un nombre propio suelto (mayúsculas seguidas) tiene como mucho 4 palabras
MAX_EXTENSION = 6   # palabras que se añaden tras un nombre conocido (número, subtítulo, mayúsculas)
PAUSA = 0.6         # s: una pausa más larga de la transcripción corta la extensión

# Forma larga que se muestra como la corta (la mención es la misma).
ALIAS = {"The Legend of Zelda": "Zelda"}

# Juegos y compañías conocidos (prioridad alta). Se evitan palabras corrientes («Control», «Rust», «Arma»…).
CONOCIDOS = [
    "Fortnite", "Minecraft", "Roblox", "Valorant", "League of Legends", "Overwatch", "Apex Legends",
    "Call of Duty", "Warzone", "GTA", "Grand Theft Auto", "Red Dead Redemption", "Elden Ring", "Dark Souls",
    "Bloodborne", "Sekiro", "Hollow Knight", "Hades", "Cyberpunk", "Baldur's Gate", "Starfield", "Skyrim",
    "Fallout", "The Witcher", "God of War", "Spider-Man", "Horizon", "Ghost of Tsushima", "Ghost of Yotei",
    "The Last of Us", "Gears of War", "Halo", "Forza", "Destiny", "Bungie", "Fall Guys", "Among Us",
    "Rocket League", "EA Sports FC", "Counter-Strike", "Dota", "Pokémon", "Zelda", "The Legend of Zelda", "Mario",
    "Super Smash Bros", "Sonic", "Kirby", "Metroid", "Donkey Kong", "Mortal Kombat", "Street Fighter", "Tekken",
    "Sea of Thieves", "Subnautica", "Terraria", "Stardew Valley", "Palworld", "Helldivers", "Battlefield",
    "Rainbow Six", "Escape from Tarkov", "Hogwarts Legacy", "Lethal Company", "Dead by Daylight", "Brawl Stars",
    "Clash Royale", "Clash of Clans", "Genshin Impact", "Marvel Rivals", "Monster Hunter", "Resident Evil",
    "Silent Hill", "Dead Space", "Alan Wake", "Death Stranding", "DayZ", "Factorio", "Satisfactory", "The Sims",
    "Animal Crossing", "Splatoon", "Overcooked", "It Takes Two", "Crash Bandicoot", "Spyro", "Assassin's Creed",
    "Far Cry", "Watch Dogs", "Tomb Raider", "Uncharted", "BioShock", "Borderlands", "Hitman", "Dishonored", "Doom",
    "Titanfall", "Splitgate", "Hell Let Loose", "Warframe", "Path of Exile", "Diablo", "World of Warcraft",
    "Lost Ark", "Black Myth", "Lies of P", "Armored Core", "Steam", "Steam Deck", "PlayStation", "Xbox", "Nintendo",
    "Nintendo Switch", "Sony", "Microsoft", "Epic Games", "Ubisoft", "Electronic Arts", "Bethesda", "Bandai Namco",
    "Capcom", "Rockstar", "Rockstar Games", "Activision", "Blizzard", "Riot Games", "Valve", "Mojang", "Konami",
    "Sega", "Square Enix", "Take-Two", "Naughty Dog", "FromSoftware", "Supercell", "HoYoverse", "Krafton", "Respawn",
    "Remedy",
    # 2025–2026 (sin palabras corrientes)
    "Final Fantasy", "Metal Gear Solid", "Black Ops", "Kingdom Come", "Split Fiction", "Clair Obscur",
]

# Subtítulos conocidos por franquicia (también en minúsculas, como los transcribe Whisper).
# Los números se tratan aparte (GTA 5, Resident Evil 4…), así que aquí solo van las palabras.
SUBTITULOS = {
    "Zelda": ["Ocarina of Time", "Majora's Mask", "Breath of the Wild", "Tears of the Kingdom", "Twilight Princess",
              "Wind Waker", "Link's Awakening", "Skyward Sword"],
    "GTA": ["San Andreas", "Vice City"],
    "Resident Evil": ["Village"],
    "Call of Duty": ["Black Ops", "Modern Warfare", "Warzone"],
    "Final Fantasy": ["Rebirth"],
    "God of War": ["Ragnarok"],
    "Spider-Man": ["Miles Morales"],
    "The Last of Us": ["Part II"],
    "Assassin's Creed": ["Valhalla", "Mirage", "Shadows"],
    "Elden Ring": ["Nightreign"],
    "Halo": ["Infinite"],
    "Gears of War": ["E-Day"],
    "Mario": ["Kart", "Odyssey", "Wonder", "Party"],
    "Pokémon": ["Escarlata", "Púrpura", "Leyendas Z-A"],
    "Hollow Knight": ["Silksong"],
    "Metal Gear Solid": ["Delta"],
    "Silent Hill": ["f"],
}

# Palabras que nunca son un tema (saludos, muletillas, palabras corrientes); claves sin acentos ni mayúsculas.
STOP = set("""
hola buenas buenos bueno buena entonces pues vale oye oigan mira miren ahora hoy ayer manana pero y o e
el la los las un una unos unas que como cuando donde porque aunque si no asi esto eso este esta ese esa estos
estas aqui alli ya yo tu ella ellos ellas nosotros nosotras vosotros usted ustedes me te se nos lo le les mi
mis su sus tambien ademas luego despues antes primero segundo tercero ultimo final claro genial perfecto gracias
chicos chicas amigos amigas gente bienvenidos bienvenidas bienvenido ok okay sabes creo bien obviamente basicamente
vamos ojo pasa tenemos tengo hay hace voy puedo quiero ahi aca siempre nunca mucho poco todo todos nada algo alguien
nadie cada otro otra otros otras mismo misma mas menos muy solo sola sino total encima osea digamos ojala wow uf
jaja video videos canal suscribete suscribe like comentarios parte juego juegos
eh ehm ehh mmm mm hmm hm mhm uh uhm um ah ahh oh uy uf ostras joder anda dale guay chulo mola molan brutal
increible increibles literal literalmente realmente verdad cosa cosas vez veces momento dia dias ano anos tio tia
tios tias vaya bah pff aja seguro segura incluso quizas tal cierto cierta sobre desde hasta durante segun hacer
hago hacemos ver veo vemos decir digo dices dicho puedes podemos paso tan tanto tanta bastante demasiado igual
es son era fue soy estoy eres somos sois fin por
""".split())

# Conectores típicos dentro de un título («Doom The Dark Ages», «Call of Duty»). «y» y «and» no: unirían
# «Minecraft y Fortnite».
CONECTORES = {"of", "the", "de", "del", "la", "los", "las"}

# Números escritos (ya sin acentos y en minúsculas) → dígitos.
_NUM_PAL = {
    "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7", "ocho": "8",
    "nueve": "9", "diez": "10", "once": "11", "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "dieciseis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19", "veinte": "20", "treinta": "30",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
# Romanos (en mayúsculas) → dígitos. «I» no: es el pronombre inglés y la palabra suelta.
_ROMANOS = {r: str(i) for i, r in enumerate(
    ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII",
     "XVIII", "XIX", "XX"], start=2)}

# Modificadores: lo que se HACE en el contexto → palabra en inglés para buscar clips.
# Cada entrada: (inglés, prefijos sin acentos; la palabra empieza por alguno).
MODIFICADORES = [
    ("looting", ("loote", "lootea", "saque", "botin", "loot")),
    ("shooting", ("dispar", "tirote", "shoot")),
    ("building", ("constru", "edific", "build")),
    ("boss fight", ("jefe", "boss")),
    ("cutscene", ("cinemat", "cutscene")),
    ("trailer", ("trailer", "trailers")),
    ("gameplay", ("gameplay", "jugand", "jugar", "jugamos", "jugue")),
    ("driving", ("conduc", "coche", "driving")),
    ("combat", ("pelea", "pelear", "combat", "batalla")),
    ("map", ("mapa", "mapas")),
    ("season update", ("temporada", "actualiz", "parche", "patch")),
    ("speedrun", ("speedrun",)),
    ("launch", ("lanzamiento", "lanzan")),
    ("character", ("personaje",)),
    ("weapons", ("arma", "armas", "weapon")),
    ("crafting", ("fabric", "craft")),
    ("stealth", ("sigilo", "stealth")),
    ("tutorial", ("tutorial",)),
    ("multiplayer", ("multijug", "multiplayer")),
    ("battle royale", ("royale",)),
]
MAX_MODS_HIT = 4

# Pieza de siglas: «G.», «T.», «A.», «G.T.A.» (con o sin punto final).
_PIEZA = re.compile(r"(?:[A-Z]\.)+[A-Z]?\.?|[A-Z]\.?")

# nkey: clave con los números ya en dígitos («GTA seis» → gta 6). key: clave tal cual.
_Tok = namedtuple("_Tok", "ini fin txt key nkey cap inicio")


def _clave(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto.lower().replace("’", "'"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).strip()


def _nclave(txt: str, prev, inicio: bool) -> str:
    """Clave con números en dígitos. Romanos solo en mayúsculas y tras otra palabra (no «vi» el verbo)."""
    k = _clave(txt)
    if k in _NUM_PAL:
        return _NUM_PAL[k]
    if txt in _ROMANOS and not inicio and prev is not None and not (txt == "X" and prev == "series"):
        return _ROMANOS[txt]
    return k


def _kn(nombre) -> tuple:
    """Clave (tupla) de un nombre ya con números en dígitos."""
    out: list[str] = []
    prev = None
    for i, x in enumerate(str(nombre or "").split()):
        c = _core(x)
        if not c:
            continue
        out.append(_nclave(c, prev, i == 0))
        prev = _clave(c)
    return tuple(out)


_SUBS = {}
for _f, _lista in SUBTITULOS.items():
    _SUBS[_kn(_f)] = sorted(((_kn(s), s) for s in _lista), key=lambda x: -len(x[0]))


# Sagas con entregas NUMERADAS: tras ellas un número dicho en palabras («GTA seis») es parte del nombre. En las demás
# (Fortnite, Minecraft…) solo si cierra la frase, para no hacer «Fortnite 2» de «jugué Fortnite dos horas».
NUMERADAS = {_kn(x) for x in (
    "GTA", "Grand Theft Auto", "Resident Evil", "Final Fantasy", "Call of Duty", "Black Ops", "Modern Warfare",
    "Battlefield", "FIFA", "EA Sports FC", "Death Stranding", "Spider-Man", "Mario Kart", "Halo", "Gears of War",
    "God of War", "The Witcher", "Fallout", "Borderlands", "Assassin's Creed", "Far Cry", "Silent Hill",
    "Metroid Prime", "Kingdom Hearts", "Dark Souls", "Diablo", "Street Fighter", "Tekken", "Mortal Kombat", "Hitman",
    "BioShock", "Portal", "Half-Life", "Metal Gear Solid", "Persona", "Overwatch", "Destiny", "Titanfall",
    "Red Dead Redemption", "Splatoon", "Nintendo Switch", "Switch", "PlayStation", "Horizon", "Cyberpunk", "Doom",
    "Dead Space", "Alan Wake", "Hollow Knight", "Monster Hunter", "Kingdom Come", "The Last of Us", "Uncharted",
    "Crash Bandicoot", "Spyro", "Rainbow Six", "Left 4 Dead", "Baldur's Gate", "Starcraft", "Warcraft", "Sims",
    "The Sims")}


def _numerada(clave) -> bool:
    return any(tuple(clave[i:]) in NUMERADAS for i in range(len(clave)))


def _subs_de(clave) -> list:
    """Subtítulos de la franquicia del nombre (busca por sus últimas palabras: «The Legend of Zelda» → Zelda)."""
    for i in range(len(clave)):
        if clave[i:] in _SUBS:
            return _SUBS[clave[i:]]
    return []


def _unir_siglas(raw: list) -> list:
    """Une piezas de siglas («G.» «T.» «A.» o «G.T.A.») en una sola palabra «GTA»."""
    out: list = []
    i = 0
    while i < len(raw):
        j = i
        while j < len(raw) and _PIEZA.fullmatch(raw[j][2].strip()):
            j += 1
        grupo = raw[i:j]
        letras = "".join(ch for x in grupo for ch in x[2] if ch.isalpha())
        if grupo and any("." in x[2] for x in grupo) and len(letras) >= 2:
            out.append([grupo[0][0], grupo[-1][1], letras])
            i = j
        else:
            out.append(raw[i])
            i += 1
    return out


def _tokens(words) -> list[_Tok]:
    """Palabras con contenido (sin signos), con su segundo de inicio/fin y si empiezan frase."""
    raw: list = []
    for w in words or []:
        try:
            ini, txt = float(w[0]), str(w[2])
        except (TypeError, ValueError, IndexError):
            continue
        try:
            fin = float(w[1])
        except (TypeError, ValueError, IndexError):
            fin = ini
        raw.append([ini, fin, txt])
    out: list[_Tok] = []
    inicio = True
    prev = None
    for ini, fin, txt in _unir_siglas(raw):
        c = _core(txt)
        if not c:
            if any(ch in txt for ch in ".!?…"):
                inicio = True
            continue
        k = _clave(c)
        out.append(_Tok(ini, fin, c, k, _nclave(c, prev, inicio), c[0].isupper(), inicio))
        prev = k
        inicio = txt.rstrip().endswith((".", "!", "?", "…"))
    return out


def _tabla(extra_terms=None, si=()) -> dict:
    """{clave de la frase (tupla con números en dígitos): (nombre a mostrar, prioridad)}."""
    t: dict = {}
    for nombre in CONOCIDOS:
        k = _kn(nombre)
        t.setdefault(k, (ALIAS.get(nombre, nombre), 2))
    # palabras clave confirmadas en el glosario (keyword_glossary): conocidas, con el nombre que puso el usuario
    for nombre in si or ():
        k = _kn(nombre)
        if k and _clave(nombre) not in STOP:
            t[k] = (" ".join(str(nombre).split()), 2)
    for w in vocabulary():
        nombre = _core(w)
        k = _kn(nombre)
        if not k or len(k) > MAX_FRASE or len(_clave(nombre)) < 3:
            continue
        if len(k) == 1 and (_clave(nombre) in STOP or _clave(nombre) in _NUM_PAL):
            continue
        t.setdefault(k, (nombre, 1))
    # subtítulos conocidos de 2+ palabras dichos SIN la saga delante: «Ocarina of Time» → «Zelda Ocarina of Time»
    for saga, subs in SUBTITULOS.items():
        for sub in subs:
            k = _kn(sub)
            if len(k) >= 2 and not all(x.isdigit() for x in k):
                t.setdefault(k, (f"{ALIAS.get(saga, saga)} {sub}", 2))
    # términos del usuario (nombres de sus carpetas por palabra clave): prioridad alta, como CONOCIDOS
    for term in extra_terms or []:
        nombre = " ".join(str(term or "").split())
        k = _kn(nombre)
        if not k or nombre in ("", "Sin nombre"):
            continue
        t[k] = (nombre, 2)
    return t


def _mods_de(claves) -> list[str]:
    out: list[str] = []
    for k in claves:
        for ingles, prefijos in MODIFICADORES:
            if ingles not in out and k.startswith(prefijos):
                out.append(ingles)
    return out


def _nombre_conocido_en(tabla, toks, j, largo_max) -> bool:
    """¿Empieza en j otro nombre conocido (de CONOCIDOS o de tus carpetas)? Entonces no se extiende."""
    for largo in range(min(largo_max, len(toks) - j), 0, -1):
        v = tabla.get(tuple(x.nkey for x in toks[j:j + largo]))
        if v is not None and v[1] == 2:
            return True
    return False


def _extender(toks, p, largo, nombre, clave, tabla, largo_max):
    """Amplía un nombre conocido con lo que sigue: subtítulo, número o palabras con mayúscula.
    Devuelve (palabras que ocupa, nombre completo)."""
    n = len(toks)
    j = p + largo
    partes = [nombre]
    subs = _subs_de(clave)
    usadas = 0
    while j < n and usadas < MAX_EXTENSION:
        t = toks[j]
        if t.inicio or t.ini - toks[j - 1].fin > PAUSA:
            break
        sub = next((x for x in subs if j + len(x[0]) <= n
                    and tuple(y.nkey for y in toks[j:j + len(x[0])]) == x[0]), None)
        if sub is not None:
            partes.append(sub[1])
            j += len(sub[0])
            usadas += len(sub[0])
            continue
        if t.nkey.isdigit() and len(t.nkey) <= 3:
            # un número se une al nombre si la saga tiene entregas numeradas (GTA, Resident Evil…); si no, solo
            # si cierra la frase («el nuevo Fortnite 2.»), para no hacer «Fortnite 2» de «Fortnite dos horas»
            numerada = _numerada(clave) or any(all(y.isdigit() for y in s_[0]) for s_ in subs)
            cierra = (j + 1 >= n or toks[j + 1].inicio or toks[j + 1].ini - t.fin > PAUSA
                      or str(t.txt).rstrip()[-1:] in ".,;:!?")
            if numerada or cierra:
                partes.append(t.nkey)
                j += 1
                usadas += 1
                continue
            break
        if _nombre_conocido_en(tabla, toks, j, largo_max):
            break
        if t.cap and t.key not in STOP:
            partes.append(t.txt)
            j += 1
            usadas += 1
            continue
        if (t.key in CONECTORES and j + 1 < n and toks[j + 1].cap and not toks[j + 1].inicio
                and toks[j + 1].key not in STOP and toks[j + 1].ini - t.fin <= PAUSA):
            partes.append(t.txt)
            j += 1
            usadas += 1
            continue
        break
    return j - p, " ".join(partes)


def _contiene(grande, chica) -> bool:
    m = len(chica)
    return any(grande[i:i + m] == chica for i in range(len(grande) - m + 1))


def _quitar_solapes(grupos: dict) -> dict:
    """«Zelda» y «Zelda Ocarina of Time» en el mismo momento son una sola mención (la larga)."""
    orig = {k: list(g["pos"]) for k, g in grupos.items()}
    for ka, ga in grupos.items():
        for kb, pos_b in orig.items():
            if len(kb) > len(ka) and _contiene(kb, ka):
                ga["pos"] = [(p, l) for p, l in ga["pos"]
                             if not any(p < q + m and q < p + l for q, m in pos_b)]
    return {k: g for k, g in grupos.items() if g["pos"]}


_CONSULTAS_MAX = 15       # consultas a internet por llamada (las respuestas de la caché no cuentan)
_DIAS_CACHE = 30          # una consulta por término como mucho cada 30 días
_TIPOS_CONOCIDOS = ("juego", "saga", "consola", "compañía")


def _resolver(nombres, glossary, online) -> dict:
    """nombres: [(nombre, nº de apariciones)]. Devuelve {clave: info} de lo que se sabe: caché del glosario y, si
    online, consultas a internet (máximo _CONSULTAS_MAX; si no hay conexión se para). La caché se guarda."""
    agregado: dict = {}
    for nombre, cuenta in nombres:
        k = _clave(nombre)
        if not k:
            continue
        if k not in agregado:
            agregado[k] = [nombre, 0]
        agregado[k][1] += cuenta
    out: dict = {}
    red = 0
    for k, (nombre, _cuenta) in sorted(agregado.items(), key=lambda x: -x[1][1]):
        info = _kg.web_get(nombre, glossary, max_dias=_DIAS_CACHE)
        if info is None and online:
            if red >= _CONSULTAS_MAX:
                continue
            red += 1
            info = game_lookup.classify(nombre)
            if info is None:           # sin conexión: no se insiste con los demás
                break
            _kg.web_put(nombre, info, glossary)
        if info is not None:
            out[k] = info
    return out


def find_mentions(project, extra_terms=None, glossary=None, online=False) -> list[dict]:
    """Lo que se dice en las transcripciones de los medios del proyecto, ordenado por importancia.
    extra_terms: nombres extra a buscar como CONOCIDOS (p. ej. las carpetas por palabra clave del usuario).
    glossary: el glosario de keyword_glossary.load(). «si» se busca como conocido; «no» nunca sale; la caché
    «web» se usa siempre. online=True: los nombres propios sin resolver se consultan en internet (game_lookup).
    Sin glossary y sin online, el resultado es el de siempre."""
    if online and glossary is None:
        glossary = _kg.load()
    usar_glos = glossary is not None
    si = _kg.yes_terms(glossary) if usar_glos else []
    no = set(glossary.get("no") or []) if usar_glos else set()
    tabla = _tabla(extra_terms, si)
    largo_max = max([MAX_FRASE] + [len(k) for k in tabla])
    partes: list = []
    for media_id, tr in (getattr(project, "transcripts", None) or {}).items():
        toks = _tokens((tr or {}).get("words"))
        if not toks:
            continue
        n = len(toks)
        grupos: dict = {}
        p = 0
        while p < n:
            hit = None
            for largo in range(min(largo_max, n - p), 0, -1):          # primero la frase más larga
                clave = tuple(t.nkey for t in toks[p:p + largo])
                if clave in tabla:
                    nombre, prio = tabla[clave]
                    hit = (clave, largo, nombre, prio)
                    break
            if hit is None:
                t = toks[p]
                if not (t.cap and t.key not in STOP):
                    p += 1
                    continue
                q = p + 1          # nombre propio: mayúsculas seguidas, sin cruzar un inicio de frase
                while (q < n and q - p < MAX_PROPIO and toks[q].cap and not toks[q].inicio
                       and toks[q].key not in STOP and len(toks[q].key) >= 2
                       and not _nombre_conocido_en(tabla, toks, q, largo_max)):
                    q += 1
                if q - p == 1 and (t.inicio or len(t.key) < 3):
                    p += 1         # mayúscula por ser inicio de frase: no es un nombre
                    continue
                clave = tuple(x.key for x in toks[p:q])
                hit = (clave, q - p, " ".join(x.txt for x in toks[p:q]), 0)
            clave, largo, nombre, prio = hit
            if prio == 2:          # juego o compañía conocidos: se amplía con su número o subtítulo
                largo, nombre = _extender(toks, p, largo, nombre, clave, tabla, largo_max)
            gk = _kn(nombre)
            g = grupos.setdefault(gk, {"nombre": nombre, "prio": prio, "pos": [], "sup": Counter()})
            if prio > g["prio"]:
                g["prio"], g["nombre"] = prio, nombre
            g["pos"].append((p, largo))
            g["sup"][nombre] += 1
            p += largo

        grupos = _quitar_solapes(grupos)
        if no:
            grupos = {k: g for k, g in grupos.items() if _clave(g["nombre"]) not in no}
        partes.append((media_id, toks, n, grupos))

    if usar_glos:
        # candidatos (nombres propios sin resolver) → caché y, si online, internet
        cand = []
        for _mid, _toks, _n, grupos in partes:
            for g in grupos.values():
                if g["prio"] == 0:
                    cand.append((g["sup"].most_common(1)[0][0], len(g["pos"])))
        resueltos = _resolver(cand, glossary, online)
        for _mid, _toks, _n, grupos in partes:
            for g in grupos.values():
                if g["prio"] != 0:
                    continue
                nombre = g["sup"].most_common(1)[0][0]
                info = resueltos.get(_clave(nombre))
                if info is None:
                    continue
                g["web"] = info.get("tipo", "ninguno")
                if g["web"] in _TIPOS_CONOCIDOS:
                    g["prio"], g["nombre"] = 2, nombre

    resultado: list[dict] = []
    for media_id, toks, n, grupos in partes:
        ix = DeepIndex(project, media_id)        # (también dentro de clips compuestos ⧉)
        for gk, g in grupos.items():
            nombre = g["nombre"] if g["prio"] > 0 else g["sup"].most_common(1)[0][0]
            hits = []
            for p0, largo in g["pos"]:
                src = toks[p0].ini
                fin = min(n, p0 + largo + CONTEXTO)
                ventana = range(max(0, p0 - CONTEXTO), fin)
                contexto = " ".join(toks[j].txt for j in ventana)
                mods = _mods_de(toks[j].key for j in ventana if not (p0 <= j < p0 + largo))
                tl = ix.time(src)
                hits.append({"src": round(src, 2), "tl": None if tl is None else round(tl, 2),
                             "context": contexto, "mods": mods[:MAX_MODS_HIT]})
            cuenta: Counter = Counter()
            orden: dict = {}
            for h in hits:
                for m in h["mods"]:
                    cuenta[m] += 1
                    orden.setdefault(m, len(orden))
            mods_total = sorted(cuenta, key=lambda m: (-cuenta[m], orden[m]))
            entrada = {"term": nombre, "media_id": media_id, "hits": hits, "count": len(hits),
                       "mods": mods_total, "known": g["prio"] > 0}
            if g.get("web"):
                entrada["web"] = g["web"]
            resultado.append(entrada)
    resultado.sort(key=lambda e: (-(e["count"] * (3 if e["known"] else 1)), e["term"].lower()))
    return resultado


def verify_online(mentions, glossary=None) -> list[dict]:
    """Consulta en internet las menciones que aún no son conocidas (para llamarla en segundo plano). Devuelve una
    lista nueva, ya ordenada: las que resultan juego, saga, consola o compañía pasan a conocidas; a todas se les pone
    «web» (tipo o «ninguno»). Usa y actualiza la caché del glosario; no toca las menciones de entrada."""
    if glossary is None:
        glossary = _kg.load()
    no = set(glossary.get("no") or [])
    cand = [(m["term"], int(m.get("count", 0))) for m in mentions
            if not m.get("known") and _clave(m["term"]) not in no]
    resueltos = _resolver(cand, glossary, True)
    out: list[dict] = []
    for m in mentions:
        e = dict(m)
        info = None if m.get("known") else resueltos.get(_clave(m["term"]))
        if info is not None:
            e["web"] = info.get("tipo", "ninguno")
            if e["web"] in _TIPOS_CONOCIDOS:
                e["known"] = True
        out.append(e)
    out.sort(key=lambda e: (-(e["count"] * (3 if e["known"] else 1)), e["term"].lower()))
    return out
