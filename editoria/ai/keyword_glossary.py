"""Glosario de palabras clave de «Dijiste…»: lo que el usuario confirmó («si»), lo que marcó como «no es palabra
clave» («no») y la caché de consultas a internet («web»). Se guarda en datos de la app como JSON.

  load() / save(g)                       lectura y escritura (escritura atómica)
  add_yes(term, tipo=None)               confirma una palabra clave (con su tipo: juego, saga, consola…)
  add_no(term)                           «no es palabra clave» (quita la confirmación si la había)
  remove(term)                           olvida el término (de «si», «no» y «web»)
  is_no(term, g=None) / yes_terms(g=None)
  web_get(term, g=None, max_dias=None)   info de la caché (None si no está o es más antigua que max_dias)
  web_put(term, info, g=None)            guarda info en la caché (fecha de hoy)
  add_union(variantes, destino)          «Unir con…»: esas variantes cuentan como la palabra «destino» («unir»)
  add_separacion(dicho)                  «Separar…»: lo dicho así va aparte de su grupo («separar»)
  uniones(g=None) / separadas(g=None)

Las variantes («GTA V», «gta cinco», «Spider-Man», «spiderman») se comparan con keyword_folders.compacta, así que
«No es palabra clave» y «Es palabra clave» valen para todas.

Los parámetros «g» son el diccionario de load(); si se omiten se lee el archivo. Sin Qt.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import unicodedata
from pathlib import Path

from ..core.keyword_folders import compacta as _canon
from ..core.keyword_folders import junta as _junta
from ..core.keyword_folders import norm as _norm
from ..core.paths import app_data_dir

NOMBRE = "glosario_palabras_clave.json"
TIPOS = ("juego", "saga", "consola", "compañía", "persona", "otro")


def clave(texto: str) -> str:
    """Clave de comparación: sin tildes, en minúsculas, sin espacios sobrantes (como mentions._clave)."""
    s = unicodedata.normalize("NFKD", str(texto or "").lower().replace("’", "'"))
    return " ".join("".join(ch for ch in s if not unicodedata.combining(ch)).split())


def _ruta() -> Path:
    return app_data_dir() / NOMBRE


def _vacio() -> dict:
    return {"si": {}, "no": [], "web": {}, "unir": {}, "separar": []}


def load() -> dict:
    """El glosario tal como está en disco (o uno vacío si no existe o está dañado)."""
    try:
        with open(_ruta(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _vacio()
    if not isinstance(data, dict):
        return _vacio()
    g = _vacio()
    if isinstance(data.get("si"), dict):
        g["si"] = {k: v for k, v in data["si"].items() if isinstance(v, dict)}
    if isinstance(data.get("no"), list):
        g["no"] = [k for k in data["no"] if isinstance(k, str)]
    if isinstance(data.get("web"), dict):
        g["web"] = {k: v for k, v in data["web"].items() if isinstance(v, dict)}
    if isinstance(data.get("unir"), dict):
        g["unir"] = {str(k): str(v) for k, v in data["unir"].items() if isinstance(v, str) and v.strip()}
    if isinstance(data.get("separar"), list):
        g["separar"] = [k for k in data["separar"] if isinstance(k, str) and k]
    return g


def save(g: dict) -> None:
    """Escribe el glosario en un archivo temporal y lo cambia por el bueno (no queda a medias si se corta)."""
    ruta = _ruta()
    tmp = ruta.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, ruta)


def _hoy() -> str:
    return _dt.date.today().isoformat()


def add_yes(term: str, tipo: str | None = None) -> None:
    nombre = " ".join(str(term or "").split())
    k = clave(nombre)
    if not k:
        return
    g = load()
    entrada = {"nombre": nombre}
    if tipo:
        entrada["tipo"] = tipo
    g["si"][k] = entrada
    c = _canon(nombre)                    # (y ninguna variante suya en «no»: «GTA V» confirma también «gta 5»)
    g["no"] = [x for x in g["no"] if x != k and _canon(x) != c]
    save(g)


def add_no(term: str) -> None:
    k = clave(term)
    if not k:
        return
    g = load()
    g["si"].pop(k, None)
    c = _junta(term)                      # (ni variantes suyas en «si»; sin quitar el artículo: «no» a «Los
    for x in [x for x, v in g["si"].items() if _junta(v.get("nombre") or x) == c]:   # Ángeles» deja «Ángeles»)
        g["si"].pop(x, None)
    if k not in g["no"]:
        g["no"].append(k)
    save(g)


def remove(term: str) -> None:
    """Olvida el término: de «si», «no», «web» y también sus «Separar…» y «Unir con…» (en los dos sentidos)."""
    k = clave(term)
    g = load()
    g["si"].pop(k, None)
    g["no"] = [x for x in g["no"] if x != k]
    g["web"].pop(k, None)
    c = _canon(term)
    g["unir"] = {x: v for x, v in g.get("unir", {}).items() if x != c and _canon(v) != c}
    g["separar"] = [x for x in g.get("separar", []) if x != _norm(term)]
    save(g)


def add_union(variantes, destino: str) -> None:
    """«Unir con…»: cada variante (lo que se oyó, p. ej. un nombre mal transcrito) cuenta desde ahora como la palabra
    «destino». Se quitan de «Separar…» y una variante que ya iba a otro grupo cambia de grupo."""
    destino = " ".join(str(destino or "").split())
    cd = _canon(destino)
    if not cd:
        return
    g = load()
    unir = g.setdefault("unir", {})
    sep = set(g.get("separar", []))
    for v in [variantes] if isinstance(variantes, str) else list(variantes or ()):
        c = _canon(v)
        if not c or c == cd:
            continue
        unir[c] = destino
        sep.discard(_norm(v))
    for x in [x for x in unir if x == cd]:            # (el destino nunca apunta a otro: sin vueltas)
        unir.pop(x)
    g["separar"] = sorted(sep)
    save(g)


def add_separacion(dicho: str) -> None:
    """«Separar…»: lo dicho así («Fortnight», «gta cinco») deja de contar en su grupo y sale aparte. Si estaba unido
    a mano («Unir con…»), se deshace esa unión."""
    k = _norm(dicho)
    if not k:
        return
    g = load()
    c = _canon(dicho)
    g["unir"] = {x: v for x, v in g.get("unir", {}).items() if x != c}
    if k not in g.setdefault("separar", []):
        g["separar"].append(k)
    save(g)


def uniones(g: dict | None = None) -> dict:
    g = load() if g is None else g
    return dict(g.get("unir") or {})


def separadas(g: dict | None = None) -> list[str]:
    g = load() if g is None else g
    return list(g.get("separar") or [])


def is_no(term: str, g: dict | None = None, exacto: bool = False) -> bool:
    """¿Marcado «No es palabra clave»? También si lo está una variante suya («GTA V» ↔ «gta 5», «GTA cinco»).
    exacto=True (para una carpeta tuya): sin quitar el artículo, así «no» a «Los Ángeles» no es «no» a «Ángeles»."""
    g = load() if g is None else g
    if clave(term) in g["no"]:
        return True
    f = _junta if exacto else _canon
    c = f(term)
    return bool(c) and any(f(x) == c for x in g["no"])


def yes_terms(g: dict | None = None) -> list[str]:
    """Nombres a mostrar de las palabras clave confirmadas."""
    g = load() if g is None else g
    return [str(v.get("nombre") or k) for k, v in g["si"].items()]


def web_get(term: str, g: dict | None = None, max_dias: int | None = None) -> dict | None:
    g = load() if g is None else g
    info = g["web"].get(clave(term))
    if not info:
        return None
    if max_dias is not None:
        try:
            fecha = _dt.date.fromisoformat(str(info.get("fecha", "")))
        except ValueError:
            return None
        if (_dt.date.today() - fecha).days > max_dias:
            return None
    return dict(info)


def web_put(term: str, info: dict, g: dict | None = None) -> None:
    k = clave(term)
    if not k or not isinstance(info, dict):
        return
    if g is None:
        g = load()
    guardado = dict(info)
    guardado.setdefault("tipo", "ninguno")
    guardado["fecha"] = _hoy()
    g["web"][k] = guardado
    save(g)
