"""
🔎 EL BUSCADOR DE RECLAIMER (22/11, el usuario: «el buscador de descargas, lo más preciso que puedas; el de frases y
palabras clave también muy bueno»). UNA sola lógica para Descargas (por fuentes), Palabras clave → Buscar material y
Material por frases. Sin Qt y SIN RED: aquí solo se entiende la consulta, se preparan las búsquedas y se ordena lo que
traiga cada fuente. Quién busca en internet vive en otros módulos (opcionales); la versión pública
lo usa para sus imágenes libres (entender, consultas y orden).

  entender(frase, termino=None, extra_terms=(), glossary=None) -> ent
      material_por_frases.entender (tema, acciones, objetos) + «entidades» (todas: «GTA 6», «PS5», «CE-108255-1»,
      nombres propios) con sus variantes («GTA VI», «Grand Theft Auto 6», «PlayStation 5») + «claves» (lo que se busca:
      «crasheo» → crashing / freezing / se cuelga), cada una con su TIPO (acción o detalle) y, si es ambigua, su
      SENTIDO (SENTIDOS: «crash» con una consola = el juego se cuelga, no un avión que se estrella) + «actualidad».
  consultas_youtube(ent) / consulta_x(ent) / hashtags(ent)    las búsquedas de cada fuente
  puntuar(resultados, ent, sin_gente=False, prefs=None) -> los mismos, ordenados, cada uno con «puntos» y «motivo»
      PRIMERO LA RELEVANCIA, por niveles («nivel», 0–4): la acción en su sentido correcto (en el título vale más que
      solo en la descripción) × la entidad principal + todas las entidades. Lo que usa la palabra en OTRO sentido
      («Plane Crash»), lo que no es lo pedido («concept», «parody»), la gente hablando con «Sin gente hablando» y las
      resubidas bajan al fondo. DENTRO de cada nivel: cobertura de todas las claves, parecido CLIP de la miniatura,
      canal oficial, visitas (log; casi nadie lo vio = peor), duración, lo que ya elegiste antes del mismo tema y la
      fecha (solo desempata, y solo si es actualidad).
  aprender(item, ent) / preferencias()      lo que bajas o pones sube un poco en las siguientes búsquedas del mismo
      tema (datos/buscador_preferencias.json: local, pequeño; solo canales).
  es_comentario(titulo)                     reacción, opinión, noticias, podcast… (sin tildes)
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata

# ---------------------------------------------------------------- variantes de nombres (sin tildes ni mayúsculas)
# Nombre → otras formas de decirlo. Los números en romano, pegados o en palabras ya los une keyword_folders.compacta
# («GTA VI» = «GTA 6» = «gta6»); aquí van las que no se pueden deducir.
ALIAS = {
    "PS5": ["PlayStation 5", "PS 5", "PlayStation5"],
    "PS5 Pro": ["PlayStation 5 Pro", "PS5Pro"],
    "PS4": ["PlayStation 4", "PS 4"],
    "PS4 Pro": ["PlayStation 4 Pro"],
    "PS3": ["PlayStation 3"],
    "PS Vita": ["PlayStation Vita"],
    "PlayStation": ["PS", "Sony PlayStation"],
    "GTA 6": ["GTA VI", "Grand Theft Auto 6", "Grand Theft Auto VI", "GTA6"],
    "GTA 5": ["GTA V", "Grand Theft Auto 5", "Grand Theft Auto V", "GTA5"],
    "GTA 4": ["GTA IV", "Grand Theft Auto 4", "Grand Theft Auto IV"],
    "GTA Online": ["Grand Theft Auto Online"],
    "RDR2": ["Red Dead Redemption 2", "RDR 2"],
    "Xbox Series X": ["XSX", "Series X"],
    "Xbox Series S": ["XSS", "Series S"],
    "Nintendo Switch 2": ["Switch 2"],
    "Nintendo Switch": ["Switch"],
    "Rockstar": ["Rockstar Games"],
    "CoD": ["Call of Duty"],
    "BO7": ["Black Ops 7"],
    "TLOU": ["The Last of Us"],
    "Zelda": ["The Legend of Zelda"],
}
# Una marca que nombra a toda su familia: «PlayStation» también es «PS5» o «PS4» en un título (solo para encontrar;
# «PS5» NO es «PS4»: por eso no van en ALIAS).
FAMILIAS = {
    "PlayStation": ["PS5", "PS5 Pro", "PS4", "PS4 Pro", "PS3", "PS2", "PS1", "PS Vita", "PSN", "PlayStation 5",
                    "PlayStation 4"],
    "Xbox": ["Xbox Series X", "Xbox Series S", "Xbox One", "Series X", "Series S"],
    "Nintendo": ["Nintendo Switch", "Switch 2", "Switch"],
}

# Palabras de la frase → lo que se busca (inglés y español). Clave: la palabra sin tildes (o su comienzo).
# tipo: «a» = la ACCIÓN o lo que se pide ver (crash, humo, tráiler…: sin ella el video no es lo pedido) · «o» = un
# detalle (ventilador, pantalla…). sentido: la entrada de SENTIDOS si la palabra es ambigua.
TERMINOS = [
    (r"crashe\w*|crash\w*|cuelg\w*|congela\w*|freez\w*", ["crash", "crashing", "crashes", "freeze"],
     ["crashea", "se cuelga", "se congela", "crasheo"], "a", "crash"),
    (r"apag\w*", ["shuts down", "shutting down", "turns off", "turning off", "shutdown"], ["se apaga", "apaga"], "a",
     "apagar"),
    (r"sobrecalent\w*|calent\w*|overheat\w*", ["overheating", "overheat", "overheated"],
     ["sobrecalentamiento", "se calienta"], "a", "calor"),
    (r"humo\w*", ["smoke", "smoking"], ["humo", "echa humo"], "a", "humo"),
    (r"ventilador\w*", ["fan", "fan noise"], ["ventilador"], "o", "fan"),
    (r"ruido\w*", ["noise", "loud"], ["ruido"], "o", None),
    (r"retras\w*|delay\w*|aplaz\w*|pospon\w*", ["delay", "delayed", "postponed"], ["retraso", "retrasa", "aplazado"],
     "a", "retraso"),
    (r"rendimiento|performance|fps", ["performance", "fps", "frame rate"], ["rendimiento"], "a", "rendimiento"),
    (r"trailer\w*|trailers?", ["trailer"], ["trailer", "tráiler"], "a", "trailer"),
    (r"gameplay\w*|jugabilidad|partida\w*", ["gameplay"], ["gameplay", "jugabilidad"], "a", "gameplay"),
    (r"error\w*|fallo\w*|bug\w*", ["error", "bug"], ["error", "fallo"], "a", "error"),
    (r"precio\w*|cuesta|price", ["price"], ["precio"], "a", None),
    (r"lanzamiento|estreno|release", ["release date", "launch"], ["lanzamiento", "fecha de salida"], "a", None),
    (r"filtra\w*|leak\w*|fuga\w*", ["leak", "leaked"], ["filtración"], "a", "leak"),
    (r"parche\w*|actualizacion\w*|update\w*|patch\w*", ["update", "patch"], ["actualización", "parche"], "a",
     "parche"),
    (r"ban|baneo\w*|banea\w*|banned|prohib\w*", ["ban", "banned"], ["baneo", "prohibido"], "a", "ban"),
    (r"vs|versus|comparacion\w*|comparativa\w*|compar\w*", ["vs", "comparison"], ["vs", "comparativa"], "o", "vs"),
    (r"pantalla\w*", ["screen"], ["pantalla"], "o", None),
    (r"negro|negra", ["black"], ["negro"], "o", None),
    (r"mando\w*|control\w*|controller\w*", ["controller"], ["mando"], "o", None),
    (r"disco\w*", ["disc"], ["disco"], "o", "disco"),
    (r"descarga\w*|download\w*", ["download"], ["descarga"], "a", None),
    (r"mapa\w*", ["map"], ["mapa"], "o", None),
    (r"graficos|grafico|graphics", ["graphics"], ["gráficos"], "a", None),
]
_TERM_RE = [(re.compile(r"^(?:" + p + r")$"), en, es, tipo, sen) for p, en, es, tipo, sen in TERMINOS]

# 🧭 SENTIDOS de las palabras ambiguas de videojuegos y noticias (22/11, el usuario: «GTA 6 PS5 crasheo» traía «Plane
# Crash Random Event»). Cada palabra, sus sentidos; el primero es el de por defecto y gana otro si la FRASE trae más
# pistas suyas («pista»: una consola, un error… / un avión, un coche…). Todo sin tildes, en minúsculas y como
# expresiones regulares sobre palabras enteras:
#   buscar  cómo se busca en inglés (la 1.ª va en las consultas; las otras, en consultas extra)
#   si      palabras del título/descripción que CONFIRMAN ese sentido (también cuentan como la clave)
#   no      las que dicen que es el OTRO sentido: en el título y sin un «si» fuera de ellas → «en otro sentido»
#   fuera   lo que no es lo pedido aunque lo nombre («concept», «parody»), salvo que la frase lo pida
#   exige   sin un «si» en el título o la descripción no cuenta («humo» pide humo de verdad: smoke, burning…)
#   oficial cuánto más pesa un canal oficial (un tráiler: el de Rockstar, no el de un fan)
_HW = (r"ps ?[1-5]|ps ?vita|psn|playstation\w*|xbox\w*|series [xs]|switch|nintendo|pc|steam ?deck|consolas?|"
       r"consoles?|gpu|tarjeta grafica|nvidia|amd|rtx|cpu|portatil|laptop|movil|iphone|android|mando|controller")
_FALLO = r"error\w*|fallo\w*|bug\w*|cuelg\w*|congel\w*|apag\w*|crashe\w*|pantallazo|codigo|ce \d+|reinici\w*"
_ACCIDENTE = (r"planes?|airplanes?|jets?|aircraft|airport|cars?|trucks?|bikes?|motorcycles?|landing|accidents?|"
              r"random events?|chase\w*|police|cops?|helicopters?|heli|trains?|boats?|ships?|pile ?ups?|collisions?|"
              r"crash tests?|derby|ragdoll|flights?|avion\w*|avioneta\w*|coches?|accidente\w*|persecucion\w*|"
              r"aterriz\w*|choque\w*|crashing (?:into|cars|planes)|crash(?:es|ed)? into")
SENTIDOS = {
    "crash": [
        {"nombre": "el juego se cuelga", "pista": _HW + "|" + _FALLO,
         "buscar": ["crashing", "freezing", "crash fix"],
         # (solo lo que dice que SE CUELGA: «bugs», «lag» o «glitch» sueltos no son un crasheo)
         "si": r"crashing|crashes|crashed|crash (?:fix|bug|issue|problem|error)|freez\w*|frozen|"
               r"shut(?:s|ting)? (?:down|off)|shutdown|turn(?:s|ing|ed)? off|error\w*|ce \d{5,}|"
               r"not (?:launching|loading|working|responding|starting)|won'?t (?:launch|load|start)|"
               r"wont (?:launch|load|start)|black screen|stuck (?:on|at|in) (?:the )?loading|se cuelga|crashea\w*|"
               r"crasheo\w*|se congela|se apaga|se cierra|se traba\w*|trabando|pantallazo",
         "no": _ACCIDENTE + r"|bandicoot|stock market|market crash|crash(?:es)? out|crash course"},
        {"nombre": "choque o accidente", "pista": r"avion\w*|avioneta\w*|coches?|autos?|carros?|motos?|accidente\w*|"
                                                   r"choque\w*|choca\w*|aterriz\w*|persecucion\w*|helicoptero\w*|"
                                                   r"trenes?|barcos?|planes?|cars?",
         "buscar": ["crash"], "si": _ACCIDENTE,
         "no": r"crashing (?:fix|on|issue)|error\w*|freez\w*|fix\w*|ce \d+|bandicoot"},
    ],
    "apagar": [
        {"nombre": "se apaga sola", "pista": "", "buscar": ["shuts down", "turning off", "turns off by itself"],
         "si": r"shut(?:s|ting)? (?:down|off)|shutdown|shuts? off|turn(?:s|ing|ed)? off|power(?:s|ing|ed)? (?:off|down)|"
               r"by itself|randomly|se apaga\w*|apagando|apagon\w*|apaga sola|reinici\w*|restart\w*|reboot\w*",
         "no": r"settings?|should turn off|need to turn off|turn off these|turn this off|features?|options?|ajustes|"
               r"configuracion\w*|opciones|luces|lights?|notifications?|notificaciones|motion blur|hdr|vrr"},
    ],
    "calor": [
        {"nombre": "sobrecalentamiento", "pista": "", "buscar": ["overheating", "overheat"],
         "si": r"overheat\w*|over heating|temperatur\w*|temps?|thermal\w*|heat\w*|hot|runs? hot|calient\w*|"
               r"sobrecalent\w*|cooling|cooler|liquid metal|refrigeracion",
         "no": r"hot takes?|hot coffee|hottest|hot girls?|hot wheels|heat waves?|hot pursuit|hot dogs?|red hot"},
    ],
    "humo": [
        {"nombre": "humo de verdad", "pista": "", "exige": True,
         "buscar": ["smoke", "smoking", "smoke coming out", "burning smell", "caught fire"], "sin_juegos": True,
         "si": r"smoke|smokes|smoking|smoked|smoky|burn(?:s|ing|t|ed)?|fire|flames?|on fire|melt\w*|humo|quema\w*|"
               r"fuego|incendi\w*|explod\w*|explosion\w*|exploto|explota\w*|blew up|blown up|sparks?|chispas?",
         "no": r"burn(?:ing)? (?:rubber|notice)|fire (?:emblem|force|red|them|him|her|all|everyone|sale)|fired|"
               r"firing|ceasefire|burnout|smoke and mirrors|holy smokes?|"
               r"smok(?:ing|ed|es?) (?:the|them|him|her|ops|kids|people|noobs|everyone|everybody)",
         # (otro humo: un personaje u operador de un juego, una misión, granadas, tabaco, una consola de casa de
         # fumadores, «go up in smoke» en sentido figurado…; sin_juegos: un título que nombra un juego, tampoco)
         "fuera": r"mortal kombat|mk ?\d+|grenades?|weed|vape\w*|vaping|cigar\w*|smoke bombs?|bbq|brisket|"
                  r"smokers?|granadas?|hookah|smoke tests?|smoke damage|nicotine|soot|tobacco|tabaco|ceniza\w*|"
                  r"operators?|showcase|walkthrough|playthrough|part \d+|parte \d+|chapter|boss|characters?|"
                  r"personajes?|skins?|trailers?|dlc|(?:go|goes|going|went) up in smoke|up in smoke|smoke breaks?|"
                  r"scenario|old clips|gameplay|powers?"},
    ],
    "fan": [
        {"nombre": "ventilador", "pista": "", "buscar": ["fan", "loud fan", "fan noise"],
         "si": r"fan noise|loud fan|fans? (?:is |are )?(?:loud|noisy|spinning|speed|replacement|cleaning|clean|broken|"
               r"making|not working|noise)|cooling fan|ventilador\w*|ventilacion|rpm|jet engine|cooling|cooler|dust|"
               r"polvo|ruido|noise|loud",
         "no": r"fans? react\w*|fan ?made|fan art|fan theor\w*|fan concepts?|fan reactions?|fan service|"
               r"fan favou?rites?|fan films?|fan edits?|fanbase|fans (?:are|think|want|say|hate|love)|for fans|"
               r"super fans?|big fan|fan trailers?|fan games?|fans? of|fanaticos|seguidores"},
    ],
    "retraso": [
        {"nombre": "retraso del lanzamiento", "pista": "", "buscar": ["delay", "delayed"],
         "si": r"delay\w*|postpon\w*|pushed back|push(?:ed|es)? (?:to|back)|release date|launch date|new date|"
               r"retras\w*|aplaz\w*|pospon\w*|nueva fecha|fecha de (?:salida|lanzamiento)",
         "no": r"input (?:delay|lag)|latency|audio delay|delay pedal|guitar|ping|desync|delay effect|frame delay|"
               r"retraso de (?:input|audio|imagen)|reverb"},
    ],
    "error": [
        {"nombre": "error del programa", "pista": "", "buscar": ["error", "error code"],
         "si": r"error\w*|codes?|codigo\w*|ce \d{5,}|fix\w*|solucion\w*|bug\w*|problem\w*|issues?|crash\w*|"
               r"fallo\w*",
         "no": r"trial and error|human error",
         "fuera": r"parod\w*|memes?|through the years|evolution of|evolucion de|funny|gracios\w*|compilation"},
    ],
    "trailer": [
        {"nombre": "tráiler", "pista": "", "buscar": ["trailer", "official trailer"], "oficial": 3.0,
         "si": r"trailers?|teasers?|traileres|avance",
         "no": r"trucks?|semi|towing|tow|trailer park|hitch|camion\w*|remolque\w*|18 wheeler",
         "fuera": r"concepts?|fan ?made|fake|ai generated|hecho por (?:un )?fan|recreat\w*|reimagin\w*|"
                  r"fan trailers?|what if|my version|mi version|parod\w*|unreal engine|ue5|recreacion\w*",
         "fuera_desc": True},
    ],
    "gameplay": [
        {"nombre": "gameplay", "pista": "", "buscar": ["gameplay", "walkthrough"],
         "si": r"gameplay|walkthrough|playthrough|free ?roam|let ?s play|full game|missions?|partida\w*|jugabilidad|"
               r"part \d+|parte \d+|campaign|campana|no commentary|sin comentarios",
         "no": ""},
    ],
    "rendimiento": [
        {"nombre": "rendimiento", "pista": "", "buscar": ["performance", "fps", "graphics comparison"],
         "si": r"performance|fps|frame ?rate|framerate|resolution|graphics|comparison|compared|tested|test|"
               r"benchmark\w*|4k|1080p|1440p|\d+ ?fps|runs?|running|rendimiento|graficos|comparativa|comparacion|"
               r"loading times?|ray ?tracing|pssr|upscal\w*|all versions",
         "no": r"concerts?|live performance|songs?|dance\w*|music|singer|performance art|stage"},
    ],
    "vs": [
        {"nombre": "comparativa", "pista": "", "buscar": ["vs", "comparison"],
         "si": r"vs|versus|comparison|compared|comparativa|comparacion|side by side|all versions|which (?:is )?better",
         "no": ""},
    ],
    "leak": [
        {"nombre": "filtración", "pista": "", "buscar": ["leak", "leaked"],
         "si": r"leak\w*|filtra\w*|insider\w*|footage|screenshots?|datamin\w*",
         "no": r"water|liquid|pipes?|gas|oil|roof|agua|liquido|aceite|tuberia\w*"},
        {"nombre": "fuga de líquido", "pista": r"liquido|agua|metal|pasta|aceite|liquid|water|thermal",
         "buscar": ["liquid metal leak", "leaking"],
         "si": r"liquid metal|leak\w*|fuga\w*|agua|water|liquid|thermal paste|pasta termica",
         "no": r"footage|insider\w*|trailers?|screenshots?|datamin\w*"},
    ],
    "parche": [
        {"nombre": "actualización del juego", "pista": "", "buscar": ["update", "patch notes"],
         "si": r"updates?|patch\w*|hotfix\w*|title update|version \d+|v ?\d+ \d+|actualizacion\w*|parche\w*",
         "no": r"news update|channel update|life update|weekly update|embroider\w*|iron on|sew\w*|eye patch|tire|"
               r"tyre|drywall|bordad\w*|patch cable"},
    ],
    "ban": [
        {"nombre": "baneo de cuentas", "pista": "", "buscar": ["ban", "ban wave", "banned"],
         "si": r"ban\w*|ban wave|suspend\w*|suspension|cheat\w*|hack\w*|mod menu|baneo\w*|banea\w*|suspendid\w*",
         "no": r"banned in|government|gobierno|pais|country|censor\w*|illegal|ilegal|banana\w*|banner\w*|bank\w*"},
        {"nombre": "prohibido en un país", "pista": r"pais\w*|gobierno\w*|prohib\w*|censura\w*|ilegal|ley|leyes",
         "buscar": ["banned in", "ban country"],
         "si": r"banned in|government|censor\w*|prohib\w*|country|pais\w*|gobierno|illegal|ilegal|rating refused",
         "no": r"ban wave|cheat\w*|hack\w*|accounts?|cuentas?|mod menu|banana\w*|banner\w*"},
    ],
    "disco": [
        {"nombre": "disco del juego", "pista": "", "buscar": ["disc"],
         "si": r"discs?|disco|lector|drive|blu ?ray",
         "no": r"disco music|disco elysium|dance\w*|baile\w*|musica|party|fiesta|70s"},
    ],
}
_RX: dict = {}


def _rx(patron: str):
    """La expresión de un sentido, compilada una vez (palabras enteras sobre el texto de norm())."""
    if not patron:
        return None
    if patron not in _RX:
        _RX[patron] = re.compile(r"\b(?:" + patron + r")\b")
    return _RX[patron]


def _elegir_sentido(clave_s: str | None, frase_n: str) -> dict | None:
    """El sentido de esa palabra ambigua según las pistas de la frase (el primero si nada lo cambia)."""
    opciones = SENTIDOS.get(clave_s or "") or []
    if not opciones:
        return None
    texto = f" {frase_n} "

    def pistas(i):
        rx = _rx(opciones[i].get("pista") or "")
        return len(rx.findall(texto)) if rx else 0
    return opciones[max(range(len(opciones)), key=lambda i: (pistas(i), -i))]

# Lo que dice que es algo de AHORA (una noticia, un fallo nuevo): entonces cuenta la fecha
ACTUALIDAD = re.compile(r"^(?:crashe\w*|crash\w*|cuelg\w*|noticia\w*|nuev[oa]s?|ahora|hoy|ayer|retras\w*|parche\w*|"
                        r"actualizacion\w*|error\w*|fallo\w*|filtra\w*|leak\w*|rumor\w*|anuncio\w*|anuncia\w*|"
                        r"lanzamiento|precio\w*|apag\w*|sobrecalent\w*|humo|oficial|confirma\w*|news|update)$")
# Palabras que no ayudan a encontrar nada cuando ya hay una entidad («consola» con «PS5» ya está dicho)
DEBILES = {"consola", "consolas", "juego", "juegos", "videojuego", "video", "videos", "cosa", "pro", "sin",
           "comentarios", "comentario", "version", "nuevo", "nueva"}
# «sin comentarios» / «no commentary»: quiere partidas sin voz
SIN_VOZ = re.compile(r"\b(sin comentarios?|no commentary|sin hablar|sin voz)\b")

# Reacciones, opiniones, noticias, podcasts… (una sola lista para todo el programa)
_COMENTARIO = [
    r"react\w*", r"reaccion\w*", r"reacciona\w*", r"thoughts?", r"speculat\w*", r"opinion\w*",
    r"let'?s talk", r"talk", r"podcast\w*", r"news", r"noticias?", r"rumou?rs?", r"leaks?", r"leaked",
    r"backlash", r"what is going on", r"explained", r"breakdown", r"reviews?", r"analisis", r"is getting",
    r"crashes out", r"drama", r"my take", r"discussion", r"live", r"stream\w*", r"esto es todo", r"impressions?",
    r"impresiones",
]
_RE_COMENTARIO = re.compile(r"\b(?:" + "|".join(_COMENTARIO) + r")\b")
_RE_COMPILACION = re.compile(r"\b(?:compilation|compilacion|recopilacion|top ?\d+|best moments|mejores momentos|"
                             r"funny moments|momentos graciosos|every|todos los)\b")
_RE_CODIGO = re.compile(r"\b[A-Z]{1,4}-\d{3,}(?:-\d+)?\b")          # (códigos de error: «CE-108255-1»)


def norm(s: str) -> str:
    """Sin tildes, en minúsculas, solo letras y números separados por un espacio."""
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", s))


def es_comentario(titulo: str) -> bool:
    """¿El título parece de alguien hablando a cámara (reacción, opinión, noticias…)? Sin tildes ni mayúsculas."""
    return bool(_RE_COMENTARIO.search(norm(titulo)))


def _compacta(s: str) -> str:
    from ..core import keyword_folders as KF
    try:
        return KF.compacta(s)
    except Exception:  # noqa: BLE001
        return norm(s).replace(" ", "")


# ---------------------------------------------------------------- entender
def _variantes(nombre: str) -> list[str]:
    """El nombre y sus otras formas (alias de la tabla, en las dos direcciones)."""
    c = _compacta(nombre)
    out = [nombre]
    for k, vs in ALIAS.items():
        formas = [k] + vs
        if any(_compacta(f) == c for f in formas):
            out += [f for f in formas if norm(f) != norm(nombre)]
    vistos, res = set(), []
    for v in out:                       # («GTA VI» y «GTA 6» se escriben distinto: las dos, para buscar y enseñar)
        nv = norm(v)
        if nv and nv not in vistos:
            vistos.add(nv)
            res.append(v)
    return res


def _alias_en(frase: str) -> list[str]:
    """Los nombres de la tabla de alias que aparecen tal cual en la frase (el más largo primero: «PS5 Pro» antes que
    «PS5»; «PS5» también si se dice SUELTO aparte: «PS5 Pro vs PS5»)."""
    t = " " + norm(frase) + " "
    hallados = []
    for k, vs in ALIAS.items():
        formas = sorted({norm(f) for f in [k] + vs if len(norm(f)) >= 2}, key=len, reverse=True)
        dentro = [f for f in formas if f" {f} " in t]
        if dentro:
            hallados.append((len(dentro[0]), k, formas))
    hallados.sort(key=lambda h: -h[0])
    out, resto = [], t
    for _l, k, formas in hallados:
        if not any(f" {f} " in resto for f in formas):
            continue                                    # (solo estaba dentro de uno más largo)
        out.append(k)
        for f in formas:                                # (lo ya usado no cuenta para los más cortos)
            while f" {f} " in resto:
                resto = resto.replace(f" {f} ", " | ")
    return out


def _menciones(frase: str, extra_terms=(), glossary=None) -> list[str]:
    from types import SimpleNamespace

    from . import mentions
    from .material_por_frases import _palabras
    ws = _palabras(frase)
    if not ws:
        return []
    words = [[i * 0.3, i * 0.3 + 0.25, w] for i, w in enumerate(ws)]
    falso = SimpleNamespace(transcripts={"frase": {"words": words}}, clips={}, compounds={}, media={}, tracks=[])
    try:
        return [m["term"] for m in mentions.find_mentions(falso, extra_terms=list(extra_terms or ()),
                                                          glossary=glossary)]
    except Exception:  # noqa: BLE001
        return []


_CONOCIDOS: list = []


def _conocidos() -> set:
    """Los nombres conocidos de «Dijiste…» (juegos, sagas, empresas), compactados (se calcula una vez)."""
    if not _CONOCIDOS:
        try:
            from . import mentions
            _CONOCIDOS.append({_compacta(x) for x in mentions.CONOCIDOS})
        except Exception:  # noqa: BLE001
            return set()
    return _CONOCIDOS[0]


def _termino_de(palabra: str) -> tuple | None:
    """(inglés, español, tipo, sentido) de la palabra según TERMINOS, o None."""
    k = norm(palabra)
    for rx, en, es, tipo, sen in _TERM_RE:
        if rx.match(k):
            return en, es, tipo, sen
    return None


def entender(frase: str, termino: str | None = None, extra_terms=(), glossary=None, base: dict | None = None) -> dict:
    """La consulta entendida: lo de material_por_frases.entender + entidades con variantes, claves y actualidad.
    base = un entender() ya hecho (Material por frases): no se repite."""
    from . import material_por_frases as M
    frase = " ".join((frase or "").split())
    ent = dict(base) if base else M.entender(frase, termino, extra_terms, glossary)
    # 1) entidades: la palabra clave, lo que detecta «Dijiste…», la tabla de alias, códigos y nombres propios
    nombres = [x for x in ([ent.get("tema")] + _menciones(frase, extra_terms, glossary) + _alias_en(frase)) if x]
    nombres += _RE_CODIGO.findall(frase)
    entidades: list[dict] = []
    conocidos = _conocidos()
    sueltos = []
    for n in nombres:                       # («Jason Lucía»: dos nombres propios sin ser un título conocido → dos)
        ws_n = n.split()
        if len(ws_n) > 1 and all(w[:1].isupper() and w.isalpha() for w in ws_n) and                 _compacta(n) not in conocidos and not any(_compacta(n) == _compacta(k) for k in ALIAS):
            sueltos += ws_n
        else:
            sueltos.append(n)
    for n in sueltos:
        cn = _compacta(n)
        if not cn or any(cn == _compacta(v) for e in entidades for v in e["variantes"]):
            continue
        # «Jason Lucía» (dos nombres propios juntos) se busca como dos palabras: no se exigen juntas
        fam = next((v for k, v in FAMILIAS.items() if _compacta(k) == cn), [])
        entidades.append({"nombre": n, "variantes": _variantes(n), "familia": list(fam)})
    # (una entidad dentro de otra más larga —«PS5» y «PS5 Pro»— se queda solo si también se dice suelta)
    ws_frase = M._palabras(frase)
    tapadas = set()
    for e in entidades:
        for v in e["variantes"]:
            for w in norm(v).split():
                tapadas.add(w)
    # 2) claves: acciones y objetos de material_por_frases, la tabla de términos y lo que queda con contenido
    claves: list[dict] = []
    frase_n = norm(" ".join([frase, *(e["nombre"] for e in entidades)]))

    def clave(es_: list[str], en_: list[str], tipo: str = "o", sen: str | None = None):
        formas = [f for f in dict.fromkeys([*es_, *en_]) if f]
        if not formas or any(set(map(norm, formas)) & set(map(norm, c["formas"])) for c in claves):
            return
        s = _elegir_sentido(sen, frase_n)
        buscar = list((s or {}).get("buscar") or [])
        claves.append({"es": es_[0] if es_ else formas[0], "en": (buscar or en_ or [""])[0], "formas": formas,
                       "tipo": tipo, "sentido": s, "extra": buscar[1:]})
    # (primero la tabla de términos, con su tipo y su sentido; luego lo que entendió material_por_frases)
    for w in ws_frase:
        k = norm(w)
        t = _termino_de(w) if k and k not in tapadas else None
        if t:
            clave([w] + t[1], t[0], t[2], t[3])
    for a in ent.get("acciones") or []:
        clave([a["es"]], [a["en_s"], a["en"]], "a")
    for o in ent.get("objetos") or []:
        clave([o["es"]], [o["en"]])
    for w in ws_frase:
        k = norm(w)
        if not k or k in tapadas or _termino_de(w):
            continue
        if k not in DEBILES and M._con_contenido(w) and not any(k in norm(c["es"]) for c in claves) and \
                not _RE_CODIGO.match(w):
            clave([w], [])
    claves.sort(key=lambda c: c["tipo"] != "a")             # (la acción primero: es lo que más se busca)
    actual = any(ACTUALIDAD.match(norm(w) or "-") for w in ws_frase)
    ent.update({"entidades": entidades, "claves": claves, "actualidad": actual,
                "sin_voz": bool(SIN_VOZ.search(norm(frase))), "frase": frase,
                "pide_comentario": es_comentario(frase), "pide_compilacion": bool(_RE_COMPILACION.search(norm(frase)))})
    return ent


# ---------------------------------------------------------------- consultas de cada fuente
def _cita(n: str) -> str:
    return f'"{n}"' if " " in n.strip() else n


def consultas_youtube(ent: dict, maximo: int = 7) -> list[str]:
    """De la más concreta a la más general, en inglés y en español. La entidad de varias palabras entre comillas en la
    primera (YouTube respeta el orden y la frase exacta). La acción, en su SENTIDO («crasheo» con una consola →
    «crashing», no «crash»), y otras formas de decirla en consultas aparte («freezing», «burning smell»…)."""
    ents = [e["nombre"] for e in ent.get("entidades") or []]
    cl = ent.get("claves") or []
    en = [c["en"] for c in cl if c.get("en")]
    es_ = [c["es"] for c in cl]
    citadas = [_cita(n) for n in ents]
    extra = next((c.get("extra") or [] for c in cl if c.get("tipo") == "a" and c.get("extra")), [])
    out = [
        " ".join([*citadas, *en[:2]]),                                     # "GTA 6" PS5 crashing
        " ".join([*ents, *es_[:2]]),                                       # GTA 6 PS5 crasheo
        " ".join([*(max(e["variantes"], key=lambda v: len(v.split()))
                    for e in ent.get("entidades") or []), *en[:1]]),       # Grand Theft Auto 6 PlayStation 5 crashing
        *(" ".join([*citadas, x]) for x in extra[:3]),                     # "GTA 6" PS5 freezing · … crash fix
        " ".join([*ents[:1], *en[:1]]) if len(ents) > 1 else "",           # GTA 6 crashing
    ]
    if ent.get("sin_voz"):
        out.insert(1, " ".join([*ents, "gameplay no commentary"]))
    if not ents:
        out.append(ent.get("frase") or "")
    vistos, res = set(), []
    for q in out:
        q = " ".join(q.split())
        if q and q.lower() not in vistos:
            vistos.add(q.lower())
            res.append(q)
    return res[:maximo]


def consulta_x(ent: dict, min_faves: int = 10) -> str:
    """La búsqueda de X con sus operadores: solo videos, en español o inglés y con un mínimo de «me gusta»."""
    ents = [_cita(e["nombre"]) for e in ent.get("entidades") or []]
    cl = ent.get("claves") or []
    partes = list(ents)
    for c in cl[:2]:
        formas = [f for f in dict.fromkeys([c["en"], c["es"]]) if f]
        partes.append("(" + " OR ".join(_cita(f) for f in formas) + ")" if len(formas) > 1 else _cita(formas[0]))
    base = " ".join(partes) or (ent.get("frase") or "")
    return f"{base} filter:videos (lang:es OR lang:en) min_faves:{min_faves}"


def hashtags(ent: dict) -> list[str]:
    """#gta6 #ps5…: de las entidades, sin espacios ni signos."""
    out = []
    for e in ent.get("entidades") or []:
        h = _compacta(e["nombre"])
        if h and h not in out and not _RE_CODIGO.match(e["nombre"]):
            out.append(h)
    return out[:3]


