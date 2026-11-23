"""
«Dijiste…»: qué palabras de tu narración son nombres o temas (Fortnite, Epic Games…) y en qué momentos salen.

  find_mentions(project) -> [{"term", "media_id", "hits": [{"src", "tl", "context", "mods"}], "count", "mods", "known"}]

· Candidatos: nombres propios (palabras con mayúscula fuera del inicio de frase; se unen «Epic Games»),
  palabras de tu vocabulario (editoria/ai/word_fix.py: vocabulary()) y una lista corta de juegos y compañías.
· Juegos con número o subtítulo: «GTA seis», «GTA VI», «G.T.A. 6» son «GTA 6»; «Zelda ocarina of time» es
  «Zelda Ocarina of Time»; «Resident Evil cuatro» es «Resident Evil 4». Los números (en palabras, romanos o
  dígitos) solo se unen tras un nombre conocido, así que «uno de los mejores» no es ningún número.
· Variantes de la misma palabra clave, un solo grupo (20/11): «gta5», «GTA-5», «GTA V», «gta cinco» y «ge te a
  cinco» (letras deletreadas, si forman un nombre de tus carpetas, del glosario o conocido) son «GTA 5»; el nombre
  que se ve es el de tu carpeta si existe, si no el del glosario, si no el del nombre conocido o el más dicho.
· Variantes de TODA palabra clave (20/11, ver ai/keyword_variants.py): números hasta 9999 en palabras («Cyberpunk dos
  mil setenta y siete»), sin espacios («spiderman» = «Spider-Man»), apóstrofos, «&»/«and»/«y», artículo inicial
  («Witcher» = «The Witcher»), siglas de un nombre conocido («COD» = «Call of Duty»), plurales y grafías de palabras
  corrientes («zombie» = «zombis»), errores de Whisper («Fortnight» = «Fortnite»), y lo que decidas con «Separar…» y
  «Unir con…» (glosario). Cada mención trae «variantes»: cómo más se dijo («gta cinco», «GTA V»).
· Nada de basura: los nombres propios sin confirmar que son palabras corrientes del español («Peor», «Bueno»…,
  según el diccionario es_MX de Reclaimer y una lista de palabras vacías) no salen; ni tartamudeos («peor peor»,
  «GTA GTA 5»), ni nombres que crucen una pausa larga o un punto.
· Nombres de varias palabras enteros («Red Dead Redemption 2», «The Game Awards») y sin repetir sus trozos: un
  nombre propio sin confirmar que es el principio de otro más largo que también dices se suma al largo.
· Tu glosario manda: «Es palabra clave» siempre sale; «No es palabra clave» nunca (en ninguna de sus variantes).
· «src» = segundo del archivo de narración; «tl» = momento en la línea de tiempo (None si ese tramo está cortado).
· «context» = unas palabras alrededor (±8). «mods» = lo que se hace en ese contexto, en inglés, para buscar
  clips («looteando» → looting). «mods» de la mención = los de todas sus apariciones, por frecuencia.
Sin Qt.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, namedtuple
from functools import lru_cache

from ..core.mapping import DeepIndex
from ..core import keyword_folders as _KF
from ..core.keyword_folders import canon as _canon
from .keyword_variants import GRAFIAS as _GRAFIAS
from .keyword_variants import Variantes, clave_dicho as _clave_dicho, fonetica as _fonetica, iniciales as _iniciales
from .keyword_variants import sigla_valida
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
peor peores mejor mejores malo mala malos malas buen grande grandes gran pequeno pequena nuevo nueva nuevos nuevas
viejo vieja primer primera ultima ultimos mayor menor tipo tipos forma manera lado cara rato cuenta caso
super hiper mega enorme facil dificil rapido rapida lento lenta largo larga corto corta alto alta bajo baja
mal mala feo fea bonito bonita raro rara normal tremendo tremenda horrible terrible maravilloso hermoso
porque sea sean seria sido estar estado tener tiene tienen tenia hacia haber habia habra han ha he hemos
mio mia tuyo tuya suyo suya nuestro nuestra cual cuales quien quienes cuanto cuanta cuantos cuantas
aquel aquella aquellos aquellas alla adios chao saludos hermano hermanos bro wey guey neta oki vos
nomas apenas casi luego pronto tarde temprano mientras entre contra hacia tras ante bajo segun sin con para
en al
""".split())

