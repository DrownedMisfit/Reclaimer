"""
Variantes de una misma palabra clave (20/11, pedido del usuario: «que valga para cualquier tipo de palabra clave»).
Decide qué nombres dichos son LA MISMA palabra clave, para que «Dijiste…» los cuente en un solo grupo. Sin Qt.

  Variantes(conocidos, comun, unir, separar)
      conocidos  {nombre visible: prioridad} de los nombres conocidos (carpetas, glosario, la tabla de mentions)
      comun      función palabra → ¿es palabra corriente del diccionario? (exacta, sin plurales)
      unir       {clave compacta de una variante: nombre del grupo}  («Unir con…» del usuario)
      separar    {clave de lo dicho}                                  («Separar…» del usuario)
  .clave(nombre, dichos=(), sigla=False) -> str   clave del grupo («GTA cinco» y «gta5» → la misma)
  .nombre_de(clave) -> str | None                 nombre conocido de ese grupo (para enseñar «Fortnite», no «Fortnight»)
  fonetica(s) / distancia(a, b)                   ayudas (parecido sonoro y Levenshtein)

Qué se une:
  1. Lo de keyword_folders.compacta: tildes, mayúsculas, guiones, apóstrofos, «&»/«and»/«y», números en palabras
     (hasta 9999), romanos, letras pegadas al número, sin espacios («spiderman» = «Spider-Man»), artículo inicial.
  2. Singular/plural y grafías («zombi», «zombie», «zombis»), solo en palabras corrientes que no son parte de un
     nombre conocido.
  3. Siglas ↔ nombre completo («COD» ↔ «Call of Duty»): solo si la sigla (en MAYÚSCULAS, no corriente) coincide con
     las iniciales de UN nombre conocido; con dos candidatos, nada. Dos nombres conocidos (uno sigla del otro) son uno.
  4. Errores de Whisper («Fortnight» → «Fortnite»): parecido sonoro u ortográfico contra un nombre conocido, con
     umbral prudente (≥ 5–6 letras, misma primera letra) y nunca si lo dicho es una palabra corriente («Hola» no es
     «Halo»; «María» no es «Mario»; «Dome» no es «Doom»: palabras cortas solo por «Unir con…» o un alias de carpeta).
  5. Lo que el usuario decide manda: «Separar…» y «Unir con…» se guardan en el glosario.
Los números de entrega nunca se mezclan: «Halo 2» ≠ «Halo 3» y «Xbox Series X» ≠ «Xbox 10».
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..core.keyword_folders import canon, compacta, compactar

# Palabras de unión que no cuentan para una sigla («Call of Duty» → COD o CD).
_CONECTORES = {"of", "the", "de", "del", "la", "los", "las", "el", "y", "and", "a", "en", "on", "in", "to"}
# Siglas comunes del español y de los videojuegos (y palabras cortas en mayúsculas): nunca son la sigla de un nombre.
SIGLAS_COMUNES = set("""
no ya ok si la el lo de es en un una uno dos mas mal sol mes fin ver dar pan mar luz sur red top fan sal sed gol voz
paz rey ley mil oro ojo pie tu yo mi su te se le nos los las del al por con sin ni
dlc pc fps rpg ia ai tv cd dvd usb led hd uhd hdr vr ar pvp pve mmo npc ui hp xp qte rgb api sdk cpu gpu ram ssd
os ps eu ue usa onu fbi cia nba nfl ufc ceo aaa goty gg wtf omg irl afk diy tbh btw fyi etc pd ac dc am pm ko tnt
adn dni ong ovni pib iva sa sl bug lag mod dlcs rts moba mmorpg jrpg arpg fov hud lod dpi
""".split())


def sigla_valida(kb: str, comun=None) -> bool:
    """¿Puede «kb» (en MAYÚSCULAS al decirla) ser la sigla de un nombre? No si es una sigla común (DLC, PC, FPS, IA,
    TV…) o una palabra corriente de 4+ letras («GATO»)."""
    if kb in SIGLAS_COMUNES or not (2 <= len(kb) <= 6) or not kb.isalpha():
        return False
    return not (len(kb) >= 4 and comun is not None and comun(kb))


# Grafías (palabras corrientes escritas de dos formas) → una.
GRAFIAS = {"zombie": "zombi", "zombies": "zombi", "zombis": "zombi", "zoombie": "zombi",
           "videojuegos": "videojuego", "video juego": "videojuego", "bosses": "boss", "jefes": "jefe",
           "mods": "mod", "skins": "skin", "streamers": "streamer", "youtubers": "youtuber",
           "gamers": "gamer", "trailers": "trailer", "remakes": "remake", "remasters": "remaster"}


@lru_cache(maxsize=65536)
def fonetica(s: str) -> str:
    """Cómo suena (aprox., español e inglés) una clave compacta: «fortnight» y «fortnite» → «fortnit»."""
    s = s.replace("ight", "it").replace("ph", "f").replace("ck", "k").replace("qu", "k").replace("q", "k")
    s = s.replace("oo", "u").replace("ee", "i").replace("sh", "x").replace("ch", "x")
    s = re.sub(r"c(?=[eiy])", "s", s).replace("c", "k")
    s = s.replace("z", "s").replace("v", "b").replace("w", "u").replace("y", "i").replace("h", "")
    s = re.sub(r"(?<=[^aeiou])e$", "", s)           # e muda final del inglés («fortnite», «dome»)
    return re.sub(r"(.)\1+", r"\1", s)              # letras dobles


@lru_cache(maxsize=65536)
def distancia(a: str, b: str) -> int:
    """Levenshtein (sin dependencias: rapidfuzz y jellyfish no están en el .venv)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _base_y_numeros(palabras: list) -> tuple[list, list]:
    """«halo 2» → (["halo"], ["2"]): los números finales (la entrega) aparte; nunca se mezclan."""
    i = len(palabras)
    while i > 1 and palabras[i - 1].isdigit():
        i -= 1
    return palabras[:i], palabras[i:]