# ---------------------------------------------------------------- orden: primero la relevancia, por niveles
PESOS = {"todas": 0.4, "entidad": 0.6, "titulo": 0.3, "clave": 1.6, "clip": 9.0, "fecha": 0.35, "oficial": 0.6,
         "visitas": 0.12, "poca_vista": 8.0, "duracion": 0.3, "comentario": -6.0, "compilacion": -0.9,
         "resubida": -6.0, "pref": 0.5, "otro_juego": -2.5, "otro_sentido": -1.0, "sin_voz": 1.0}
# Cuánto vale un nivel de relevancia (0–4) frente a lo demás (que suma, como mucho, unos ±10): en Descargas la
# relevancia manda del todo; en Material por frases (B-roll) lo que SE VE también cuenta; en las imágenes libres casi
# solo lo que se ve (sus títulos dicen poco): sin niveles.
NIVEL = {"descargas": 20.0, "frases": 8.0, "imagenes": 0.0}
# Cada sitio, con el mismo orden y otro acento
MODOS = {"descargas": {},
         "frases": {"todas": 0.3, "entidad": 0.3, "titulo": 0.1, "clave": 0.5, "clip": 14.0, "visitas": 0.05,
                    "fecha": 0.15},
         "imagenes": {"todas": 0.3, "entidad": 0.3, "titulo": 0.1, "clave": 0.2, "clip": 16.0, "visitas": 0.0,
                      "fecha": 0.0, "oficial": 0.0, "duracion": 0.0}}