# Letras dichas una a una («ge te a» → GTA): solo cuentan si juntas forman un nombre de tus carpetas, del glosario o
# conocido. También las letras sueltas tal cual («G T A»).
LETRAS = {"a": "a", "be": "b", "ce": "c", "de": "d", "e": "e", "efe": "f", "ge": "g", "hache": "h", "i": "i",
          "jota": "j", "ka": "k", "ele": "l", "eme": "m", "ene": "n", "o": "o", "pe": "p", "cu": "q", "erre": "r",
          "ese": "s", "te": "t", "u": "u", "uve": "v", "ve": "v", "equis": "x", "ye": "y", "zeta": "z"}
LETRAS.update({ch: ch for ch in "abcdefghijklmnopqrstuvwxyz"})
MAX_DELETREO = 6
TARTAMUDEO = 0.9    # s: la misma palabra (o el principio de la siguiente mención) repetida tan seguida no cuenta dos veces

_COMUNES: set | None = None
_CON_PLURAL: set = set()      # palabras corrientes que admiten plural (marca «S» del diccionario: «zombi», «flor»)
_PROPIOS_DIC: set = set()     # nombres propios del diccionario («Dios», «Marcos», «Ángeles»)


def _comunes() -> set:
    """Las palabras corrientes del español (claves sin tildes): el diccionario es_MX de Reclaimer (Hunspell, en
    assets/diccionarios), solo sus entradas en minúscula (las de mayúscula son nombres propios). Se lee una vez.
    De paso apunta qué palabras admiten plural (_CON_PLURAL) y los nombres propios (_PROPIOS_DIC)."""
    global _COMUNES
    if _COMUNES is not None:
        return _COMUNES
    import os
    out: set = set()
    ruta = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "diccionarios", "es_MX.dic")
    try:
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            next(f, None)                                   # (la primera línea es el número de entradas)
            for linea in f:
                w, _, marcas = linea.strip().partition("/")
                w = w.strip()
                if not w or " " in w:
                    continue
                if w[0].islower():
                    out.add(_clave(w))
                    if "S" in marcas:
                        _CON_PLURAL.add(_clave(w))
                else:
                    _PROPIOS_DIC.add(_clave(w))
    except OSError:
        pass
    out.update(("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"))   # (faltan en el diccionario)
    _COMUNES = out
    return out


_VOCALES = "aeiou"
# Plurales cuyo singular significa otra cosa («Mercedes» no es «merced», «esposas» no es «esposa»): no se recortan.
_NO_RECORTAR = {"mercedes", "esposas", "bienes", "modales", "letras", "cortes", "gafas", "lentes", "celos", "restos",
                "honores", "amores", "favores", "intereses", "finanzas", "pesas", "viveres", "afueras"}


def _singular_de(w: str) -> str | None:
    """«zombis» → «zombi», «flores» → «flor»: solo si de verdad es su plural (la raíz admite plural en el diccionario
    y el plural no es una palabra propia: «dios», «celos», «andes» y «dados» no se recortan; «dio» y «ande» son
    formas verbales sin plural)."""
    c = _comunes()
    if not w.isalpha() or w in c or w in _PROPIOS_DIC or w in _NO_RECORTAR:
        return None
    if w.endswith("ces") and w[:-3] + "z" in _CON_PLURAL:
        return w[:-3] + "z"
    if w.endswith("es") and w[:-2] in _CON_PLURAL and w[-3:-2] not in _VOCALES:
        return w[:-2]
    if w.endswith("s") and w[:-1] in _CON_PLURAL and w[-2:-1] in _VOCALES:
        return w[:-1]
    return None


def _plural_de(w: str) -> str | None:
    """«zombi» → «zombis», «flor» → «flores» (solo palabras corrientes que admiten plural)."""
    _comunes()
    if w not in _CON_PLURAL:
        return None
    if w.endswith("z"):
        return w[:-1] + "ces"
    return w + ("s" if w[-1:] in _VOCALES else "es")


def _es_comun(k: str) -> bool:
    """¿Es una palabra corriente del español (o una forma simple suya: plural, femenino)? k: clave sin tildes."""
    if k in STOP:
        return True
    c = _comunes()
    if not c or len(k) < 2:
        return False
    if k in c:
        return True
    if k.endswith("es") and k[:-2] in c or k.endswith("s") and k[:-1] in c:
        return True
    if k.endswith("a") and k[:-1] + "o" in c or k.endswith("as") and k[:-2] + "o" in c:
        return True
    return False


def precargar():
    """Lee el diccionario de palabras corrientes (≈0,1 s) para que el primer «Dijiste…» no lo espere."""
    _comunes()

# Conectores típicos dentro de un título («Doom The Dark Ages», «Call of Duty»). «y» y «and» no: unirían
# «Minecraft y Fortnite».
CONECTORES = {"of", "the", "de", "del", "la", "los", "las"}

