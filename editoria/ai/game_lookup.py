"""¿Qué es un nombre? (juego, saga, consola, compañía, persona o nada) consultando internet, gratis y sin clave.

  classify(term, timeout=4) -> {"tipo", "titulo", "fuente"}  («tipo» = juego|saga|consola|compañía|persona|ninguno)
                              o None si no hay conexión o el servicio no responde.

Fuente principal: Wikidata (instance of, P31). Si Wikidata no responde, la descripción de Wikipedia (es, luego en).
Sin ventanas, sin Qt. Nunca lanza excepciones por red.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Reclaimer/1.0 (editor de video)"

# QID de «instance of» → tipo. El orden importa: una saga también puede ser «videojuego» en algún dato.
_P31 = [
    ("Q7058673", "saga"),        # serie de videojuegos
    ("Q7889", "juego"),          # videojuego
    ("Q8076", "consola"),        # consola de videojuegos
    ("Q17611", "consola"),       # consola doméstica
    ("Q210167", "compañía"),     # desarrolladora de videojuegos
    ("Q1137109", "compañía"),    # distribuidora de videojuegos
    ("Q4830453", "compañía"),    # empresa
    ("Q783794", "compañía"),     # empresa (compañía)
    ("Q5", "persona"),           # ser humano
]

# Palabras de la descripción de Wikipedia (es/en) → tipo. Se mira en este orden.
_DESCRIPCION = [
    ("saga", ("saga de videojuegos", "serie de videojuegos", "video game series", "franquicia")),
    ("juego", ("videojuego", "video game")),
    ("consola", ("consola", "console")),
    ("compañía", ("desarrolladora", "distribuidora", "compañía", "empresa", "company", "developer", "publisher")),
    ("persona", ("futbolista", "actor", "actriz", "músico", "cantante", "youtuber", "streamer", "singer", "footballer")),
]


def _pedir(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _wikidata(term: str, timeout: float):
    """(tipo, titulo) con Wikidata; ("ninguno", None) si no hay resultados; None si falla la red."""
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": term, "language": "es",
                                "uselang": "es", "limit": 3, "format": "json"})
    datos = _pedir("https://www.wikidata.org/w/api.php?" + q, timeout)
    res = (datos or {}).get("search") or []
    if not res:
        return "ninguno", None
    ids = [str(x.get("id")) for x in res[:3] if x.get("id")]
    q2 = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
                                 "format": "json"})
    ents = (_pedir("https://www.wikidata.org/w/api.php?" + q2, timeout) or {}).get("entities") or {}
    for x in res[:3]:
        eid = str(x.get("id"))
        titulo = x.get("label") or term
        claims = ((ents.get(eid) or {}).get("claims") or {}).get("P31") or []
        qids = set()
        for c in claims:
            try:
                qids.add(c["mainsnak"]["datavalue"]["value"]["id"])
            except (KeyError, TypeError):
                continue
        for qid, tipo in _P31:
            if qid in qids:
                return tipo, titulo
    return "ninguno", None


def _wikipedia(term: str, timeout: float):
    """(tipo, titulo) con la descripción de Wikipedia; ("ninguno", None) si no hay artículo claro."""
    for lang in ("es", "en"):
        titulo_url = urllib.parse.quote(term.strip().replace(" ", "_"), safe="")
        try:
            datos = _pedir(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{titulo_url}", timeout)
        except urllib.error.HTTPError:
            continue
        if not isinstance(datos, dict) or datos.get("type") == "disambiguation":
            continue
        desc = str(datos.get("description") or "").lower()
        if not desc:
            continue
        for tipo, palabras in _DESCRIPCION:
            if any(p in desc for p in palabras):
                return tipo, datos.get("title") or term
    return "ninguno", None


def classify(term: str, timeout: float = 4) -> dict | None:
    nombre = " ".join(str(term or "").split())
    if not nombre:
        return {"tipo": "ninguno", "titulo": None, "fuente": None}
    try:
        tipo, titulo = _wikidata(nombre, timeout)
        return {"tipo": tipo, "titulo": titulo, "fuente": "wikidata"}
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        pass
    try:
        tipo, titulo = _wikipedia(nombre, timeout)
        return {"tipo": tipo, "titulo": titulo, "fuente": "wikipedia"}
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return None