_SIN_VOZ_TITULO = re.compile(r"\b(?:no commentary|sin comentarios?|no talking|sin hablar|sin voz|silent)\b")


def _compactos(texto_n: str) -> str:
    """Las n-gramas (1–4 palabras) compactadas, unidas por «|»: así «GTA VI», «gta-6» o «gta6» se encuentran."""
    ws = texto_n.split()
    out = []
    for n in range(1, 5):
        for i in range(0, len(ws) - n + 1):
            out.append(_compacta(" ".join(ws[i:i + n])))
    return "|" + "|".join(out) + "|"


def _en(texto_n: str, comp: str, formas) -> str | None:
    t = f" {texto_n} "
    for f in formas:
        cf = _compacta(f)
        nf = norm(f)
        if (nf and f" {nf} " in t) or (len(cf) >= 3 and f"|{cf}|" in comp):
            return f
        if nf and " " not in nf and len(nf) >= 4 and not nf.isdigit():     # (smoke → smokes / smoked; fan → fans)
            if any(f" {nf}{fin} " in t for fin in ("s", "es", "d", "ed")):
                return f
        if nf and len(nf) >= 3 and nf[-1].isdigit() and nf[0].isalpha() and f" {nf}s " in t:
            return f                                                     # (PS5 → «PS5s»)
    return None