# Números escritos de UNA palabra (ya sin acentos y en minúsculas) → dígitos: 1–99 y «cien» (keyword_folders).
# Los de varias palabras («dos mil setenta y siete») los lee _numero_en con keyword_folders.leer_numero.
_NUM_PAL = dict(_KF.NUM_UNA)
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
_Tok = namedtuple("_Tok", "ini fin txt key nkey cap inicio coma")


@lru_cache(maxsize=65536)
def _clave(texto: str) -> str:
    """(⚡ con caché: en una narración las mismas palabras se repiten miles de veces)"""
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


_SIGNOS = ".,;:!?…"
_PEGADO = re.compile(r"^([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,})(?:-?(\d{1,3})|-([IVX]{1,4}))$")


def _tokens(words, primeras=()) -> list[_Tok]:
    """Palabras con contenido (sin signos), con su segundo de inicio/fin y si empiezan frase. «gta5», «GTA-5» y
    «GTA-V» se parten en dos («GTA» «5») si la primera parte empieza un nombre de la tabla (primeras)."""
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
        m = _PEGADO.match(c) if primeras else None
        if m and _clave(m.group(1)) in primeras:
            letras, num = m.group(1), m.group(2) or m.group(3)
            k = _clave(letras)
            coma = txt.rstrip()[-1:] in _SIGNOS
            out.append(_Tok(ini, fin, letras, k, _nclave(letras, prev, inicio), letras[0].isupper(), inicio, False))
            out.append(_Tok(ini, fin, num, _clave(num), _nclave(num, k, False), num[0].isupper(), False, coma))
            prev = _clave(num)
        else:
            k = _clave(c)
            out.append(_Tok(ini, fin, c, k, _nclave(c, prev, inicio), c[0].isupper(), inicio,
                            txt.rstrip()[-1:] in _SIGNOS))
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
        if k:                         # (tu glosario manda: aunque sea una palabra corriente o vacía)
            t[k] = (" ".join(str(nombre).split()), 2)
    for w in vocabulary():
        nombre = _core(w)
        k = _kn(nombre)
        if not k or len(k) > MAX_FRASE or len(_clave(nombre)) < 3:
            continue
        if len(k) == 1 and (_clave(nombre) in STOP or _clave(nombre) in _NUM_PAL or _es_comun(_clave(nombre))):
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


_ARTICULO_INICIAL = ("the", "el", "la", "los", "las")
_CONJ = ("&", "and", "y")


def _comun_exacta(w: str) -> bool:
    """¿Palabra corriente del diccionario (tal cual, sin buscar plurales) o vacía?"""
    return w in STOP or w in _comunes()


def _ampliar(tabla: dict, propios) -> dict:
    """Variantes de escritura de los nombres conocidos para DETECTARLOS (no solo agruparlos). Añade a la tabla
    «spider man» y «baldurs gate» (sin guion ni apóstrofo) y «last of us» (sin artículo), y devuelve {palabra: (nombre,
    prioridad)} de una sola palabra: «spiderman», «callofduty», «witcher» y los plurales y grafías de tus palabras
    corrientes («zombie», «zombies» para tu carpeta «Zombis»)."""
    alt: dict = {}
    for k, (nombre, prio) in list(tabla.items()):
        if prio != 2 or not k:
            continue
        partes = tuple(x for tok in k for x in tok.replace("'", "").replace("-", " ").split() if x)
        if len(partes) >= 2 and partes != k:
            tabla.setdefault(partes, (nombre, prio))
        if len(partes) >= 3 and any(x in _CONJ for x in partes[1:-1]):    # «&» / «and» / «y» dan igual
            for cj in _CONJ:
                tabla.setdefault(tuple(cj if (0 < i < len(partes) - 1 and x in _CONJ) else x
                                       for i, x in enumerate(partes)), (nombre, prio))
        if len(partes) >= 2 and partes[0] in _ARTICULO_INICIAL:
            resto = partes[1:]
            if len(resto) >= 2:
                tabla.setdefault(resto, (nombre, prio))
            elif len(resto[0]) >= 5 and resto[0].isalpha() and not _comun_exacta(resto[0]):
                alt.setdefault(resto[0], (nombre, prio))
        junto = "".join(partes[1:] if partes[0] in _ARTICULO_INICIAL and len(partes) > 2 else partes)
        if len(partes) >= 2 and len(junto) >= 6 and junto.isalpha() and not _comun_exacta(junto):
            alt.setdefault(junto, (nombre, prio))
    for nombre in propios or ():
        k = _kn(nombre)
        if len(k) != 1 or not k[0].isalpha() or k not in tabla:
            continue
        w = k[0]
        if w in _PROPIOS_DIC:
            continue                                     # (un nombre propio no: «Marcos», «Dolores», «Dios»)
        sing = _singular_de(w)
        raiz = _GRAFIAS.get(w) or sing or w
        if not (_comun_exacta(w) or sing or w in _GRAFIAS or raiz in _GRAFIAS.values()):
            continue                                     # (solo palabras corrientes)
        # Una carpeta en SINGULAR de palabra corriente («Persona», «Control») no atrapa su plural en minúscula: el
        # recuento no se infla. Solo una carpeta en plural («Zombis») une sus formas («zombi», «zombie», «zombies»).
        es_plural = sing is not None or (w in _GRAFIAS and w.endswith("s"))
        if es_plural:
            plural = _plural_de(raiz)
            formas = {raiz, None if plural in _comunes() else plural}     # («martes» es otra palabra, no «marte»s)
            formas |= {g for g, r in _GRAFIAS.items() if r == raiz and " " not in g}
        else:
            formas = {raiz} | {g for g, r in _GRAFIAS.items() if r == raiz and " " not in g and not g.endswith("s")}
        for f in formas:
            if f and f != w and len(f) >= 3 and (f,) not in tabla:
                alt.setdefault(f, tabla[k])
    return alt


