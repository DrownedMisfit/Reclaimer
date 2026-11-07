"""
Prueba de nombres compuestos en «Dijiste…» (find_mentions), sin ventanas:
  · GTA seis / GTA VI / G.T.A. 6 / gta 6 / GTA Six → «GTA 6» (3 apariciones en la prueba);
  · subtítulos: «Zelda ocarina of time» → «Zelda Ocarina of Time», «The Legend of Zelda Breath of the Wild»
    → «Zelda Breath of the Wild», y un «Zelda» suelto en otra frase sigue siendo «Zelda»;
  · números romanos y en palabras tras un nombre: «Resident Evil cuatro» → «Resident Evil 4»,
    «Final Fantasy VII» → «Final Fantasy 7»;
  · «uno de los mejores» no produce ningún número ni mención;
  · una pausa larga corta la extensión; «Minecraft y Fortnite» son dos menciones.
Sin ventanas visibles. Ejecutar:  .venv/Scripts/python.exe tests/test_mentions_names.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from editoria.ai.mentions import find_mentions  # noqa: E402
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


def main():
    texto = ("Yo creo que el GTA seis va a salir este año. Ojalá GTA VI llegue pronto. "
             "Y el G.T.A. 6 promete mucho. "
             "Me encantó Zelda ocarina of time de niño. "
             "The Legend of Zelda Breath of the Wild es enorme. "
             "Zelda es mi saga favorita. "
             "Resident Evil cuatro me dio miedo. "
             "Final Fantasy VII es un clásico. "
             "Uno de los mejores juegos es Tekken. "
             "Minecraft y Fortnite son distintos. "
             "GTA | 6 con pausa no cuenta. "
             "Call of Duty Black Ops 6 salió ayer. "
             "Hollow Knight Silksong es difícil. "
             "Doom The Dark Ages es brutal. "
             "Xbox Series X es potente.")
    res = find_mentions(_proyecto(texto))
    terminos = [m["term"] for m in res]
    print("menciones:", terminos)

    gta = _termino(res, "GTA 6")
    check(gta is not None and gta["count"] == 3, "«GTA seis», «GTA VI» y «G.T.A. 6» son «GTA 6» con 3 apariciones")
    check(_termino(res, "GTA") is not None and _termino(res, "GTA")["count"] == 1,
          "«GTA | 6» con pausa: «GTA» suelto (1 aparición), sin extender")

    check(_termino(res, "Zelda Ocarina of Time") is not None, "«Zelda ocarina of time» → «Zelda Ocarina of Time»")
    check(_termino(res, "Zelda Breath of the Wild") is not None,
          "«The Legend of Zelda Breath of the Wild» → «Zelda Breath of the Wild»")
    zs = _termino(res, "Zelda")
    check(zs is not None and zs["count"] == 1, "«Zelda» suelto en otra frase sigue siendo «Zelda» (1 aparición)")

    check(_termino(res, "Resident Evil 4") is not None, "«Resident Evil cuatro» → «Resident Evil 4»")
    check(_termino(res, "Final Fantasy 7") is not None, "«Final Fantasy VII» → «Final Fantasy 7»")
    check(_termino(res, "Call of Duty Black Ops 6") is not None, "«Call of Duty Black Ops 6» completo")
    check(_termino(res, "Hollow Knight Silksong") is not None, "«Hollow Knight Silksong» completo")
    check(_termino(res, "Doom The Dark Ages") is not None, "«Doom The Dark Ages» completo")
    check(_termino(res, "Xbox Series X") is not None, "«Xbox Series X»: la X no pasa a 10")
    check(_termino(res, "Minecraft") is not None and _termino(res, "Fortnite") is not None,
          "«Minecraft y Fortnite» son dos menciones separadas")

    check(not any(t.lower() in ("uno", "1") or t.startswith("1") or "uno" in t.lower() for t in terminos),
          "«uno de los mejores» no produce ningún número ni mención")

    # Las antiguas: un nombre repetido cuenta como antes y el orden es el mismo
    viejo = find_mentions(_proyecto("Hoy vamos a jugar con zombis. Luego Fortnite y Fortnite otra vez."))
    f = _termino(viejo, "Fortnite")
    check(f is not None and f["count"] == 2 and f["known"], "Fortnite ×2 sigue como conocido")
    check(find_mentions(Project.new()) == [], "sin transcripciones: lista vacía")

    # Frases reales de un video del usuario (07/11): «Con» al empezar la frase no se pega a «GTA V»; el subtítulo
    # dicho solo es su juego; «Series S, X y S.» no inventa una sigla
    real = find_mentions(_proyecto("Y mira. Con GTA V esperamos casi dos años. El caso de Zelda. | El remake de "
                                   "Ocarina of Time vuelve. | PlayStation 5 y Xbox Series | S, X y S."))
    nombres = [m["term"] for m in real]
    check(_termino(real, "GTA 5") is not None and not any(n.startswith("Con ") for n in nombres),
          f"«Con GTA V» → «GTA 5» (sin el «Con»): {nombres}")
    check(_termino(real, "Zelda Ocarina of Time") is not None and "Ocarina" not in nombres and "Time" not in nombres,
          f"«el remake de Ocarina of Time» → «Zelda Ocarina of Time»: {nombres}")
    check(not any("XyS" in n.replace(" ", "") for n in nombres), f"«S, X y S.» no inventa una sigla: {nombres}")

    print("TODO OK")


if __name__ == "__main__":
    main()