_JUEGOS: list = []


def _juegos() -> dict:
    """Los juegos conocidos de «Dijiste…» (sin empresas ni consolas), compactados → nombre."""
    if not _JUEGOS:
        try:
            from . import material_por_frases as M
            from . import mentions
            _JUEGOS.append({_compacta(x): x for x in mentions.CONOCIDOS if not M.es_empresa(x)})
        except Exception:  # noqa: BLE001
            _JUEGOS.append({})
    return _JUEGOS[0]


def _es_empresa(nombre: str) -> bool:
    try:
        from . import material_por_frases as M
        return bool(M.es_empresa(nombre))
    except Exception:  # noqa: BLE001
        return False


def _es_juego(e: dict) -> bool:
    tuyos = [_compacta(v) for v in e["variantes"]]
    return any(k == x or x.startswith(k) for k in _juegos() if len(k) >= 3 for x in tuyos if x)


def _otro_juego(t_c: str, ents: list[dict]) -> str | None:
    """¿El título nombra un juego conocido que NO es lo que buscas? Solo si buscas un juego («GTA» no cuenta si buscas
    «GTA 6»: es parte de lo tuyo; si buscas un error de PlayStation, que salga GTA no es «otro juego»)."""
    if not any(_es_juego(e) for e in ents):
        return None
    tuyos = [_compacta(v) for e in ents for v in e["variantes"]]
    for k, nombre in _juegos().items():
        if len(k) < 3 or f"|{k}|" not in t_c:
            continue
        if any(k == x or x.startswith(k) or k.startswith(x) for x in tuyos if x):
            continue
        return nombre
    return None


