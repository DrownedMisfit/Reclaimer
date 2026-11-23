"""
🔎 BUSCAR MATERIAL CONFORME A FRASES Y PALABRAS CLAVE (lógica sin Qt; vale para la versión pública y la privada).

De una frase de la narración al material que la ilustra:
  «en GTA 5 hay carros que explotan con unos cuantos disparos»
    → tema «GTA 5» (palabra clave: ai/mentions.py, con sus variantes y tu glosario)
    → acciones: explotar (exploding / explosion), disparar (shooting / gunfire)
    → objetos: carros (car)
    → consultas en inglés y español: «GTA 5 car explosion», «GTA 5 car», «GTA 5 carros explotan», «car explosion»…
    → los resultados se ORDENAN por parecido REAL con CLIP (la miniatura contra lo que dices), no solo por el título.

Versión pública: solo IMÁGENES con licencia libre (ai/web_images.py: Openverse y Wikimedia Commons), con su crédito y
licencia en «<imagen>.creditos.json». La versión privada añade los videos (módulo privado aparte, opcional): esta
lógica NUNCA importa nada privado; `hay_videos()` solo mira si el módulo existe.

  entender(frase, termino=None, extra_terms=(), glossary=None) -> {"tema", "acciones", "objetos", "resto", "frase"}
  consultas(ent, para="imagenes"|"videos", maximo=6) -> ["GTA 5 car explosion", …]
  textos_clip(ent) -> ["a car exploding, in GTA 5", "<la frase>"]   (lo que se compara con las imágenes)
  ordenar_por_clip(candidatos, textos, enc_texto=None, enc_imagen=None) -> candidatos con «parecido», ordenados
  momentos(project, menciones, separacion=8.0, maximo=30, incluir_frases=True) -> [{"tl", "frase", "termino", …}]
  buscar_para_frase(frase, termino, fuentes, n=6, …) -> los mejores candidatos (miniatura local + parecido)
  plan_automatico(momentos, fuentes, …) -> lo elegido para cada momento (sin repetir), ya descargado
  colocar_imagenes(ctrl, elegidos) -> resumen (UN solo Ctrl+Z para todo; estilo «Encima, fondo desenfocado y sombra»)
  quitar(ctrl, entrada) · cambiar(ctrl, entrada, ruta_nueva, item_nuevo)

Las búsquedas y descargas se inyectan con `Fuentes` (en las pruebas, material local fabricado: sin internet).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .base import check_cancel

# ---------------------------------------------------------------- diccionarios (español → inglés)
# Acciones comunes: (patrón sobre la palabra sin tildes ni mayúsculas, gerundio en inglés, sustantivo en inglés).
# Patrones con formas concretas para no confundir palabras corrientes («nada» no es nadar, «correo» no es correr).
ACCIONES = [
    (r"^(explot|explosi|revent|revient|estall)", "exploding", "explosion"),
    (r"^(dispar|tirote|balace|balea)", "shooting", "gunfire"),
    (r"^(conduc|conduj|manej)", "driving", "driving"),
    (r"^(corre|corren|correr|corriendo|corrio|corrian|corria)$", "running", "running"),
    (r"^(vuela|vuelan|vuelo|volar|volando|volaba|volaban|volo|pilot)", "flying", "flight"),
    (r"^(salta|saltan|saltar|saltando|salto|saltaba|saltaban)$", "jumping", "jump"),
    (r"^(pelea|pelean|pelear|peleando|peleo|peleaba|lucha|luchan|luchar|luchando|combat)", "fighting", "fight"),
    (r"^(mata|matan|matar|matando|mato|mataba|mataban|asesin)", "killing", "kill"),
    (r"^(muere|mueren|morir|muriendo|murio|murieron|muerto|muertos)$", "dying", "death"),
    (r"^(choc|choqu)", "crashing", "crash"),
    (r"^(destru|derrib)", "destroying", "destruction"),
    (r"^(persig|persegu|persecuc)", "chasing", "chase"),
    (r"^(escala|escalan|escalar|escalando|trepa|trepan|trepar|trepando)$", "climbing", "climbing"),
    (r"^(nadan|nadar|nadando|nado|nadaba)$", "swimming", "swimming"),
    (r"^(constru)", "building", "construction"),
    (r"^(roba|roban|robar|robando|robo|robaron|atrac|asalt)", "robbing", "heist"),
    (r"^(escond|sigil)", "hiding", "stealth"),
    (r"^(quema|queman|quemar|quemando|arde|arden|ardiendo|incendi)", "burning", "fire"),
    (r"^(cae|caen|caer|cayendo|cayo|cayeron)$", "falling", "fall"),
    (r"^(ataca|atacan|atacar|atacando|ataco|ataque|ataques)$", "attacking", "attack"),
    (r"^(explora|exploran|explorar|explorando|exploracion)$", "exploring", "exploration"),
    (r"^(baila|bailan|bailar|bailando|baile)$", "dancing", "dance"),
    (r"^(derrap)", "drifting", "drift"),
    (r"^(carrera|carreras|compite|compiten|competir)$", "racing", "race"),
    (r"^(recarg)", "reloading", "reload"),
    (r"^(apunta|apuntan|apuntar|apuntando)$", "aiming", "aim"),
    (r"^(huye|huyen|huir|huyendo|huyo|escapa|escapan|escapar|escapando)$", "escaping", "escape"),
    (r"^(hacke|hackea)", "hacking", "hacking"),
    (r"^(caza|cazan|cazar|cazando)$", "hunting", "hunt"),
    (r"^(navega|navegan|navegar|navegando)$", "sailing", "sailing"),
    (r"^(cocina|cocinan|cocinar|cocinando)$", "cooking", "cooking"),
]
_ACC_RE = [(re.compile(p), g, s) for p, g, s in ACCIONES]

# Objetos y lugares comunes (singular sin tildes → inglés). Los plurales se reconocen solos («carros» → carro).
OBJETOS = {
    "carro": "car", "coche": "car", "auto": "car", "automovil": "car", "camion": "truck", "camioneta": "pickup truck",
    "moto": "motorcycle", "motocicleta": "motorcycle", "bici": "bicycle", "bicicleta": "bicycle", "avion": "airplane",
    "avioneta": "small plane", "helicoptero": "helicopter", "barco": "ship", "lancha": "speedboat", "tanque": "tank",
    "tren": "train", "nave": "spaceship", "cohete": "rocket", "arma": "weapon", "pistola": "pistol", "rifle": "rifle",
    "escopeta": "shotgun", "francotirador": "sniper", "espada": "sword", "escudo": "shield", "arco": "bow",
    "granada": "grenade", "bomba": "bomb", "policia": "police", "patrulla": "police car", "soldado": "soldier",
    "zombi": "zombie", "zombie": "zombie", "dragon": "dragon", "monstruo": "monster", "jefe": "boss",
    "enemigo": "enemy", "personaje": "character", "robot": "robot", "alien": "alien", "extraterrestre": "alien",
    "perro": "dog", "gato": "cat", "caballo": "horse", "lobo": "wolf", "oso": "bear", "tiburon": "shark",
    "ciudad": "city", "calle": "street", "carretera": "highway", "autopista": "highway", "edificio": "building",
    "rascacielos": "skyscraper", "casa": "house", "castillo": "castle", "bosque": "forest", "selva": "jungle",
    "desierto": "desert", "montana": "mountain", "playa": "beach", "mar": "sea", "oceano": "ocean", "rio": "river",
    "lago": "lake", "isla": "island", "cueva": "cave", "nieve": "snow", "lluvia": "rain", "tormenta": "storm",
    "cielo": "sky", "noche": "night", "puente": "bridge", "fuego": "fire", "llamas": "flames", "humo": "smoke",
    "explosion": "explosion", "mapa": "map", "tienda": "shop", "banco": "bank", "carcel": "prison",
    "mazmorra": "dungeon", "mansion": "mansion", "hospital": "hospital", "escuela": "school", "estadio": "stadium",
    "pelota": "ball", "balon": "ball", "gasolinera": "gas station", "aeropuerto": "airport", "puerto": "harbor",
    "granja": "farm", "armadura": "armor", "casco": "helmet", "cofre": "treasure chest", "tesoro": "treasure",
    "moneda": "coin", "puerta": "door", "pueblo": "village", "ruinas": "ruins", "templo": "temple",
    "volcan": "volcano", "fantasma": "ghost", "vampiro": "vampire", "bruja": "witch", "mago": "wizard",
    "caballero": "knight", "pirata": "pirate", "ninja": "ninja", "vaquero": "cowboy", "gangster": "gangster",
}

# Palabras que nunca son ni acción ni objeto (cuantificadores, conectores…)
_VACIAS = set("""
a al algo algun alguna algunas alguno algunos ante aqui asi aun bien cada como con contra cual cuando cuantas cuantos
de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso esos esta estaba estan estas este esto
estos fue fueron ha han hasta hay la las le les lo los mas me mi mientras muy mucho muchos muchas nada ni no nos o
otra otras otro otros para pero poco pocos por porque que quien se sea ser si sin sobre son su sus tambien tan tanto
te tiene tienen todo todos todas tu un una unas uno unos y ya yo luego entonces pues super bastante solo vez veces cosa cosas
""".split())


# Verbos auxiliares y corrientes y palabras de relleno que no dicen nada de lo que se ve («hizo», «anunció», «nuevo»)
_SIN_CONTENIDO = set("""
hizo hace hacen hacer haciendo hecho hicieron anuncio anuncia anuncian anunciaron dijo dice dicen decir salio sale
salen salieron tiene tenia tenemos tuvo tener es son fue fueron era eran sera seria estar esta estan estaba estuvo
puede pueden podria pudo quiere quieren queria va van vamos iba ir viene vienen vino ver vi vimos mira miren creo
parece parecia siento pienso nuevo nueva nuevos nuevas viejo vieja gente juego juegos videojuego videojuegos ano anos
dia dias hoy ayer manana ahora antes despues siempre nunca tambien todavia aun casi realmente literalmente verdad
gran grande mejor peor mismo misma mismos otra otro algo nada todo cualquier tipo parte veces cosa cosas forma
manera momento tiempo lado caso hecho igual tanto tan mas menos muy bien mal sido haber hay habia hubo
""".split())


def _con_contenido(w: str) -> bool:
    """¿Es un sustantivo o adjetivo con contenido? (fuera vacías, auxiliares y formas que casi siempre son verbo:
    «anunció», «jugando», «salieron»)."""
    k = _sin_tildes(w)
    if len(k) < 3 or w.isdigit() or k in _VACIAS or k in _SIN_CONTENIDO:
        return False
    gerundio = len(k) >= 7 and k.endswith(("ando", "iendo"))     # («mando» o «bando» no son gerundios)
    if w.lower().endswith("ó") or k.endswith(("aron", "ieron", "aban")) or gerundio:
        return False
    return True


def _sin_tildes(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _palabras(frase: str) -> list[str]:
    """Palabras de la frase tal cual (sin signos), en orden."""
    return [w for w in re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’]+", frase or "") if w]


def _singular(w: str) -> list[str]:
    """La palabra y sus posibles singulares («carros» → carro, «camiones» → camion, «ciudades» → ciudad)."""
    out = [w]
    if w.endswith("es") and len(w) > 4:
        out.append(w[:-2])
    if w.endswith("s") and len(w) > 3:
        out.append(w[:-1])
    return out


def accion_de(palabra: str) -> tuple[str, str] | None:
    """(gerundio, sustantivo) en inglés de una palabra española que es una acción común, o None."""
    k = _sin_tildes(palabra)
    if len(k) < 3 or k in _VACIAS:
        return None
    for rx, g, s in _ACC_RE:
        if rx.search(k):
            return g, s
    return None


def objeto_de(palabra: str) -> str | None:
    """El inglés de un objeto o lugar común («carros» → car), o None."""
    k = _sin_tildes(palabra)
    if len(k) < 2 or k in _VACIAS:
        return None
    for s in _singular(k):
        if s in OBJETOS:
            return OBJETOS[s]
    return None


# ---------------------------------------------------------------- entender la frase
def _tema_de(frase: str, extra_terms=(), glossary=None) -> str | None:
    """La palabra clave de la frase con la MISMA detección que «Dijiste…» (ai/mentions.py: variantes, glosario…)."""
    from types import SimpleNamespace

    from . import mentions
    ws = _palabras(frase)
    if not ws:
        return None
    words = [[i * 0.3, i * 0.3 + 0.25, w] for i, w in enumerate(ws)]
    falso = SimpleNamespace(transcripts={"frase": {"words": words}}, clips={}, compounds={}, media={}, tracks=[])
    try:
        ms = mentions.find_mentions(falso, extra_terms=list(extra_terms or ()), glossary=glossary)
    except Exception:  # noqa: BLE001 - sin tema, la búsqueda sigue con acciones y objetos
        return None
    return ms[0]["term"] if ms else None


def _quitar_tema(ws: list[str], tema: str | None) -> list[str]:
    """Las palabras de la frase sin las del tema («GTA 5» dicho «GTA cinco» también se quita)."""
    if not tema:
        return list(ws)
    from ..core import keyword_folders as KF
    objetivo = KF.canon(tema)
    objetivo_c = KF.compacta(tema)
    for largo in range(min(8, len(ws)), 0, -1):
        for i in range(0, len(ws) - largo + 1):
            trozo = " ".join(ws[i:i + largo])
            if KF.canon(trozo) == objetivo or (objetivo_c and KF.compacta(trozo) == objetivo_c):
                return ws[:i] + ws[i + largo:]
    return list(ws)


def entender(frase: str, termino: str | None = None, extra_terms=(), glossary=None, buscar_tema: bool = True) -> dict:
    """Tema (palabra clave) + acciones + objetos de una frase. termino = la palabra clave ya detectada (la de
    «Dijiste…»); si no se da, se busca en la frase con la detección de siempre (salvo buscar_tema=False)."""
    tema = (termino or "").strip() or (_tema_de(frase, extra_terms, glossary) if buscar_tema else None)
    ws = _quitar_tema(_palabras(frase), tema)
    acciones, objetos, resto = [], [], []
    vistos_a, vistos_o = set(), set()
    for w in ws:
        o = objeto_de(w)
        a = None if o else accion_de(w)
        if o:
            if o not in vistos_o:
                vistos_o.add(o)
                objetos.append({"es": w, "en": o})
        elif a:
            if a[0] not in vistos_a:
                vistos_a.add(a[0])
                acciones.append({"es": w, "en": a[0], "en_s": a[1]})
        elif _con_contenido(w):
            resto.append(w)
    return {"frase": frase, "tema": tema or None, "acciones": acciones, "objetos": objetos, "resto": resto}


def _unir(*partes) -> str:
    return " ".join(" ".join(str(p) for p in partes if p).split())


def consultas(ent: dict, para: str = "imagenes", maximo: int = 6) -> list[str]:
    """Varias búsquedas en inglés y español, de la más concreta a la más general. Para imágenes libres se añade una
    general sin el tema («car explosion»: las fotos libres casi nunca son del juego)."""
    tema = ent.get("tema") or ""
    obj = ent.get("objetos") or []
    acc = ent.get("acciones") or []
    o_en = obj[0]["en"] if obj else ""
    o_es = obj[0]["es"] if obj else ""
    a_s = acc[0]["en_s"] if acc else ""
    a_es = acc[0]["es"] if acc else ""
    out = [
        _unir(tema, o_en, a_s),                    # GTA 5 car explosion
        _unir(tema, o_es, a_es),                   # GTA 5 carros explotan
        _unir(tema, o_en) if (o_en and a_s) else "",   # GTA 5 car
        _unir(tema, a_s) if (o_en and a_s) else "",    # GTA 5 explosion
    ]
    if len(acc) > 1 and tema:
        out.append(_unir(tema, o_en, acc[1]["en_s"]))  # GTA 5 car gunfire
    if para == "imagenes" and tema and o_en and a_s:
        out.append(_unir(o_en, a_s))               # car explosion
    if not tema and len(obj) > 1 and a_s:
        out.insert(0, _unir(o_en, obj[1]["en"], a_s))   # dragon village fire
    resto = ent.get("resto") or []
    if tema and not obj and not acc and resto:     # frases de opinión: el tema y 1–2 palabras de lo que dices
        out.append(_unir(tema, *resto[:2]))
    if tema:
        out.append(tema)
    if not tema and not obj and not acc:           # nada reconocido: las palabras con contenido de la frase
        out.append(_unir(*resto[:5]))
    vistos, res = set(), []
    for q in out:
        k = q.lower()
        if not q or k in vistos:
            continue
        if not tema and len(q.split()) < 2:        # sin tema, una sola palabra («zombie») trae de todo
            continue
        vistos.add(k)
        res.append(q)
    return res[:maximo]


# Empresas, estudios, tiendas y consolas (salen en «Dijiste…» como conocidos, pero NO son juegos)
EMPRESAS = [
    "Steam", "Steam Deck", "PlayStation", "Xbox", "Nintendo", "Nintendo Switch", "Sony", "Microsoft", "Epic Games",
    "Epic", "Ubisoft", "Electronic Arts", "EA", "Bethesda", "Bandai Namco", "Capcom", "Rockstar", "Rockstar Games",
    "Activision", "Blizzard", "Riot Games", "Riot", "Valve", "Mojang", "Konami", "Sega", "Square Enix", "Take-Two",
    "Naughty Dog", "FromSoftware", "Supercell", "HoYoverse", "Krafton", "Respawn", "Remedy", "Bungie",
    "CD Projekt", "CD Projekt Red", "Insomniac", "343 Industries", "Santa Monica Studio", "Guerrilla", "Sucker Punch",
    "Treyarch", "Infinity Ward", "Raven", "DICE", "BioWare", "id Software", "Arkane", "MachineGames", "Obsidian",
    "inXile", "Double Fine", "Playground Games", "Turn 10", "The Coalition", "Rare", "Ninja Theory", "Kojima Productions",
    "Larian", "Larian Studios", "Tencent", "NetEase", "Embracer", "Devolver Digital", "Annapurna Interactive",
    "Warner Bros", "Warner Bros Games", "Twitch", "YouTube", "Google", "Apple", "Meta", "Amazon", "Netflix", "Discord",
    "Game Pass", "PlayStation Plus", "Nvidia", "AMD", "Intel", "Valve Index", "Meta Quest",
]


def es_empresa(tema: str | None) -> bool:
    """¿Es una empresa, un estudio, una tienda o una consola? Solo el nombre EXACTO (o con un número detrás:
    «PlayStation 6», «Nintendo Switch 2»): «EA Sports FC 25» o «Microsoft Flight Simulator» no son empresas."""
    if not tema:
        return False
    from ..core import keyword_folders as KF
    c = KF.canon(tema)
    for x in EMPRESAS:
        k = KF.canon(x)
        if c == k or (c.startswith(k + " ") and c[len(k) + 1:].isdigit()):
            return True
    return False


def es_juego(tema: str | None) -> bool:
    """¿El tema es un juego (o saga)? Lista de conocidos de «Dijiste…», tu glosario y lo consultado en internet."""
    if not tema:
        return False
    from . import keyword_glossary as KG
    from . import mentions
    from ..core import keyword_folders as KF
    try:
        g = KG.load()
        tipo = (((g.get("si") or {}).get(KG.clave(tema)) or {}).get("tipo") or (KG.web_get(tema, g) or {}).get("tipo") or "")
    except Exception:  # noqa: BLE001
        tipo = ""
    if tipo:
        return tipo in ("juego", "saga")
    c = KF.canon(tema)
    juegos = [x for x in mentions.CONOCIDOS if not es_empresa(x)]
    if any(KF.canon(x) == c for x in juegos):  # (un juego conocido tal cual gana)
        return True
    if es_empresa(tema):                       # (Nintendo, Epic Games, Xbox…: conocidos, pero no son juegos)
        return False
    return any(KF.canon(x) == c or c.startswith(KF.canon(x) + " ") for x in mentions.CONOCIDOS)


def textos_clip(ent: dict) -> list[str]:
    """Lo que se compara con cada imagen: una descripción en inglés («car explosion, in the video game GTA 5»; sin
    «video game» si el tema no es un juego) y la frase tal cual (el CLIP de Reclaimer es multilingüe)."""
    obj = ent.get("objetos") or []
    acc = ent.get("acciones") or []
    tema = ent.get("tema") or ""
    nombres = [o["en"] for o in obj[:2]]          # «dragón quema el pueblo» → dragon fire village
    if nombres and acc:
        desc = " ".join([nombres[0], acc[0]["en_s"]] + nombres[1:])
    elif nombres:
        desc = " and ".join(nombres)
    elif acc:
        desc = acc[0]["en_s"]
    else:
        desc = ""
    if tema and es_juego(tema):
        desc = f"{desc}, in the video game {tema}" if desc else f"a screenshot of the video game {tema}"
    elif tema:
        desc = f"{desc}, {tema}" if desc else f"a photo of {tema}"
    out = [t for t in (desc, ent.get("frase") or "") if t.strip()]
    return out or [tema or "image"]


# ---------------------------------------------------------------- ranking con CLIP
def leer_imagen_224(ruta: str) -> np.ndarray | None:
    """La imagen recortada al centro a 224×224 RGB (como media.sample_frames), sin FFmpeg (rápido para miniaturas)."""
    try:
        import cv2
        img = cv2.imdecode(np.fromfile(ruta, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    k = 224.0 / min(h, w)
    nw, nh = max(224, int(round(w * k))), max(224, int(round(h * k)))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    x0, y0 = (nw - 224) // 2, (nh - 224) // 2
    img = img[y0:y0 + 224, x0:x0 + 224]
    return np.ascontiguousarray(img[:, :, ::-1])


def _vector_texto(textos: list[str], enc_texto) -> np.ndarray:
    v = enc_texto.encode(list(textos)).mean(axis=0)
    return (v / max(1e-9, float(np.linalg.norm(v)))).astype(np.float32)


def _encoders(enc_texto, enc_imagen):
    if enc_texto is None or enc_imagen is None:
        from . import embeddings
        enc_texto = enc_texto or embeddings.get("clip_text")
        enc_imagen = enc_imagen or embeddings.get("clip_image")
    return enc_texto, enc_imagen


def _coincide_titulo(item: dict, ent: dict | None) -> float:
    """Un empujoncito (nunca manda) si el título nombra el tema o el objeto."""
    if not ent:
        return 0.0
    titulo = _sin_tildes(item.get("title") or "")
    claves = [ent.get("tema") or ""] + [o["en"] for o in ent.get("objetos") or []]
    return 1.0 if any(c and _sin_tildes(c) in titulo for c in claves) else 0.0


def ordenar_por_clip(candidatos: list[dict], textos: list[str], enc_texto=None, enc_imagen=None,
                     ent: dict | None = None) -> list[dict]:
    """Ordena por parecido REAL: CLIP de la miniatura local («thumb_local») contra lo que dices. Cada candidato
    recibe «parecido» (coseno CLIP) y «vec» (su huella, para no repetir). Sin miniatura legible, se queda fuera."""
    enc_texto, enc_imagen = _encoders(enc_texto, enc_imagen)
    q = _vector_texto(textos, enc_texto)
    buenos, imgs = [], []
    for c in candidatos:
        img = leer_imagen_224(c.get("thumb_local") or "")
        if img is not None:
            buenos.append(c)
            imgs.append(img)
    if not buenos:
        return []
    vecs = enc_imagen.encode(np.stack(imgs))
    for c, v in zip(buenos, vecs):
        c["vec"] = np.asarray(v, np.float32)
        c["parecido"] = round(float(v @ q), 4)
        c["puntos"] = c["parecido"] + 0.02 * _coincide_titulo(c, ent)
    buenos.sort(key=lambda c: -c["puntos"])
    return buenos


# ---------------------------------------------------------------- las frases de la narración
FIN_FRASE = ".?!…;"
PAUSA_FRASE = 0.7       # s: una pausa más larga corta la frase
MAX_LADO = 14           # palabras a cada lado como mucho


def frase_en(words: list, src: float) -> tuple[str, float, float] | None:
    """La frase que se dice en el segundo src del archivo: (texto, inicio, fin) en segundos del archivo. Corta en el
    punto (o ? ! …) y en las pausas largas."""
    if not words:
        return None
    j = 0
    for i, w in enumerate(words):
        if float(w[0]) <= src + 1e-6:
            j = i
        else:
            break
    a = j
    while a > 0 and j - a < MAX_LADO:
        prev = words[a - 1]
        if str(prev[2]).rstrip().endswith(tuple(FIN_FRASE)) or float(words[a][0]) - float(prev[1]) > PAUSA_FRASE:
            break
        a -= 1
    b = j
    while b < len(words) - 1 and b - j < MAX_LADO:
        if str(words[b][2]).rstrip().endswith(tuple(FIN_FRASE)) or float(words[b + 1][0]) - float(words[b][1]) > \
                PAUSA_FRASE:
            break
        b += 1
    texto = " ".join(str(w[2]).strip() for w in words[a:b + 1]).strip()
    return texto, float(words[a][0]), float(words[b][1])


def momentos(project, menciones: list[dict], separacion: float = 8.0, maximo: int = 30,
             incluir_frases: bool = True) -> list[dict]:
    """Los momentos donde poner material, en orden: cada vez que dices una palabra clave (con su frase) y, con
    incluir_frases, las frases sin palabra clave que nombran un objeto Y una acción («los carros explotan»).
    Una sola vez por frase, al menos `separacion` s entre uno y otro (las imágenes, pocas) y como mucho `maximo`.
    [{"tl", "frase", "termino", "media_id", "src", "fin"}] (tl = segundo de la línea de tiempo)."""
    from ..core.mapping import DeepIndex
    cand: list[dict] = []
    vistos: set = set()
    trans = getattr(project, "transcripts", None) or {}
    for prio, m in enumerate(menciones or []):
        words = (trans.get(m.get("media_id")) or {}).get("words") or []
        for h in m.get("hits") or []:
            if h.get("tl") is None:
                continue
            fr = frase_en(words, float(h.get("src", 0.0))) if words else None
            texto = fr[0] if fr else (h.get("context") or m.get("term") or "")
            clave = (m.get("media_id"), round(fr[1], 2) if fr else round(float(h["tl"]), 1))
            if clave in vistos:
                continue
            vistos.add(clave)
            cand.append({"tl": float(h["tl"]), "frase": texto, "termino": m.get("term"), "media_id": m.get("media_id"),
                         "src": float(h.get("src", 0.0)), "prio": prio})
    if incluir_frases:
        for mid, tr in trans.items():
            words = (tr or {}).get("words") or []
            if not words:
                continue
            ix = DeepIndex(project, mid)
            i = 0
            while i < len(words):
                fr = frase_en(words, float(words[i][0]))
                if fr is None:
                    break
                texto, a, b = fr
                fin = next((k for k in range(i, len(words)) if float(words[k][0]) > b + 1e-6), len(words))
                i = max(i + 1, fin)
                if (mid, round(a, 2)) in vistos:
                    continue
                ent = entender(texto, buscar_tema=False)    # (sin tema: solo objeto + acción)
                if not (ent["objetos"] and ent["acciones"]):
                    continue
                tl = ix.time(a)
                if tl is None:
                    continue
                vistos.add((mid, round(a, 2)))
                cand.append({"tl": float(tl), "frase": texto, "termino": None, "media_id": mid, "src": a,
                             "prio": 10_000})
    cand.sort(key=lambda c: c["tl"])
    out: list[dict] = []
    for c in cand:                     # la separación mínima: si chocan, gana la palabra clave más dicha
        if out and c["tl"] - out[-1]["tl"] < separacion:
            if c["prio"] < out[-1]["prio"]:
                out[-1] = c
            continue
        out.append(c)
    if len(out) > maximo:              # demasiados: los de las palabras más importantes, repartidos en el tiempo
        out = sorted(sorted(out, key=lambda c: (c["prio"], c["tl"]))[:maximo], key=lambda c: c["tl"])
    for c in out:
        c.pop("prio", None)
    return out


# ---------------------------------------------------------------- fuentes (internet o, en las pruebas, local)
class Fuentes:
    """Dónde se busca y cómo se baja. Por defecto, la versión pública: imágenes libres de Openverse y Wikimedia
    Commons (ai/web_images.py). Las pruebas pasan sus propias funciones (sin internet)."""

    PAUSA = 0.4                 # s entre peticiones a la misma web (no cargarla ni que nos limite)

    def __init__(self):
        self._cache: dict[str, list[dict]] = {}
        self.fallos: list[str] = []          # (lo que no respondió o limitó: el panel lo avisa)
        self._ultima = 0.0

    def _esperar(self):
        import time
        falta = self.PAUSA - (time.monotonic() - self._ultima)
        if falta > 0:
            time.sleep(falta)
        self._ultima = time.monotonic()

    def buscar_imagenes(self, qs: list[str], cancelled=None) -> list[dict]:
        """Cada consulta UNA vez por pasada (la del tema solo, que se repite en cada frase, sale de la caché):
        Wikimedia Commons en las dos primeras y Openverse en todas."""
        from . import web_images
        out = []
        for i, q in enumerate(qs):
            if cancelled and cancelled():
                break
            if q not in self._cache:
                res = []
                for fuente, fn in (("Wikimedia Commons", web_images.search_commons if i < 2 else None),
                                   ("Openverse", web_images.search)):
                    if fn is None:
                        continue
                    self._esperar()
                    try:
                        res += fn(q)
                    except Exception as exc:  # noqa: BLE001 - sin conexión o la web limita: se avisa
                        self.fallos.append(f"{fuente}: {exc}")
                for r in res:
                    r["query"] = q
                self._cache[q] = res
            out += [dict(r) for r in self._cache[q]]
        return out

    def bajar_miniatura(self, item: dict, destino: str) -> str:
        from . import web_images
        return web_images.fetch(item.get("thumbnail") or item["url"], destino, timeout=15, limit=8_000_000)

    def bajar_imagen(self, item: dict, nombre: str | None) -> str:
        from . import web_images
        return web_images.download(item, name=nombre)


def licencia_ok(item: dict) -> bool:
    """Solo licencias que dejan vender y editar: nada sin licencia, ni NC (no comercial) ni ND (sin cambios). Los
    videos (versión privada) no pasan por aquí."""
    if item.get("tipo") == "video":
        return True
    lic = " ".join(str(item.get(k) or "") for k in ("license", "license_text")).lower().strip()
    if not lic:
        return False
    partes = set(re.split(r"[\s_\-/.]+", lic))
    return not ({"nc", "nd"} & partes) and "noncommercial" not in lic.replace("-", "") and \
        "noderiv" not in lic.replace("-", "")


def _carpeta_miniaturas() -> str:
    from ..core.paths import cache_dir
    return str(cache_dir("material_frases"))


def _clave_item(item: dict) -> str:
    return str(item.get("id") or item.get("url") or item.get("thumbnail") or "")


def _ruta_miniatura(item: dict) -> str:
    k = re.sub(r"[^A-Za-z0-9_-]", "", _clave_item(item))[-60:] or str(abs(hash(_clave_item(item))))
    return os.path.join(_carpeta_miniaturas(), f"m_{k}.jpg")


def _bajar_miniaturas(items: list[dict], fuentes: Fuentes, cancelled=None) -> list[dict]:
    """Miniatura local de cada candidato (las que ya estén en la caché no se vuelven a bajar). 4 a la vez."""
    def una(it):
        if cancelled and cancelled():
            return None
        if it.get("thumb_local") and os.path.isfile(it["thumb_local"]):
            return it
        dest = _ruta_miniatura(it)
        try:
            if not (os.path.isfile(dest) and os.path.getsize(dest) > 0):
                fuentes.bajar_miniatura(it, dest)
            it["thumb_local"] = dest
            return it
        except Exception:  # noqa: BLE001 - una miniatura que falla no para las demás
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        res = list(pool.map(una, items))
    return [r for r in res if r is not None]


def buscar_para_frase(frase: str, termino: str | None, fuentes: Fuentes | None = None, n: int = 6,
                      cancelled=None, enc_texto=None, enc_imagen=None, extra_terms=(), glossary=None,
                      por_consulta: int = 12, ent: dict | None = None) -> list[dict]:
    """Los n mejores candidatos para UNA frase (búsqueda manual de «Dijiste…» y paso de plan_automatico).
    Varias consultas → miniaturas → CLIP. Cada candidato: el item de la fuente + «thumb_local», «parecido», «vec»,
    «query»."""
    fuentes = fuentes or Fuentes()
    ent = ent or entender(frase, termino, extra_terms, glossary)
    qs = consultas(ent, "imagenes")
    check_cancel(cancelled)
    items = [it for it in (fuentes.buscar_imagenes(qs, cancelled=cancelled) or []) if licencia_ok(it)]
    check_cancel(cancelled)
    por_q: dict = {}
    vistos: set = set()
    elegidos = []
    for it in items:                        # unos pocos de cada consulta (si no, la primera se lo lleva todo)
        k = _clave_item(it)
        q = it.get("query", "")
        if not k or k in vistos or por_q.get(q, 0) >= por_consulta:
            continue
        vistos.add(k)
        por_q[q] = por_q.get(q, 0) + 1
        elegidos.append(it)
    elegidos = _bajar_miniaturas(elegidos, fuentes, cancelled)
    check_cancel(cancelled)
    ranked = ordenar_por_clip(elegidos, textos_clip(ent), enc_texto, enc_imagen, ent)
    # (22/11) el MISMO orden que Descargas y Buscar material (ai/buscador.puntuar), con el acento en lo que se ve:
    # sobre todo CLIP; lo que nombra el título ayuda un poco y las copias casi iguales bajan
    from . import buscador as B
    B.puntuar(ranked, B.entender(frase, termino, extra_terms, glossary, base=ent), prefs={}, modo="imagenes")
    for c in ranked:
        c["entendido"] = {k: v for k, v in ent.items() if k != "frase"}
    return ranked[:max(1, n)] if n else ranked


# ---------------------------------------------------------------- sin repetir
PARECIDO_REPETIDA = 0.92      # dos imágenes con huellas CLIP así de parecidas son «la misma escena»
PARECIDO_MINIMO = 0.17        # por debajo, la imagen no tiene que ver con la frase: mejor no poner nada


def repetida(vec, usados: list) -> bool:
    if vec is None:
        return False
    return any(float(np.dot(vec, u)) >= PARECIDO_REPETIDA for u in usados)


def huellas_en_proyecto(project) -> list:
    """Huellas CLIP (ya calculadas) de las imágenes que ya están en la línea de tiempo: lo nuevo no las repite."""
    from . import clip_analysis
    out, vistos = [], set()
    for c in getattr(project, "clips", {}).values():
        m = project.media.get(c.media_id) if hasattr(project, "media") else None
        if m is None or getattr(m, "kind", "") != "image" or m.id in vistos:
            continue
        vistos.add(m.id)
        try:
            cached = clip_analysis.load_cached(m.path)
        except Exception:  # noqa: BLE001
            cached = None
        if cached is not None and len(cached[1]):
            out.append(np.asarray(cached[1][0], np.float32))
    return out


def rutas_en_proyecto(project) -> set:
    return {os.path.normcase(os.path.abspath(m.path)) for m in getattr(project, "media", {}).values()
            if any(c.media_id == m.id for c in project.clips.values())}


def claves_en_proyecto(project) -> set:
    """Claves (y enlaces) de las imágenes ya en la línea de tiempo, leídas de sus «.creditos.json»: una segunda pasada
    no las vuelve a poner aunque aún no tengan huella CLIP."""
    out = set()
    for ruta in rutas_en_proyecto(project):
        try:
            with open(os.path.splitext(ruta)[0] + ".creditos.json", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for k in ("clave", "imagen", "url"):
            if isinstance(d, dict) and d.get(k):
                out.add(str(d[k]))
    return out


def _es_nuestro(c) -> bool:
    return (c.note or "").endswith(NOTA)


def momentos_libres(project, momentos_: list[dict]) -> list[dict]:
    """Sin los momentos que ya tienen material puesto por esta función (un clip «🔎 Material por frases» encima)."""
    nuestros = [c for c in project.clips.values() if _es_nuestro(c)]
    return [mo for mo in momentos_
            if not any(c.start - 0.3 <= float(mo["tl"]) < c.end for c in nuestros)]


def momentos_libres_elegidos(project, elegidos: list[dict]) -> list[dict]:
    """Lo elegido cuyo momento sigue libre (si mientras se buscaba pusiste material ahí, no se pisa)."""
    libres = {id(m) for m in momentos_libres(project, [e["momento"] for e in elegidos])}
    return [e for e in elegidos if id(e["momento"]) in libres]


def actualizar_momentos(project, elegidos: list[dict]) -> list[dict]:
    """Justo antes de colocar: el segundo de cada frase otra vez (por si editaste mientras se buscaba). Lo que ya no
    está en la línea de tiempo se quita."""
    from ..core.mapping import DeepIndex
    ix: dict = {}
    out = []
    for e in elegidos:
        mo = e["momento"]
        mid = mo.get("media_id")
        if mid is None or mo.get("src") is None:
            out.append(e)
            continue
        if mid not in ix:
            ix[mid] = DeepIndex(project, mid)
        tl = ix[mid].time(float(mo["src"]))
        if tl is None:
            continue
        out.append(dict(e, momento=dict(mo, tl=float(tl))))
    return out


def guardar_creditos(ruta: str, item: dict, termino: str | None, frase: str = "") -> str:
    """«<imagen>.creditos.json» como el resto de descargas (así sale en «Descargado» y en los créditos), con la
    licencia y el autor."""
    datos = {"title": item.get("title") or "", "channel": item.get("creator") or "",
             "url": item.get("page") or item.get("url") or "", "term": termino or "", "tipo": "imagen",
             "license": item.get("license") or "", "license_text": item.get("license_text") or "",
             "source": item.get("source") or "Openverse", "attribution": item.get("attribution") or "",
             "frase": frase or "", "clave": _clave_item(item), "imagen": item.get("url") or ""}
    dest = os.path.splitext(ruta)[0] + ".creditos.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    return dest


def bajar_elegido(cand: dict, fuentes: Fuentes, termino: str | None, frase: str = "") -> str:
    """Baja la imagen entera de un candidato y deja su crédito al lado. Devuelve la ruta."""
    ruta = fuentes.bajar_imagen(cand, termino or None)
    guardar_creditos(ruta, cand, termino, frase)
    return ruta


def plan_automatico(momentos_: list[dict], fuentes: Fuentes | None = None, progress=None, cancelled=None,
                    enc_texto=None, enc_imagen=None, usados: list | None = None, urls_usadas: set | None = None,
                    alternativas: int = 4, extra_terms=(), glossary=None) -> list[dict]:
    """Busca y baja una imagen para cada momento, SIN repetir (ni la misma imagen ni una casi igual, tampoco las que
    ya están en la línea de tiempo: `usados`). Lo que no encaja con la frase (parecido < PARECIDO_MINIMO) se salta.
    Devuelve [{"momento", "ruta", "item", "alternativas": [candidatos]}] (en segundo plano: sin Qt)."""
    fuentes = fuentes or Fuentes()
    enc_texto, enc_imagen = _encoders(enc_texto, enc_imagen)
    usados = list(usados or [])
    urls = set(urls_usadas or ())
    out = []
    n = max(1, len(momentos_))
    for i, mo in enumerate(momentos_):
        check_cancel(cancelled)
        if progress:
            progress(i / n, f"Buscando material {i + 1}/{n}: «{(mo.get('termino') or mo['frase'])[:40]}»")
        try:
            ranked = buscar_para_frase(mo["frase"], mo.get("termino"), fuentes, n=0, cancelled=cancelled,
                                       enc_texto=enc_texto, enc_imagen=enc_imagen, extra_terms=extra_terms,
                                       glossary=glossary)
        except Exception as exc:  # noqa: BLE001 - una frase que falla (sin conexión…) no para las demás
            from .base import Cancelled
            if isinstance(exc, Cancelled):
                raise
            ranked = []
        libres = [c for c in ranked if _clave_item(c) not in urls and not repetida(c.get("vec"), usados)
                  and c.get("parecido", 0) >= PARECIDO_MINIMO]
        for k, c in enumerate(libres):
            try:
                ruta = bajar_elegido(c, fuentes, mo.get("termino"), mo["frase"])
            except Exception:  # noqa: BLE001 - no se pudo bajar: el siguiente
                continue
            urls.add(_clave_item(c))
            usados.append(c["vec"])
            alts = [x for x in libres[k + 1:] if not repetida(x.get("vec"), [c["vec"]])][:alternativas]
            out.append({"momento": mo, "ruta": ruta, "item": c, "alternativas": alts})
            break
    if progress:
        progress(1.0, f"Material encontrado para {len(out)} de {len(momentos_)} frases")
    return out


# ---------------------------------------------------------------- colocar en la línea de tiempo (hilo de la interfaz)
NOTA = "🔎 Material por frases"
TITULO_DESHACER = "🔎 Material conforme a frases y palabras clave"


def _pista_imagenes(ctrl, t: float, dur: float) -> str | None:
    """La pista de video más alta (encima del B-roll y de la narración). Si está ocupada en ese tramo, una nueva
    encima de todo (dentro del mismo paso de deshacer)."""
    p = ctrl.project
    vt = [tr for tr in p.tracks if tr.kind == "video"]
    if not vt:
        return None
    arriba = next((tr for tr in vt if not tr.locked), None)
    if arriba is None:
        return None
    ocupada = any(c.start < t + dur - 1e-6 and c.end > t + 1e-6 for c in p.clips_on(arriba.id))
    if not ocupada:
        return arriba.id
    if arriba is vt[0]:                 # la más alta está ocupada ahí: una nueva encima de todo
        return ctrl.ensure_video_above(arriba.id) or arriba.id
    return arriba.id                    # (hay pistas bloqueadas encima: add_image_overlay busca la libre más cercana)


def _con_estilo(ctrl, cids: list[str]) -> None:
    """Nunca a pantalla completa: si no había video debajo (add_image_overlay la deja normal), se le pone igualmente
    el estilo «Encima, fondo desenfocado y sombra»."""
    p = ctrl.project
    sin = [cid for cid in cids if cid in p.clips and "ovl" not in (p.clips[cid].fx or {})]
    if sin:
        ctrl.set_image_style(sin, "auto")


def _poner_una(ctrl, ruta: str, tl: float) -> str | None:
    p = ctrl.project
    ids = ctrl.import_now([ruta], quiet=True)
    if not ids:
        return None
    from ..core import overlay
    dur, _ = overlay.auto_duration(p, tl)
    tid = _pista_imagenes(ctrl, tl, dur)
    if tid is None:
        return None
    creados = ctrl.add_image_overlay([ids[0]], tid, tl)
    if not creados:
        return None
    _con_estilo(ctrl, list(creados))
    cid = creados[0]
    ctrl.set_clip_props([cid], "Nota", note=NOTA)      # (para reconocerlas; va dentro del mismo macro)
    return cid


def _colocar_imagenes(ctrl, elegidos: list[dict]) -> list[dict]:
    """(dentro de un macro de deshacer) las imágenes, cada una en el momento de su frase."""
    resumen = []
    for e in sorted(elegidos, key=lambda x: x["momento"]["tl"]):
        tl = float(e["momento"]["tl"])
        try:
            cid = _poner_una(ctrl, e["ruta"], tl)
        except Exception:  # noqa: BLE001 - una imagen que falla no para el resto
            cid = None
        if cid:
            resumen.append({"clip_id": cid, "tl": tl, "frase": e["momento"]["frase"], "tipo": "imagen",
                            "termino": e["momento"].get("termino"), "ruta": e["ruta"], "item": e.get("item"),
                            "alternativas": list(e.get("alternativas") or [])})
    return resumen


def colocar_imagenes(ctrl, elegidos: list[dict]) -> list[dict]:
    """Coloca cada imagen elegida en el momento de su frase, con el estilo del usuario (pequeña, con sombra, sobre el
    video desenfocado; nunca a pantalla completa). TODO en UN solo paso de Ctrl+Z. Devuelve el resumen para revisar:
    [{"clip_id", "tl", "frase", "termino", "ruta", "item", "alternativas"}]."""
    return colocar_todo(ctrl, elegidos, [])


def colocar_todo(ctrl, imagenes: list[dict], videos: list[dict]) -> list[dict]:
    """Imágenes y (versión privada) trozos de video, TODO en UN solo paso de Ctrl+Z. Devuelve el resumen ordenado."""
    if not imagenes and not videos:
        return []
    resumen: list[dict] = []
    ctrl.undo_stack.beginMacro(TITULO_DESHACER)
    try:
        with ctrl.sin_abrir_editor():
            if videos:                       # (primero los videos: las imágenes van encima de ellos)
                mod = _videos()
                if mod is not None:
                    resumen += mod.colocar_videos(ctrl, videos)
            if imagenes:
                resumen += _colocar_imagenes(ctrl, imagenes)
    finally:
        ctrl.undo_stack.endMacro()
    return sorted(resumen, key=lambda e: e["tl"])


def poner_en(ctrl, ruta: str, tl: float, texto: str = "Imagen para esta frase", censura: dict | None = None) -> str | None:
    """Una imagen en el segundo tl (búsqueda manual: «un clic baja y pone en el cabezal»), un Ctrl+Z. Con censura
    (zona_censura de un resultado marcado «Censurar»), se tapa al ponerla, en el mismo paso."""
    ctrl.undo_stack.beginMacro(f"🔎 {texto}")
    try:
        with ctrl.sin_abrir_editor():
            cid = _poner_una(ctrl, ruta, tl)
            if cid and censura:
                aplicar_censura(ctrl, cid, censura)
            return cid
    finally:
        ctrl.undo_stack.endMacro()


def quitar(ctrl, entrada: dict) -> bool:
    """«Quitar» en el resumen: borra ese clip (el archivo sigue en Medios). Un Ctrl+Z."""
    cid = entrada.get("clip_id")
    if not cid or cid not in ctrl.project.clips:
        return False
    ctrl.delete_clips([cid])           # (el id se queda: si deshaces, el resumen lo vuelve a ver)
    return cid not in ctrl.project.clips


def cambiar(ctrl, entrada: dict, ruta_nueva: str, item_nuevo: dict | None = None) -> str | None:
    """«Cambiar» en el resumen: la imagen de ese momento por otra (la siguiente alternativa). Un Ctrl+Z."""
    ctrl.undo_stack.beginMacro("🔎 Cambiar la imagen de esta frase")
    try:
        with ctrl.sin_abrir_editor():
            cid = entrada.get("clip_id")
            if cid and cid in ctrl.project.clips:
                ctrl.delete_clips([cid])
            nuevo = _poner_una(ctrl, ruta_nueva, float(entrada["tl"]))
    finally:
        ctrl.undo_stack.endMacro()
    if nuevo:
        entrada["clip_id"] = nuevo
        entrada["ruta"] = ruta_nueva
        if item_nuevo is not None:
            entrada["item"] = item_nuevo
    return nuevo


# ---------------------------------------------------------------- 🙈 censurar (cámara del youtuber, una cara…)
# Reutiliza el «Tapar (censurar)» de Figuras geométricas: fx["blur_regions"] (core/effects.py), que el visor ya deja
# mover y cambiar de tamaño con sus tiradores, y Figuras geométricas cambia de cuadro a círculo, desenfoque o pixelado
# y la fuerza. Aquí solo se elige DÓNDE va el recuadro.
ESQUINA_CAMARA = {"x": 0.83, "y": 0.79, "w": 0.28, "h": 0.32}     # abajo a la derecha (donde suele ir la cámara)
MARGEN_CARA = 0.35            # la caja de la cara, un 35 % más grande (pelo, cuello, el borde de la cámara)
SE_MUEVE = 0.08               # si el centro de la cara se mueve más que esto (fracción) en el trozo: «seguir»
ORIGEN_CENSURA = "material_frases"     # (marca de la zona puesta por «Censurar»: «Seguir» la sustituye)


def _leer_bgr(ruta: str):
    try:
        import cv2
        img = cv2.imdecode(np.fromfile(ruta, dtype=np.uint8), cv2.IMREAD_COLOR)
        return img if img is not None and img.size else None
    except Exception:  # noqa: BLE001
        return None


def _fotogramas(ruta: str, es_video: bool, desde: float = 0.0, dur: float = 0.0, n: int = 5) -> list:
    if not es_video:
        img = _leer_bgr(ruta)
        return [img] if img is not None else []
    from ..core import media as MT
    out = []
    for k in range(n):
        t = desde + (dur * (k + 0.5) / n if dur > 0 else 0.0)
        rgb = MT.frame_rgb(ruta, t, width=640)
        if rgb is not None:
            out.append(np.ascontiguousarray(rgb[:, :, ::-1]))
    return out


def zona_censura(ruta: str, es_video: bool = False, desde: float = 0.0, dur: float = 0.0, detector=None) -> dict:
    """Dónde tapar: las caras detectadas (ai/tracking.detect_faces en unos fotogramas, cajas unidas y con margen) o, si
    no hay ninguna, la esquina típica de la cámara de un youtuber. {"x","y" (centro), "w","h", "cara": bool,
    "se_mueve": bool} en fracciones de la IMAGEN (o del fotograma)."""
    if detector is None:
        from .tracking import detect_faces as detector
    cajas, centros = [], []
    for fr in _fotogramas(ruta, es_video, desde, dur):
        try:
            caras = [c for c in detector(fr) if c[2] * c[3] >= 0.002]
        except Exception:  # noqa: BLE001 - sin el modelo de caras: la esquina
            caras = []
        if caras:
            x0 = min(c[0] for c in caras)
            y0 = min(c[1] for c in caras)
            x1 = max(c[0] + c[2] for c in caras)
            y1 = max(c[1] + c[3] for c in caras)
            cajas.append((x0, y0, x1, y1))
            centros.append(((x0 + x1) / 2, (y0 + y1) / 2))
    if not cajas:
        return dict(ESQUINA_CAMARA, cara=False, se_mueve=False)
    x0, y0 = min(c[0] for c in cajas), min(c[1] for c in cajas)
    x1, y1 = max(c[2] for c in cajas), max(c[3] for c in cajas)
    w, h = (x1 - x0) * (1 + MARGEN_CARA), (y1 - y0) * (1 + MARGEN_CARA)
    w, h = min(1.0, max(0.04, w)), min(1.0, max(0.04, h))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    mueve = len(centros) > 1 and max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in centros for b in centros) > SE_MUEVE
    return {"x": round(float(cx), 4), "y": round(float(cy), 4), "w": round(float(w), 4), "h": round(float(h), 4),
            "cara": True,
            "se_mueve": bool(mueve)}


def _a_caja(zona: dict, img_w: int, img_h: int, box_w: float, box_h: float) -> dict:
    """De fracciones de la imagen a fracciones de la CAJA del clip (las zonas de core/effects van en la caja, y la
    imagen va dentro con «contain»: puede sobrar a los lados o arriba y abajo)."""
    from ..core import transform
    if img_w <= 0 or img_h <= 0:
        return {k: zona[k] for k in ("x", "y", "w", "h")}
    sw, sh = transform.fit_size(img_w, img_h, max(2, int(box_w)), max(2, int(box_h)), "contain")
    ox, oy = (box_w - sw) / 2, (box_h - sh) / 2
    return {"x": (ox + zona["x"] * sw) / box_w, "y": (oy + zona["y"] * sh) / box_h,
            "w": zona["w"] * sw / box_w, "h": zona["h"] * sh / box_h}


def aplicar_censura(ctrl, clip_id: str, zona: dict, forma: str = "rect", modo: str = "blur",
                    fuerza: float = 0.6) -> bool:
    """🙈 Pone el recuadro borroso en ese clip (un Ctrl+Z), con el mismo sistema que «Tapar (censurar)»."""
    from ..core import effects as E
    from ..core import transform
    p = ctrl.project
    c = p.clips.get(clip_id)
    m = p.media_of(c) if c is not None else None
    if c is None or m is None:
        return False
    box = c.layout or transform.FULL
    bw, bh = box["w"] * p.width, box["h"] * p.height
    if not (m.width and m.height):
        try:
            from ..core import media as MT
            info = MT.probe(m.path)
            mw, mh = int(info.get("width") or 0), int(info.get("height") or 0)
        except Exception:  # noqa: BLE001
            mw = mh = 0
    else:
        mw, mh = int(m.width), int(m.height)
    r = E.new_region(forma, bw, bh)
    r.update(_a_caja(zona, mw, mh, bw, bh))
    r["amount"] = round(float(fuerza), 2)
    r["origen"] = ORIGEN_CENSURA
    if modo == "pixel":
        r["mode"] = "pixel"
    fx = dict(c.fx or {})
    fx["blur_regions"] = list(fx.get("blur_regions") or []) + [r]
    return bool(ctrl.batch_clip_props({c.id: {"fx": fx}}, "🙈 Censurar"))


def plan_seguimiento(ruta: str, desde: float, hasta: float, zona: dict, cancelled=None) -> dict | None:
    """🎯 «Seguir»: el recorrido de lo tapado durante el trozo (el seguidor simple de ai/tracking.track), listo para
    guardarlo en el clip (formato de core/motion_track). None si no se pudo seguir."""
    from ..core import media as MT
    from ..core import motion_track as MTR
    from . import tracking
    info = MT.probe(ruta)
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    zw, zh = min(1.0, float(zona["w"])), min(1.0, float(zona["h"]))
    x0 = min(max(0.0, float(zona["x"]) - zw / 2), 1.0 - zw)
    y0 = min(max(0.0, float(zona["y"]) - zh / 2), 1.0 - zh)
    muestras = tracking.track(ruta, desde, hasta, (x0, y0, zw, zh), w, h, fps=10.0, cancelled=cancelled)
    if len(muestras) < 2:
        return None
    trk = MTR.new_track("Lo tapado", fps=10.0)
    trk = MTR.replace_auto(trk, desde, hasta, [list(m) + [1.0] for m in muestras])
    return MTR.clean(trk)


def aplicar_seguimiento(ctrl, clip_id: str, trk: dict, forma: str = "rect", modo: str = "blur",
                        fuerza: float = 0.7) -> bool:
    """La censura fija pasa a acompañar a lo seguido (fx «tracked_blur» con ctrl.track_blur, el mismo de
    «Seguimiento → taparlo»). Un solo Ctrl+Z: se quita la zona fija de «Censurar» y se pone la que sigue."""
    c = ctrl.project.clips.get(clip_id)
    if c is None or not trk:
        return False
    ctrl.undo_stack.beginMacro("🎯 Seguir lo censurado")
    try:
        ok = ctrl.track_blur(clip_id, None, forma, modo, fuerza, 1.0, save=trk)
        c = ctrl.project.clips.get(clip_id)
        regs = list((c.fx or {}).get("blur_regions") or []) if (ok and c is not None) else []
        quedan = [r for r in regs if r.get("origen") != ORIGEN_CENSURA]
        if ok and len(quedan) != len(regs):      # (solo si ya sigue: si no, la censura fija se queda)
            fx = dict(c.fx or {})
            if quedan:
                fx["blur_regions"] = quedan
            else:
                fx.pop("blur_regions", None)
            ctrl.batch_clip_props({clip_id: {"fx": fx}}, "🙈 Censura fija → seguir")
    finally:
        ctrl.undo_stack.endMacro()
    return bool(ok)


# ---------------------------------------------------------------- versión pública / privada
MODULOS_PRIVADOS = ("editoria.ai.clip_search", "editoria.ai.clip_download", "editoria.ai.material_videos")
MODULO_VIDEOS = "editoria.ai.material_videos"      # (la parte privada de videos, si está en este PC)


def hay_videos() -> bool:
    """¿Está la parte PRIVADA de videos (solo en el PC del usuario, gitignorada)? Sin importarla: solo se mira."""
    import importlib.util
    try:
        return all(importlib.util.find_spec(m) is not None for m in MODULOS_PRIVADOS)
    except (ImportError, ValueError):
        return False


def _videos():
    """El módulo privado de videos si está (como hace el panel Clips con HAY_INTERNET); si no, None."""
    if not hay_videos():
        return None
    import importlib
    try:
        return importlib.import_module(MODULO_VIDEOS)
    except ImportError:
        return None


def nuevas_fuentes_video():
    """Versión privada: las fuentes de video (con sus «fallos» y «avisos» para el panel). Sin la parte privada, None."""
    mod = _videos()
    return mod.FuentesVideo() if mod is not None else None


def textos_video() -> dict:
    """Los textos de la interfaz que hablan de videos los aporta la parte privada (aquí, ninguno)."""
    mod = _videos()
    return dict(getattr(mod, "TEXTOS", {}) or {}) if mod is not None else {}


def plan_videos(momentos_: list[dict], trozo: int, progress=None, cancelled=None, **k) -> list[dict]:
    """Versión privada: un trozo de video (15/30/60 s) para cada momento. Sin la parte privada, nada."""
    mod = _videos()
    if mod is None:
        return []
    return mod.plan_videos(momentos_, trozo, progress=progress, cancelled=cancelled, **k)


def buscar_videos_frase(frase: str, termino: str | None, trozo: int, **k) -> list[dict]:
    """Versión privada: 4–6 videos para una frase (con el trozo marcado). Sin la parte privada, nada."""
    mod = _videos()
    return mod.buscar_para_frase(frase, termino, trozo, **k) if mod is not None else []


def bajar_video(c: dict, trozo: int, termino: str | None, frase: str, **k) -> tuple[str, float]:
    mod = _videos()
    if mod is None:
        raise RuntimeError("Los videos solo están en la versión con la parte de internet.")
    return mod.bajar_resultado(c, trozo, termino, frase, **k)


def poner_video_en(ctrl, ruta: str, tl: float, mejor: float = 0.0, censura: dict | None = None) -> str | None:
    mod = _videos()
    return mod.poner_video_en(ctrl, ruta, tl, mejor, censura) if mod is not None else None