@lru_cache(maxsize=65536)
def _mods_de_clave(k: str) -> tuple:
    return tuple(ingles for ingles, prefijos in MODIFICADORES if k.startswith(prefijos))


def _mods_de(claves) -> list[str]:
    out: list[str] = []
    for k in claves:
        for ingles in _mods_de_clave(k):
            if ingles not in out:
                out.append(ingles)
    return out


def _largos(tabla) -> dict:
    """{primera palabra: largos posibles de mayor a menor}: así cada posición solo prueba lo que puede ser
    (⚡ con 2 h de narración, de ~20 tuplas por palabra a 0–2)."""
    out: dict = {}
    for k in tabla:
        if k:
            out.setdefault(k[0], set()).add(len(k))
    return {w: tuple(sorted(s, reverse=True)) for w, s in out.items()}


def _nombre_conocido_en(tabla, toks, j, largos) -> bool:
    """¿Empieza en j otro nombre conocido (de CONOCIDOS o de tus carpetas)? Entonces no se extiende."""
    n = len(toks)
    for largo in largos.get(toks[j].nkey, ()):
        if j + largo > n:
            continue
        v = tabla.get(tuple(x.nkey for x in toks[j:j + largo]))
        if v is not None and v[1] == 2:
            return True
    return False


def _cierra(toks, k: int) -> bool:
    """¿La palabra k-1 cierra la frase (fin, pausa larga, signo o empieza otra frase)?"""
    n = len(toks)
    return k >= n or toks[k].inicio or toks[k].ini - toks[k - 1].fin > PAUSA or toks[k - 1].coma


# Lo que convierte un número en una CANTIDAD («cuarenta horas», «cien veces», «siete de cada diez»): tras el nombre de
# una saga, ese número nunca es la entrega.
UNIDADES = set("""
hora horas minuto minutos min segundo segundos seg vez veces dia dias semana semanas mes meses ano anos decada decadas
siglo siglos millon millones millar millares mil billon billones copia copias euro euros dolar dolares peso pesos
libra libras yen yenes persona personas jugador jugadores gente usuario usuarios suscriptor suscriptores seguidor
seguidores visita visitas partida partidas punto puntos nivel niveles vida vidas muerte muertes kill kills estrella
estrellas metro metros kilometro kilometros km kilo kilos gb mb tb fps hz ghz cm mm pulgada pulgadas porciento
capitulo capitulos episodio episodios mision misiones jefe jefes enemigo enemigos arma armas bala balas
hour hours minute minutes second seconds time times day days week weeks month months year years million millions
thousand copy copies dollar dollars player players people percent point points level levels
""".split())


def _cantidad(toks, k: int) -> bool:
    """¿Lo que sigue a un número (en k) lo hace una cantidad? Unidades («horas», «veces», «millones»…), «de cada»,
    «por ciento», «o/a + otro número» («dos o tres horas»)."""
    n = len(toks)
    if k >= n or toks[k].inicio or toks[k - 1].coma:
        return False
    w = toks[k].key
    if w in UNIDADES:
        return True
    sig = toks[k + 1].key if k + 1 < n else ""
    if w == "de" and sig in ("cada", "los", "las"):
        return True
    if w in ("por", "per") and sig in ("ciento", "cien", "cent"):
        return True
    if w in ("o", "u", "a", "y", "or", "to") and k + 1 < n and (toks[k + 1].nkey.isdigit()
                                                              or toks[k + 1].key in _KF._EMPIEZA_NUM):
        return True
    return False


