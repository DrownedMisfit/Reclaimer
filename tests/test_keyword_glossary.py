"""
Prueba del glosario de palabras clave y de la consulta en internet de «Dijiste…» (sin ventanas, sin red salvo la
prueba real que se salta si no hay conexión):
  · «este», «eh», «bien», «pues», «mira»… con mayúscula al inicio de frase nunca salen;
  · un término en «no» desaparece;
  · un término en «si» sale como conocido aunque no esté en CONOCIDOS;
  · online=True con respuestas falsas: «Vive Coding» → ninguno (no se promueve); «Ruinas Eternas» → juego (conocido,
    guardado en caché; la segunda llamada no vuelve a consultar); persona no se promueve; sin conexión no revienta;
  · verify_online (segundo plano) promueve lo que resulte juego;
  · classify real: «Hollow Knight Silksong» → juego, «Nintendo» → compañía (se salta sin conexión).
Carpeta de datos temporal (EDITORIA_DATOS) dentro de _pruebas_tmp.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_keyword_glossary.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_glosario_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from editoria.ai import game_lookup  # noqa: E402
from editoria.ai import keyword_glossary as kg  # noqa: E402
from editoria.ai.mentions import find_mentions, verify_online  # noqa: E402
from editoria.core.model import Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def _frases(texto: str) -> list:
    """Palabras con 0,4 s cada una y 0,1 s entre ellas. «|» = pausa de 1 s (corta la extensión)."""
    out, t = [], 0.0
    for tok in texto.split():
        if tok == "|":
            t += 1.0
            continue
        out.append([round(t, 2), round(t + 0.4, 2), tok, 0.9])
        t += 0.5
    return out


def _proyecto(texto: str) -> Project:
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _frases(texto)}}
    return p


def _termino(res, term):
    return next((m for m in res if m["term"] == term), None)


def _reset():
    ruta = kg._ruta()
    if ruta.exists():
        ruta.unlink()


_FALSO = {}           # nombre en clave → respuesta de classify falsa
_LLAMADAS = []        # nombres consultados


def _classify_falso(term, timeout=4):
    _LLAMADAS.append(term)
    return _FALSO.get(kg.clave(term), {"tipo": "ninguno", "titulo": None, "fuente": "falso"})


def test_muletillas():
    _reset()
    texto = ("Este video es bueno. Eh, bien, pues vamos. Mira esto. Hola a todos. Bien. Pues. "
             "Este capítulo trata de algo. Ehm, mmm, o sea, digamos que sí. Vale, entonces seguimos. "
             "Sobre todo la verdad es que jugamos Fortnite hoy. Por cierto, Fortnite otra vez.")
    res = find_mentions(_proyecto(texto), glossary=kg.load())
    terminos = {m["term"].lower() for m in res}
    for mal in ("este", "eh", "bien", "pues", "mira", "esto", "hola", "vale", "entonces", "ehm", "mmm",
                "sobre", "todo", "digamos", "por", "cierto", "vamos", "o", "sí", "si"):
        check(mal not in terminos, f"«{mal}» no sale como palabra clave")
    check("fortnite" in terminos, "Fortnite sigue saliendo (es juego conocido)")


def test_no_y_si():
    _reset()
    texto = "Hoy jugamos Vive Coding con los amigos. Vive Coding es divertido. Lo recomiendo mucho."
    antes = find_mentions(_proyecto(texto))
    check(_termino(antes, "Vive Coding") is not None, "sin glosario «Vive Coding» sale como nombre propio")
    kg.add_no("Vive Coding")
    despues = find_mentions(_proyecto(texto), glossary=kg.load())
    check(_termino(despues, "Vive Coding") is None, "marcado «no es palabra clave» → desaparece")
    check(kg.is_no("vive coding") and kg.is_no("VIVE CODING"), "is_no ignora mayúsculas y tildes")

    texto2 = "Lo que más nos gustó fue Lumen Quest de principio a fin. Lumen Quest es corto."
    sin = _termino(find_mentions(_proyecto(texto2)), "Lumen Quest")
    check(sin is not None and sin["known"] is False, "sin glosario «Lumen Quest» es nombre propio (no conocido)")
    kg.add_yes("Lumen Quest", "juego")
    con = _termino(find_mentions(_proyecto(texto2), glossary=kg.load()), "Lumen Quest")
    check(con is not None and con["known"] is True, "confirmado «si» → sale como conocido")
    check("Lumen Quest" in kg.yes_terms(), "yes_terms() lista el término confirmado")
    kg.remove("Lumen Quest")
    check("Lumen Quest" not in kg.yes_terms(), "remove() lo olvida")


def test_online():
    _reset()
    _FALSO.clear()
    _FALSO["ruinas eternas"] = {"tipo": "juego", "titulo": "Ruinas Eternas", "fuente": "falso"}
    _FALSO["vive coding"] = {"tipo": "ninguno", "titulo": None, "fuente": "falso"}
    _FALSO["ana perez"] = {"tipo": "persona", "titulo": "Ana Pérez", "fuente": "falso"}
    texto = ("Ayer probamos Ruinas Eternas en directo. Ruinas Eternas tiene buena pinta. "
             "Vive Coding también salió. Y Ana Pérez habló de todo. Ana Pérez es famosa.")
    _LLAMADAS.clear()
    orig = game_lookup.classify
    game_lookup.classify = _classify_falso
    try:
        g = kg.load()
        res = find_mentions(_proyecto(texto), glossary=g, online=True)
        r = _termino(res, "Ruinas Eternas")
        check(r is not None and r["known"] is True and r.get("web") == "juego",
              "online: «Ruinas Eternas» → juego (conocido, web=juego)")
        v = _termino(res, "Vive Coding")
        check(v is not None and v["known"] is False and v.get("web") == "ninguno",
              "online: «Vive Coding» → ninguno (no se promueve)")
        a = _termino(res, "Ana Pérez")
        check(a is not None and a["known"] is False and a.get("web") == "persona",
              "online: persona no se promueve pero queda marcada")
        check(len(_LLAMADAS) == 3, f"online: 3 consultas en la primera llamada (hay {len(_LLAMADAS)})")
        check(kg.web_get("Ruinas Eternas") is not None, "la respuesta queda en la caché del glosario")

        n = len(_LLAMADAS)
        res2 = find_mentions(_proyecto(texto), glossary=kg.load(), online=True)
        check(len(_LLAMADAS) == n, "segunda llamada: no vuelve a consultar (caché)")
        check(_termino(res2, "Ruinas Eternas")["known"] is True, "segunda llamada: sigue conocido")

        # verify_online en segundo plano sobre un resultado sin consultas
        _reset()
        base = find_mentions(_proyecto("Hoy probamos Nebula Pantano en casa. Nebula Pantano es nuevo."),
                             glossary=kg.load())
        check(_termino(base, "Nebula Pantano")["known"] is False, "antes de verify_online: no conocido")
        _FALSO["nebula pantano"] = {"tipo": "juego", "titulo": "Nebula Pantano", "fuente": "falso"}
        n = len(_LLAMADAS)
        ver = verify_online(base, kg.load())
        check(_termino(ver, "Nebula Pantano")["known"] is True, "verify_online promueve a juego")
        check(len(_LLAMADAS) == n + 1, "verify_online: una consulta")
        check(_termino(base, "Nebula Pantano")["known"] is False, "verify_online no modifica la lista de entrada")

        # sin conexión: no revienta y no inventa nada
        def _sin_red(term, timeout=4):
            return None
        game_lookup.classify = _sin_red
        _reset()
        sin = find_mentions(_proyecto("Hoy probamos Mundo Perdido en casa. Mundo Perdido es nuevo."),
                            glossary=kg.load(), online=True)
        check(_termino(sin, "Mundo Perdido") is not None and _termino(sin, "Mundo Perdido")["known"] is False,
              "sin conexión: no revienta y el nombre sigue sin conocer")
    finally:
        game_lookup.classify = orig


def test_real():
    _reset()
    a = game_lookup.classify("Hollow Knight Silksong", timeout=6)
    if a is None:
        print("- prueba de red omitida (sin conexión)")
        return
    check(a["tipo"] == "juego", f"red: «Hollow Knight Silksong» → juego (hay {a['tipo']})")
    b = game_lookup.classify("Nintendo", timeout=6)
    if b is None:
        print("- prueba de red de «Nintendo» omitida (sin conexión)")
        return
    check(b["tipo"] == "compañía", f"red: «Nintendo» → compañía (hay {b['tipo']})")


def main():
    test_muletillas()
    test_no_y_si()
    test_online()
    test_real()
    print("TODO OK")


if __name__ == "__main__":
    main()