def _dias(fecha: str) -> float | None:
    """«20261115» (YYYYMMDD) → días hasta hoy."""
    try:
        t = time.mktime(time.strptime(str(fecha)[:8], "%Y%m%d"))
    except (ValueError, OverflowError):
        return None
    return max(0.0, (time.time() - t) / 86400.0)


def _dhash(ruta: str) -> int | None:
    """Huella de 64 bits de la miniatura (dHash 9×8): dos miniaturas casi iguales difieren en pocos bits."""
    if not ruta or not os.path.isfile(ruta):
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.fromfile(ruta, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        p = cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA)
        bits = (p[:, 1:] > p[:, :-1]).flatten()
        return int("".join("1" if b else "0" for b in bits), 2)
    except Exception:  # noqa: BLE001
        return None


def _parecido_titulos(a: str, b: str) -> float:
    sa, sb = set(norm(a).split()), set(norm(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _clave_tema(ent: dict) -> str:
    ents = ent.get("entidades") or []
    return _compacta(ents[0]["nombre"]) if ents else ""


def _fmt_visitas(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1e6:.1f} M".replace(".", ",")
    if v >= 1000:
        return f"{v / 1e3:.0f} mil"
    return str(v)


def _quitar(texto_n: str, frases_n: list[str]) -> str:
    """El texto sin esas frases (para buscar «PS5» sin contar los «PS5 Pro»)."""
    t = f" {texto_n} "
    for f in frases_n:
        while f" {f} " in t:
            t = t.replace(f" {f} ", " | ")
    return t.strip()


def _clave_en(c: dict, t_n: str, t_c: str, todo_n: str, todo_c: str, desc_n: str, frase_n: str) -> tuple[str, str]:
    """¿Nombra esta clave EN SU SENTIDO? → («titulo» | «descripcion» | «» | «otro» | «fuera», la palabra que lo
    decide). «otro» = la usa en otro sentido («Plane Crash»); «fuera» = no es lo pedido («concept»)."""
    s = c.get("sentido") or {}
    formas = c["formas"]
    f_t, f_d = _en(t_n, t_c, formas), _en(todo_n, todo_c, formas)
    if not s:
        return ("titulo", f_t) if f_t else ("descripcion", f_d) if f_d else ("", "")
    rx_fuera = _rx(s.get("fuera") or "")
    if rx_fuera and not rx_fuera.search(frase_n):
        m = rx_fuera.search(t_n) or (rx_fuera.search(desc_n[:300]) if s.get("fuera_desc") else None)
        if m:
            return "fuera", m.group(0)
    if s.get("sin_juegos") and (f_t or f_d):                 # (el humo de una consola no sale en un juego)
        for k, nombre in _juegos().items():
            if len(k) >= 3 and f"|{k}|" in t_c and k not in _compacta(frase_n):
                return "fuera", nombre
    rx_si, rx_no = _rx(s.get("si") or ""), _rx(s.get("no") or "")
    t_lim = rx_no.sub(" | ", t_n) if rx_no else t_n          # (lo que queda fuera de las palabras del otro sentido)
    d_lim = rx_no.sub(" | ", todo_n) if rx_no else todo_n
    si_t = rx_si.search(t_lim) if rx_si else None
    si_d = rx_si.search(d_lim) if rx_si else None
    if rx_no and not si_t and (f_t or s.get("exige")):
        m = rx_no.search(t_n)
        if m:
            return "otro", m.group(0)
    if s.get("exige"):
        return ("titulo", si_t.group(0)) if si_t else ("descripcion", si_d.group(0)) if si_d else ("", "")
    if f_t or si_t:
        return "titulo", f_t or si_t.group(0)
    if f_d or si_d:
        return "descripcion", f_d or si_d.group(0)
    return "", ""


def puntuar(resultados: list[dict], ent: dict, sin_gente: bool = False, prefs: dict | None = None,
            ordenar: bool = True, modo: str = "descargas") -> list[dict]:
    """El orden: PRIMERO la relevancia («nivel» 0–4: la acción en su sentido × la entidad principal + las entidades),
    luego lo demás dentro de cada nivel. Cada resultado recibe «nivel», «puntos» (= nivel × NIVEL[modo] + el resto),
    «motivo» (por qué salió, para su tooltip) y, si es copia de otro, «resubida». Devuelve la lista ordenada de más
    a menos puntos (los mismos diccionarios).
    modo: «descargas» · «frases» (Material por frases: lo que se ve pesa más) · «imagenes» (imágenes libres)."""
    PESOS = dict(globals()["PESOS"], **MODOS.get(modo, {}))
    paso = NIVEL.get(modo, NIVEL["descargas"])
    ents = ent.get("entidades") or []
    claves = ent.get("claves") or []
    acciones = [c for c in claves if c.get("tipo") == "a"] or claves
    codigos = [e for e in ents if _RE_CODIGO.match(e["nombre"])]
    principal = (codigos or ents or [None])[0]               # (un código de error manda; si no, el tema)
    frase_n = norm(ent.get("frase") or "")
    # (una entidad dentro de otra que también buscas —«PS5» y «PS5 Pro»—: «PS5» se busca sin contar los «PS5 Pro»)
    largas = {}
    for e in ents:
        mias = {norm(v) for v in e["variantes"]}
        largas[id(e)] = [norm(v) for o in ents if o is not e for v in o["variantes"]
                         if any(f" {m} " in f" {norm(v)} " and m != norm(v) for m in mias)]
    prefs = preferencias() if prefs is None else prefs
    tema_prefs = (prefs.get("temas") or {}).get(_clave_tema(ent), {}) if prefs else {}
    penalizar_charla = (sin_gente or ent.get("sin_voz")) and not ent.get("pide_comentario")
    for r in resultados:
        titulo = r.get("title") or ""
        t_n = norm(titulo)
        desc_n = norm(str(r.get("description") or "")[:600])
        todo_n = norm(" ".join([titulo, str(r.get("description") or "")[:600], str(r.get("channel") or "")]))
        t_c, todo_c = _compactos(t_n), _compactos(todo_n)
        p, por = 0.0, []
        al_fondo = ""                                     # (por qué baja al fondo, si baja)
        # 1) entidades: 1 en el título · 0,5 solo en la descripción o el canal · 0 si no
        hit_e, s_e = [], {}
        for e in ents:
            formas = e["variantes"] + list(e.get("familia") or [])
            if largas[id(e)]:
                tn, dn = _quitar(t_n, largas[id(e)]), _quitar(todo_n, largas[id(e)])
                tc, dc = _compactos(tn), _compactos(dn)
            else:
                tn, dn, tc, dc = t_n, todo_n, t_c, todo_c
            s_e[id(e)] = 1.0 if _en(tn, tc, formas) else 0.5 if _en(dn, dc, formas) else 0.0
            if s_e[id(e)]:
                hit_e.append(e["nombre"])
                p += PESOS["titulo"] if s_e[id(e)] == 1.0 else 0.0
        if r.get("official") and principal is not None and s_e.get(id(principal)) == 1.0 and \
                any((c.get("sentido") or {}).get("oficial") for c in acciones):
            # (el tráiler OFICIAL de «GTA 6» es el de Jason y Lucía aunque su título no los nombre)
            s_e = {k: 1.0 for k in s_e}
        # (una empresa junto a su juego —«Rockstar» con «GTA 6»— es contexto: pesa la mitad)
        pesos_e = {id(e): 0.5 if len(ents) > 1 and _es_empresa(e["nombre"]) and e is not principal else 1.0
                   for e in ents}
        e_med = sum(s_e[k] * w for k, w in pesos_e.items()) / sum(pesos_e.values()) if ents else 1.0
        if ents:
            p += PESOS["entidad"] * e_med + (PESOS["todas"] if len(hit_e) == len(ents) else 0.0)
        pf = {1.0: 1.0, 0.5: 0.6}.get(s_e.get(id(principal), 0.0), 0.25) if principal is not None else 1.0
        # 2) claves, en su sentido
        hit_c, falta, s_c = [], [], {}
        for c in claves:
            donde, palabra = _clave_en(c, t_n, t_c, todo_n, todo_c, desc_n, frase_n)
            nom = c["en"] or c["es"]
            s_c[id(c)] = 1.0 if donde == "titulo" else 0.5 if donde == "descripcion" else 0.0
            if s_c[id(c)]:
                hit_c.append(nom)
            elif donde in ("otro", "fuera"):
                txt = (f"«{c['es']}» en otro sentido («{palabra}»)" if donde == "otro" else
                       f"no es lo pedido («{palabra}»)")
                if c in acciones:
                    al_fondo = al_fondo or txt
                else:
                    p += PESOS["otro_sentido"]
                    por.append(txt)
            elif c in acciones:
                falta.append(c["es"])
        if claves:
            p += PESOS["clave"] * sum(s_c.values()) / len(claves)
            if len(claves) > 1 and all(s_c.values()):         # (todas las claves: «humo» Y «ventilador»)
                p += PESOS["clave"] * 1.25
        a_s = [s_c[id(c)] for c in acciones]
        a = (max(a_s) + sum(a_s) / len(a_s)) if a_s else 2.0   # (0–2: la acción en el título = 2)
        nivel = 1.0 + a * pf + e_med
        if hit_e or hit_c:
            por.append("coincide: " + ", ".join(hit_e + hit_c))
        elif ents or claves:
            por.append("no nombra lo que buscas")
        if falta and (hit_e or hit_c):
            por.append("no dice: " + ", ".join(falta))
        sen = next((c["sentido"]["nombre"] for c in acciones if c.get("sentido") and s_c.get(id(c))), "")
        if sen:
            por.append(f"en el sentido «{sen}»")
        par = r.get("parecido")
        if isinstance(par, (int, float)):
            p += PESOS["clip"] * (float(par) - 0.2)
            por.append(f"parecido de la imagen {float(par):.2f}".replace(".", ","))
        dias = _dias(r.get("upload_date") or "")
        if dias is not None:
            if ent.get("actualidad"):                      # (solo desempata: la relevancia ya está en el nivel)
                p += PESOS["fecha"] * (1.0 if dias < 30 else 0.6 if dias < 180 else 0.2 if dias < 400 else -0.4)
            por.append("hoy" if dias < 1 else f"hace {int(dias)} días" if dias < 60 else
                       f"hace {int(dias / 30)} meses" if dias < 730 else f"hace {int(dias / 365)} años")
        if r.get("official"):                   # (un canal oficial ayuda si el video va de lo que buscas)
            mult = max([float((c.get("sentido") or {}).get("oficial") or 1.0) for c in acciones] or [1.0])
            p += PESOS["oficial"] * mult * (sum(s_c.values()) / len(claves) if claves else 1.0)
            por.append("canal oficial")
        v = int(r.get("views") or 0)
        if v > 0:
            p += PESOS["visitas"] * math.log10(1 + v)
            if r.get("fuente", "youtube") == "youtube" and v < 1000:     # (casi nadie lo vio: suele ser relleno)
                p -= PESOS["visitas"] * (PESOS["poca_vista"] if v < 100 else PESOS["poca_vista"] * 0.4)
                if v < 100 and paso:                     # (menos de 100: casi siempre relleno; baja un poco el nivel)
                    nivel -= 0.6 if v < 10 else 0.3
            por.append(f"{_fmt_visitas(v)} visitas")
        d = float(r.get("duration") or 0)
        if d:
            p += PESOS["duracion"] * (1.0 if 20 <= d <= 900 else -0.5 if d < 8 else -1.5 if d > 3600 else 0.0)
        if ent.get("sin_voz") and _SIN_VOZ_TITULO.search(t_n):
            p += PESOS["sin_voz"]
            por.append("sin comentarios")
        if penalizar_charla and es_comentario(titulo):
            p += PESOS["comentario"]
            al_fondo = al_fondo or "parece gente hablando (reacción u opinión)"
        otro = _otro_juego(t_c, ents)
        if otro:                                # (habla de OTRO juego: «Mortal Kombat… Smoke» no es lo tuyo)
            p += PESOS["otro_juego"]
            por.append(f"es de otro juego ({otro})")
        if not ent.get("pide_compilacion") and _RE_COMPILACION.search(t_n):
            p += PESOS["compilacion"]
            por.append("recopilación")
        canal = str(r.get("channel") or "")
        if canal and tema_prefs.get(canal):
            p += PESOS["pref"] * min(1.0, tema_prefs[canal] / 3.0)
            por.append("de un canal que ya usaste")
        if al_fondo:
            nivel = 0.0
            por.insert(0, al_fondo)
        nivel = max(0.0, nivel)
        r["nivel"] = round(nivel, 2)
        r["puntos"] = round(nivel * paso + p, 3)
        r["motivo"] = " · ".join(por)
        r.pop("resubida", None)
    _marcar_resubidas(resultados, PESOS["resubida"], paso)
    if ordenar:
        resultados.sort(key=lambda r: (-r["nivel"] if paso else 0.0, -r["puntos"]))
    return resultados


def _marcar_resubidas(resultados: list[dict], castigo: float = PESOS["resubida"], paso: float = 0.0) -> None:
    """Dos con el título casi igual (o la miniatura casi igual): se queda arriba la original (oficial o con más
    visitas); la otra baja al fondo (nivel 0) y su motivo lo dice."""
    huellas = {id(r): _dhash(r.get("thumb_local") or "") for r in resultados}
    orden = sorted(resultados, key=lambda r: (not r.get("official"), -int(r.get("views") or 0)))
    vistos: list[dict] = []
    for r in orden:
        h = huellas.get(id(r))
        copia = None
        for o in vistos:
            if (r.get("url") and r.get("url") == o.get("url")) or \
                    _parecido_titulos(r.get("title") or "", o.get("title") or "") >= 0.85:
                copia = o
                break
            ho = huellas.get(id(o))
            if h is not None and ho is not None and bin(h ^ ho).count("1") <= 5:
                copia = o
                break
        if copia is not None:
            r["puntos"] = round(r["puntos"] - float(r.get("nivel") or 0.0) * paso + castigo, 3)
            if "nivel" in r:
                r["nivel"] = 0.0
            r["resubida"] = copia.get("id") or copia.get("url")
            r["motivo"] = (r.get("motivo") + " · " if r.get("motivo") else "") + \
                f"parece una resubida de «{(copia.get('title') or '')[:50]}»"
        else:
            vistos.append(r)


# ---------------------------------------------------------------- parecido CLIP (para quien tenga miniaturas)
def parecidos_clip(items: list[dict], ent: dict, enc_texto=None, enc_imagen=None) -> int:
    """Pone «parecido» (coseno CLIP de la miniatura local «thumb_local» con la frase) en los que tengan miniatura.
    Devuelve cuántos midió (0 si CLIP no está disponible)."""
    from . import material_por_frases as M
    try:
        enc_texto, enc_imagen = M._encoders(enc_texto, enc_imagen)
        q = M._vector_texto(M.textos_clip(ent), enc_texto)
    except Exception:  # noqa: BLE001 - sin el modelo: el orden sigue sin la imagen
        return 0
    import numpy as np
    buenos, imgs = [], []
    for it in items:
        img = M.leer_imagen_224(it.get("thumb_local") or "")
        if img is not None:
            buenos.append(it)
            imgs.append(img)
    if not buenos:
        return 0
    vecs = enc_imagen.encode(np.stack(imgs))
    for it, v in zip(buenos, vecs):
        it["parecido"] = round(float(np.asarray(v, np.float32) @ q), 4)
    return len(buenos)


# ---------------------------------------------------------------- aprender de lo que eliges
ARCHIVO_PREFS = "buscador_preferencias.json"
_PREFS: dict = {}


def _ruta_prefs() -> str:
    from ..core.paths import app_data_dir
    return os.path.join(str(app_data_dir()), ARCHIVO_PREFS)


def preferencias() -> dict:
    """{"temas": {tema compacto: {canal: veces}}} (se lee una vez)."""
    if "datos" not in _PREFS:
        try:
            with open(_ruta_prefs(), encoding="utf-8") as f:
                _PREFS["datos"] = json.load(f)
        except (OSError, ValueError):
            _PREFS["datos"] = {"temas": {}}
    return _PREFS["datos"]


def aprender(item: dict, ent: dict | None) -> bool:
    """Lo que bajas o pones en la línea de tiempo: su canal sube un poco la próxima vez que busques el
    mismo tema. Pequeño: 30 canales por tema y 200 temas como mucho. Solo se guarda en este PC."""
    canal = str((item or {}).get("channel") or "").strip()
    tema = _clave_tema(ent or {})
    if not canal or not tema:
        return False
    datos = preferencias()
    temas = datos.setdefault("temas", {})
    t = temas.setdefault(tema, {})
    t[canal] = int(t.get(canal, 0)) + 1
    if len(t) > 30:
        for k in sorted(t, key=t.get)[:len(t) - 30]:
            t.pop(k, None)
    if len(temas) > 200:
        for k in list(temas)[:len(temas) - 200]:
            temas.pop(k, None)
    try:
        ruta = _ruta_prefs()
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(tmp, ruta)
    except OSError:
        return False
    return True