def _numero_en(toks, j: int):
    """(valor, palabras) del número que empieza en j: cifras, romano o en palabras («dos mil setenta y siete»,
    «veintitrés», «twenty twenty»), sin cruzar una pausa, un signo ni otra frase. None si no hay número."""
    t = toks[j]
    if t.nkey.isdigit() and not t.key.isalpha():                 # cifras («2077») o romano («V»)
        return (int(t.nkey), 1) if len(t.nkey) <= 4 else None
    if not (t.nkey.isdigit() or t.key in _KF._EMPIEZA_NUM):
        return None
    claves = [t.key]
    for q in range(j + 1, min(len(toks), j + 8)):
        if toks[q].inicio or toks[q].ini - toks[q - 1].fin > PAUSA or str(toks[q - 1].txt).rstrip()[-1:] in ".,;:!?":
            break
        claves.append(toks[q].key)
    r = _KF.leer_numero(claves, 0)
    if r is None and t.nkey.isdigit():
        return int(t.nkey), 1
    return r


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
        if t.inicio or t.ini - toks[j - 1].fin > PAUSA or toks[j - 1].coma:   # (una coma también corta)
            break
        if t.key in ("parte", "part") and j + 1 < n and not t.coma and _numero_en(toks, j + 1) is not None \
                and not _cantidad(toks, j + 1 + _numero_en(toks, j + 1)[1]):
            j += 1                                       # «Last of Us Parte dos» → The Last of Us 2
            usadas += 1
            t = toks[j]
        sub = next((x for x in subs if j + len(x[0]) <= n
                    and tuple(y.nkey for y in toks[j:j + len(x[0])]) == x[0]), None)
        if sub is not None:
            partes.append(sub[1])
            j += len(sub[0])
            usadas += len(sub[0])
            continue
        num = _numero_en(toks, j)
        if num is not None:
            # un número se une al nombre si la saga tiene entregas numeradas (GTA, Resident Evil…); si no, solo
            # si cierra la frase («el nuevo Fortnite 2.»), para no hacer «Fortnite 2» de «Fortnite dos horas».
            # Hasta 999, o un año de título («Cyberpunk dos mil setenta y siete», «Battlefield 2042»); «dos mil
            # horas» no es ninguna entrega.
            # Nunca si es una cantidad («Halo cuarenta horas», «GTA cien veces», «siete de cada diez»). En palabras y
            # sin cerrar la frase, solo un número pequeño (≤ 20, una palabra: «GTA cinco es…»); los grandes y los años,
            # solo cerrando la frase o escritos en cifras (o si el nombre con ese número es tuyo: tu carpeta).
            valor, ocupa = num
            k = j + ocupa
            if _cantidad(toks, k):
                break
            numerada = (_numerada(clave) or _numerada(_kn(nombre))           # («last of us» → The Last of Us)
                        or any(all(y.isdigit() for y in s_[0]) for s_ in subs))
            valido = valor < 1000 or (1900 <= valor <= 2099 and valor % 100)
            cifras = not t.key.isalpha() or t.key in _KF._ROMANOS
            if tuple(clave) + (str(valor),) in tabla:
                ok = True
            elif _cierra(toks, k):
                ok = valido
            elif cifras:
                ok = numerada and valido
            else:
                ok = numerada and valor <= 20 and ocupa == 1
            if ok:
                partes.append(str(valor))
                j = k
                usadas += ocupa
                continue
            break
        if (t.key in _KF.ORDINALES and (_numerada(clave) or _numerada(_kn(nombre))) and toks[j - 1].key not in _KF.ARTICULOS
                and _cierra(toks, j + 1)):
            partes.append(str(_KF.ORDINALES[t.key]))    # «Halo segundo.» → Halo 2 (solo cerrando la frase: «un
            j += 1                                       #  segundo», «segundo a segundo» no)
            usadas += 1
            continue
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


def _basura(g) -> bool:
    """Un nombre propio SIN confirmar que no es una palabra clave: todas sus palabras son corrientes o vacías
    («Peor», «El Peor», «Bueno»), o es la misma palabra repetida."""
    claves = [_clave(x) for x in g["sup"].most_common(1)[0][0].split()]
    claves = [k for k in claves if k]
    if not claves:
        return True
    if len(set(claves)) == 1 and len(claves) > 1:
        return True
    if len(claves) > 1:            # (varias palabras con mayúscula seguidas: un título, aunque sean corrientes —
        return all(k in STOP or k.isdigit() for k in claves)   #  «Ruinas Eternas»—; solo fuera si son vacías)
    return _es_comun(claves[0]) or claves[0].isdigit()