def _iniciales(palabras: list) -> set:
    letras = [w for w in palabras if w and w[0].isalpha()]
    out = set()
    if len(letras) >= 2:
        out.add("".join(w[0] for w in letras))
        sin = [w for w in letras if w not in _CONECTORES]
        if len(sin) >= 2:
            out.add("".join(w[0] for w in sin))
    return out


def _juntar(rep: str, nums: list) -> str:
    return rep + ("|" + " ".join(nums) if nums else "")


class Variantes:
    def __init__(self, conocidos=None, comun=None, unir=None, separar=None, singular=None):
        self._comun = comun or (lambda _w: False)
        self._singular_fn = singular          # palabra → su singular de verdad o None (mentions._singular_de)
        self.unir = {compacta(k) or k: str(v) for k, v in (unir or {}).items() if v}
        self.separar = set(separar or ())
        self._rep: dict = {}          # clave base compacta → representante
        self._nombre: dict = {}       # representante → nombre visible (el de más prioridad)
        self._prio: dict = {}
        self._palabras: set = set()   # palabras de nombres conocidos (no se les quita el plural)
        self._siglas: dict = {}       # iniciales → {representantes}
        self._fon: dict = {}          # primera letra fonética → [(fonética, base, representante)]
        self._cache: dict = {}
        nombres = dict(conocidos or {})
        for destino in self.unir.values():
            nombres.setdefault(destino, 1)
        bases: list = []
        for nombre, prio in nombres.items():
            ws = canon(nombre).split()
            if not ws:
                continue
            base, _nums = _base_y_numeros(ws)
            kb = compactar(base)
            if not kb:
                continue
            self._palabras.update(w for w in base if not self._comun(w) and w not in GRAFIAS)   # (nombres propios)
            rep = self._rep.setdefault(kb, kb)
            if prio > self._prio.get(rep, -1) or (prio == self._prio.get(rep) and len(nombre) < len(self._nombre[rep])):
                self._prio[rep] = prio
                self._nombre[rep] = " ".join(str(nombre).split()[:len(str(nombre).split()) - len(_nums)]) or nombre
            bases.append((base, kb, str(nombre)))
        for base, kb, _n in bases:                  # «Zombis» conocido: «zombi» y «zombie» también son él
            kb2 = compactar([self._singular(w) for w in base])
            if kb2 and kb2 != kb:
                self._rep.setdefault(kb2, self._rep[kb])
        # siglas conocidas ↔ nombres completos conocidos: un solo grupo (si no hay dos candidatos)
        for base, kb, _n in bases:
            for ini in _iniciales(base):
                self._siglas.setdefault(ini, set()).add(kb)
        for base, kb, nombre in bases:              # (la sigla, escrita en MAYÚSCULAS: «GTA», «COD»)
            if (len(base) == 1 and sigla_valida(kb, self._comun)
                    and nombre.split()[0].replace(".", "").isupper()):
                cands = {self._rep[x] for x in self._siglas.get(kb, ()) if self._rep[x] != self._rep[kb]}
                if len(cands) == 1:
                    destino = cands.pop()
                    viejo = self._rep[kb]
                    for k, r in list(self._rep.items()):
                        if r == viejo:
                            self._rep[k] = destino
                    if self._prio.get(viejo, -1) > self._prio.get(destino, -1):
                        self._prio[destino], self._nombre[destino] = self._prio[viejo], self._nombre[viejo]
        for _b, kb, _n in bases:
            if len(kb) >= 5:
                f = fonetica(kb)
                self._fon.setdefault(f[:1], []).append((f, kb, self._rep[kb]))

    # ------------------------------------------------------------------
    def nombre_de(self, clave: str) -> str | None:
        """Nombre conocido del grupo (con su número de entrega), o None si el grupo no es de un nombre conocido."""
        rep, _, nums = clave.partition("|")
        n = self._nombre.get(rep)
        if n is None:
            return None
        return f"{n} {nums}" if nums else n

    def es_separada(self, dicho: str) -> bool:
        return bool(self.separar) and _clave_dicho(dicho) in self.separar

    def _singular(self, w: str) -> str:
        if w in self._palabras or not w.isalpha():
            return w
        if w in GRAFIAS:
            return GRAFIAS[w]
        if self._singular_fn is not None:     # (con el diccionario: solo plurales de verdad, «dios» no es «dio»)
            r = self._singular_fn(w)
            return GRAFIAS.get(r, r) if r else w
        if len(w) > 4 and w.endswith("es") and self._comun(w[:-2]):
            return GRAFIAS.get(w[:-2], w[:-2])
        if len(w) > 3 and w.endswith("s") and self._comun(w[:-1]):
            return GRAFIAS.get(w[:-1], w[:-1])
        return w

    def _union_manual(self, nombre: str, dichos) -> str | None:
        if not self.unir:
            return None
        for x in (nombre, *dichos):
            d = self.unir.get(compacta(x))
            if d is not None:
                return d
        return None

    def clave(self, nombre: str, dichos=(), sigla: bool = False, validas=None) -> str:
        """Clave del grupo de «nombre». dichos: cómo se dijo (para «Unir con…»). sigla=True: se dijo en MAYÚSCULAS
        (puede ser la sigla de un nombre conocido). validas: representantes de los nombres que se dijeron enteros
        (o están en el glosario); si se da, una sigla solo vale para uno de ellos."""
        validas = frozenset(validas) if validas is not None else None
        ck = (nombre, tuple(dichos), sigla, validas)
        r = self._cache.get(ck)
        if r is None:
            destino = self._union_manual(nombre, dichos)
            if destino is not None and compacta(destino) != compacta(nombre):
                r = self._clave(destino, False)
            else:
                r = self._clave(nombre, sigla, validas)
            self._cache[ck] = r
        return r

    def _clave(self, nombre: str, sigla: bool, validas=None) -> str:
        ws = canon(nombre).split()
        if not ws:
            return ""
        base, nums = _base_y_numeros(ws)
        kb = compactar(base)
        if kb in self._rep:                                   # nombre conocido (o variante exacta suya)
            return _juntar(self._rep[kb], nums)
        base = [self._singular(w) for w in base]              # plural / grafía de palabras corrientes
        kb = compactar(base)
        if kb in self._rep:
            return _juntar(self._rep[kb], nums)
        todas_comunes = all(self._comun(w) or w in GRAFIAS.values() for w in base)
        if sigla and len(base) == 1 and sigla_valida(kb, self._comun):   # (en MAYÚSCULAS, no «DLC» ni «GATO»)
            cands = {self._rep[x] for x in self._siglas.get(kb, ())}
            if validas is not None:                           # (solo nombres dichos enteros o de tu glosario)
                cands &= validas
            if len(cands) == 1:                               # «COD» → «Call of Duty» (un solo candidato)
                return _juntar(cands.pop(), nums)
        if len(kb) >= 5 and not todas_comunes:
            rep = self._parecido(kb)
            if rep is not None:
                return _juntar(rep, nums)
        return _juntar(kb, nums)

    def _parecido(self, kb: str) -> str | None:
        """Un nombre conocido que SUENA igual o casi («fortnight» → fortnite); None si no hay o si hay dos."""
        f = fonetica(kb)
        mejores: dict = {}
        for fk, base, rep in self._fon.get(f[:1], ()):
            if abs(len(fk) - len(f)) > 2 or base[:1] != kb[:1]:
                continue
            corto = min(len(kb), len(base))
            if fk == f:
                d = 0
            else:
                d = min(distancia(f, fk), distancia(kb, base))
                if not ((d == 1 and corto >= 6) or (d == 2 and corto >= 10)
                        or (d == 2 and corto >= 8 and kb[-4:] == base[-4:])):   # («maincraft» → minecraft)
                    continue
            if d < mejores.get(rep, 99):
                mejores[rep] = d
        if not mejores:
            return None
        dmin = min(mejores.values())
        reps = [r for r, d in mejores.items() if d == dmin]
        return reps[0] if len(reps) == 1 else None


def _clave_dicho(texto: str) -> str:
    """Clave de lo dicho tal cual (para «Separar…»): minúsculas, sin tildes ni signos, espacios simples."""
    from ..core.keyword_folders import norm
    return norm(texto)


clave_dicho = _clave_dicho
iniciales = _iniciales