def _dichos(g) -> Counter:
    """Cómo se dijo el grupo (lo oído en cada momento que le queda)."""
    d = g.get("dichos") or {}
    return Counter(d.get(x) or g["nombre"] for x in g["pos"])


def _es_sigla(dicho: str) -> bool:
    s = dicho.replace(".", "").replace(" ", "")
    return 2 <= len(s) <= 6 and s.isalpha() and s.isupper()


def _unir_en(juntos: dict, c: str, g: dict):
    if c in juntos:
        o = juntos[c]
        mas = len(g["pos"]) > len(o["pos"])
        o["pos"] = sorted(set(o["pos"]) | set(g["pos"]))
        o["sup"].update(g["sup"])
        o.setdefault("dichos", {}).update(g.get("dichos") or {})
        if g["prio"] > o["prio"] or (g["prio"] == o["prio"] and mas and not o.get("fijo")):
            o["prio"], o["nombre"] = g["prio"], g["nombre"]
            o["fijo"] = o.get("fijo") or g.get("fijo")
    else:
        juntos[c] = g


def _limpiar(grupos: dict, preferido: dict, V: Variantes | None = None, no_c=frozenset(), si_reps=()) -> dict:
    """Variantes de la misma palabra clave en UN grupo (ver keyword_variants: números, sin espacios, siglas, plurales,
    errores de Whisper, «Separar…» / «Unir con…»), con el nombre de tu carpeta o tu glosario si existe; fuera lo marcado
    «No es palabra clave» (las veces dichas así) y la basura; y un nombre propio sin confirmar que es el principio de
    otro más largo que también dices («Red Dead» y «Red Dead Redemption 2») se suma al largo."""
    V = V or Variantes()
    juntos: dict = {}
    # nombres dichos ENTEROS en esta narración (y los de tu glosario): una sigla solo vale si su nombre completo es uno
    dichos_enteros = set(si_reps)
    for gk, g in grupos.items():
        if not g.get("sep"):
            dichos_enteros.add(V.clave(g["nombre"]).partition("|")[0])
    for gk, g in grupos.items():
        dichos = g.get("dichos") or {}
        if no_c:
            g["pos"] = [x for x in g["pos"] if _KF.compacta(dichos.get(x) or "") not in no_c]
            if not g["pos"] or _KF.compacta(g["nombre"]) in no_c or any(_KF.compacta(s) in no_c for s in g["sup"]):
                continue
        oido = _dichos(g)
        if g.get("sep"):                                  # «Separar…»: lo dicho así va aparte, tal cual
            c = "§" + gk[1]
            g["nombre"] = oido.most_common(1)[0][0]
            g["sup"] = Counter({g["nombre"]: len(g["pos"])})
            g["fijo"] = True
        else:
            sigla = any(_es_sigla(d) for d in oido)
            c = V.clave(g["nombre"], tuple(oido), sigla=sigla, validas=dichos_enteros if sigla else None)
            manual = V._union_manual(g["nombre"], oido)
            if c in preferido:                            # (tu carpeta o tu glosario: confirmado, con su nombre)
                g["prio"], g["nombre"], g["fijo"] = max(g["prio"], 2), preferido[c], True
            elif manual is not None:                      # «Unir con…»: el nombre del grupo elegido
                g["prio"], g["nombre"], g["fijo"] = max(g["prio"], 1), V.nombre_de(c) or manual, True
            elif g["prio"] == 0:
                conocido = V.nombre_de(c)                 # sigla o error de Whisper de un nombre conocido
                if conocido is not None:
                    g["prio"], g["nombre"] = 2, conocido
            if g["prio"] == 0 and _basura(g):
                continue
        _unir_en(juntos, c, g)
    _unir_detectados(juntos, V)
    claves = {c: tuple(_canon(g["nombre"]).split()) for c, g in juntos.items()}
    for c, g in list(juntos.items()):
        if g["prio"] != 0 or g.get("sep"):
            continue
        largo = max((c2 for c2 in juntos if c2 != c and len(claves[c2]) > len(claves[c])
                     and claves[c2][:len(claves[c])] == claves[c]), key=lambda c2: len(juntos[c2]["pos"]), default=None)
        if largo is not None:
            o = juntos[largo]
            o["pos"] = sorted(set(o["pos"]) | set(g["pos"]))
            o.setdefault("dichos", {}).update(g.get("dichos") or {})
            del juntos[c]
    return juntos


def _unir_detectados(juntos: dict, V: Variantes):
    """Nombres ya detectados en el proyecto (sin confirmar, dichos 3+ veces) como «conocidos» para lo dicho 1–2 veces:
    si suena IGUAL (6+ letras) o es su sigla en mayúsculas (un solo candidato), es el mismo."""
    frecuentes = {c: g for c, g in juntos.items() if g["prio"] == 0 and len(g["pos"]) >= 3 and not g.get("sep")}
    if not frecuentes:
        return
    fon: dict = {}
    ini: dict = {}
    for c, g in frecuentes.items():
        ws = _canon(g["nombre"]).split()
        kb = _KF.compactar(ws)
        if len(kb) >= 6:
            fon.setdefault(_fonetica(kb), []).append(c)
        for i in _iniciales(ws):
            ini.setdefault(i, []).append(c)
    for c, g in list(juntos.items()):
        if g["prio"] != 0 or len(g["pos"]) > 2 or g.get("sep") or c in frecuentes or V._union_manual(g["nombre"], ()):
            continue
        ws = _canon(g["nombre"]).split()
        kb = _KF.compactar(ws)
        destino = None
        if len(kb) >= 6 and not all(_comun_exacta(w) for w in ws):
            cand = fon.get(_fonetica(kb)) or []
            if len(cand) == 1:
                destino = cand[0]
        if destino is None and len(ws) == 1 and any(_es_sigla(d) for d in _dichos(g)) and sigla_valida(kb, _comun_exacta):
            cand = ini.get(kb) or []
            if len(cand) == 1:
                destino = cand[0]
        if destino is not None and destino != c and destino in juntos:
            _unir_en(juntos, destino, g)
            del juntos[c]


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


_V_CACHE: list = [None, None]      # (firma, Variantes): ⚡ se rehace solo si cambian los conocidos o el glosario


def _variantes(tabla: dict, glossary) -> Variantes:
    """El agrupador de variantes con los nombres conocidos (la tabla) y lo que decidiste («Unir con…» / «Separar…»)."""
    unir = dict((glossary or {}).get("unir") or {})
    separar = tuple((glossary or {}).get("separar") or ())
    conocidos: dict = {}
    for nombre, prio in tabla.values():
        if prio > conocidos.get(nombre, -1):
            conocidos[nombre] = prio
    firma = (tuple(sorted(conocidos.items())), tuple(sorted(unir.items())), separar)
    if _V_CACHE[0] != firma:
        _V_CACHE[0], _V_CACHE[1] = firma, Variantes(conocidos, _comun_exacta, unir, separar, singular=_singular_de)
    return _V_CACHE[1]


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
    alt = _ampliar(tabla, list(si or ()) + list(extra_terms or ()))   # (spiderman, witcher, zombie…)
    largo_max = _largos(tabla)          # (por primera palabra: ver _largos)
    primeras = set(largo_max)
    acronimos = {k[0]: v for k, v in tabla.items() if len(k) == 1 and 2 <= len(k[0]) <= MAX_DELETREO
                 and k[0].isalpha()}
    # el nombre que se ve: el de tu carpeta si existe; si no, el del glosario (canónico → nombre)
    V = _variantes(tabla, glossary if usar_glos else None)
    separar = V.separar
    preferido: dict = {}
    for nombre in list(si or ()) + list(extra_terms or ()):           # (las carpetas, las últimas: mandan)
        nombre = " ".join(str(nombre or "").split())
        if nombre and nombre != "Sin nombre":
            preferido[V.clave(nombre)] = nombre
    no_c = {_KF.compacta(x) for x in no} - {""}
    if no_c and preferido:     # «no» a «Los Ángeles» no borra tu carpeta «Ángeles» (solo coincide sin el artículo)
        no_j = {_KF.junta(x) for x in no}
        no_c -= {_KF.compacta(nm) for nm in preferido.values() if _KF.junta(nm) not in no_j}
    si_reps = {V.clave(x).partition("|")[0] for x in (si or ())}
    partes: list = []
    for media_id, tr in (getattr(project, "transcripts", None) or {}).items():
        toks = _tokens((tr or {}).get("words"), primeras)
        if not toks:
            continue
        n = len(toks)
        grupos: dict = {}
        ultimo = None             # (grupo, posición) de la mención anterior: para el tartamudeo
        p = 0
        while p < n:
            hit = None
            for largo in largo_max.get(toks[p].nkey, ()):             # primero la frase más larga
                if p + largo > n:
                    continue
                clave = tuple(t.nkey for t in toks[p:p + largo])
                if clave in tabla:
                    nombre, prio = tabla[clave]
                    hit = (clave, largo, nombre, prio)
                    break
            if hit is None and alt:                                     # «spiderman», «witcher», «zombie»…
                v = alt.get(toks[p].key)
                if v is not None:
                    hit = (_kn(v[0]), 1, v[0], v[1])
            if hit is None and toks[p].key in LETRAS and acronimos:    # «ge te a» → GTA (si es un nombre conocido)
                letras = []
                q = p
                while q < n and q - p < MAX_DELETREO and toks[q].key in LETRAS and \
                        (q == p or (not toks[q].inicio and toks[q].ini - toks[q - 1].fin <= PAUSA)):
                    letras.append(LETRAS[toks[q].key])
                    q += 1
                for largo in range(len(letras), 1, -1):
                    v = acronimos.get("".join(letras[:largo]))
                    if v is not None:
                        hit = (("".join(letras[:largo]),), largo, v[0], v[1])
                        break
            if hit is None:
                t = toks[p]
                if not (t.cap and t.key not in STOP):
                    p += 1
                    continue
                q = p + 1          # nombre propio: mayúsculas seguidas, sin cruzar un inicio de frase ni una pausa
                while (q < n and q - p < MAX_PROPIO and toks[q].cap and not toks[q].inicio
                       and toks[q].key not in STOP and len(toks[q].key) >= 2
                       and toks[q].ini - toks[q - 1].fin <= PAUSA
                       and toks[q].key != toks[q - 1].key                 # (tartamudeo: «Peor Peor»)
                       and not _nombre_conocido_en(tabla, toks, q, largo_max)):
                    q += 1
                if q - p == 1 and (t.inicio or len(t.key) < 3):
                    p += 1         # mayúscula por ser inicio de frase: no es un nombre
                    continue
                if t.inicio and q - p >= 2 and _es_comun(t.key) and \
                        V.nombre_de(V.clave(" ".join(x.txt for x in toks[p + 1:q]))) is not None:
                    p += 1         # «Jugué Fortnight»: el verbo del principio no es parte del nombre
                    continue
                clave = tuple(x.key for x in toks[p:q])
                hit = (clave, q - p, " ".join(x.txt for x in toks[p:q]), 0)
            clave, largo, nombre, prio = hit
            if prio == 2:          # juego o compañía conocidos: se amplía con su número o subtítulo
                largo, nombre = _extender(toks, p, largo, nombre, clave, tabla, largo_max)
            gk = _kn(nombre)
            dicho = toks[p].txt                       # cómo se dijo («gta cinco»; «gta5» partido se junta otra vez)
            for q in range(p + 1, p + largo):
                dicho += ("" if toks[q].ini == toks[q - 1].ini else " ") + toks[q].txt
            sep = bool(separar) and _clave_dicho(dicho) in separar
            if sep:                                   # «Separar…»: va aparte
                gk = ("§", _clave_dicho(dicho))
            # tartamudeo: «GTA, GTA cinco» / «Fortnite Fortnite» pegados → cuenta una vez (la última, la completa)
            if ultimo is not None:
                gk0, p0, l0 = ultimo
                if p0 + l0 == p and toks[p].ini - toks[p - 1].fin <= TARTAMUDEO and gk[:len(gk0)] == gk0:
                    g0 = grupos.get(gk0)
                    if g0 is not None and (p0, l0) in g0["pos"]:
                        g0["pos"].remove((p0, l0))
                        if not g0["pos"]:
                            del grupos[gk0]
            g = grupos.setdefault(gk, {"nombre": nombre, "prio": prio, "pos": [], "sup": Counter(), "dichos": {}})
            if sep:
                g["sep"] = True
            if prio > g["prio"]:
                g["prio"], g["nombre"] = prio, nombre
            g["pos"].append((p, largo))
            g["sup"][nombre] += 1
            g["dichos"][(p, largo)] = dicho
            ultimo = (gk, p, largo)
            p += largo

        grupos = _quitar_solapes(grupos)
        grupos = _limpiar(grupos, preferido, V, no_c, si_reps)
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
            vistos = {_KF.norm(nombre)}
            variantes = []
            for d, _c in _dichos(g).most_common():        # cómo más se dijo, sin repetir el nombre que se ve
                kd = _KF.norm(d)
                if kd and kd not in vistos:
                    vistos.add(kd)
                    variantes.append(d)
            entrada = {"term": nombre, "media_id": media_id, "hits": hits, "count": len(hits),
                       "mods": mods_total, "known": g["prio"] > 0, "variantes": variantes[:10]}
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
