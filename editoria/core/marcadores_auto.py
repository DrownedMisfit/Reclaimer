"""
📍 MARCADORES AUTOMÁTICOS (fase 5): todo lo que hay que revisar, en UNA capa sobre la línea de tiempo y un índice.

No crea marcadores nuevos ni repite avisos: LEE lo que ya existe y lo junta, cada cosa una sola vez.
  · tomas repetidas, muletillas y palabras repetidas → las propuestas pendientes de la limpieza de voz, con el MISMO
    filtro que la Revisión guiada (pendientes, que se pueden cortar, no tachadas a mano: pendientes());
    los silencios y ruidos no (ya salen en Limpieza y serían cientos);
  · cortes dudosos → las líneas rojas de «Cortes de audio» (si caen encima de una propuesta, sale solo la propuesta);
  · marcas de OBS (marcadores rojos), temas de la narración y tus marcadores (con su nota);
  · huecos sin imagen (hay voz o música y ningún video encima) y material repetido (fase 4).
Lo que das por revisado no vuelve a salir: una propuesta rechazada, un corte «está bien así» (cut_ok), un marcador
«resuelto» o, para huecos y material repetido, su clave en project.review_ok.

  TIPOS                                  tipo -> (nombre, color)
  capa(project, cut_issues, repetidos)   -> [Marca] en el orden del video
  contar(marcas) -> {tipo: n}
  siguiente(marcas, t, paso, tipos)      -> Marca | None   (Mayús+↑ / Mayús+↓)
  grupos_tomas(project) -> [grupo]       las tomas repetidas agrupadas (con 3 o más tomas, varias propuestas)
  tomas_viejas(project) -> [ids]         las propuestas de toma repetida pendientes (en la línea de tiempo)
  quitar_tomas_viejas(ctrl) -> str       quita todas las tomas de cada grupo menos la última, un Ctrl+Z
  dar_por_revisada(ctrl, marca) -> str   «está bien así» (cada fuente con su propio estado), un Ctrl+Z
  marcador_en(project, t, fps) -> Marker | None   el marcador puntual en ese instante (para M+M)
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

TIPOS: dict[str, tuple[str, str]] = {
    "toma": ("Tomas repetidas", "#f08c3a"),
    "muletilla": ("Muletillas y repeticiones", "#d6b84a"),
    "duda": ("Cortes dudosos", "#c75bd6"),
    "obs": ("Marcas de OBS", "#e5484d"),
    "tema": ("Temas", "#4f9cf0"),
    "hueco": ("Huecos sin imagen", "#8a8f98"),
    "repetido": ("Material repetido", "#e8b040"),
    "marcador": ("Mis marcadores", "#f2b33d"),
}
TIPO_DE_PROPUESTA = {"retake": "toma", "filler": "muletilla", "repeat": "muletilla"}
NOMBRE_PROPUESTA = {"retake": "Toma repetida", "filler": "Muletilla", "repeat": "Palabra repetida"}
COLOR_OBS = "#e5484d"            # (ui/obs_marks_ui.MARK_COLOR: las marcas de OBS son marcadores rojos)
HUECO_MIN = 1.0                  # s: un hueco sin imagen más corto no se avisa
JUNTO = 0.3                      # s: un corte dudoso a menos de esto de una propuesta es el mismo sitio


@dataclass
class Marca:
    t: float
    fin: float | None
    tipo: str
    texto: str
    ref: str                     # id de la propuesta · clave del corte · id del marcador · id del clip · «a-b»

    @property
    def clave(self) -> str:
        """La clave de «está bien así» en project.review_ok (huecos y material repetido)."""
        return f"marca|{self.tipo}|{self.ref}"


def _mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}".replace(".", ",")


# ------------------------------------------------------------------ dónde está cada cosa (rápido)
class _EnLinea:
    """Dónde sale en la línea de tiempo un tramo de un archivo, sin recorrer todos sus clips en cada consulta: los clips
    de cada archivo, ordenados por su inicio en el archivo, con el final más lejano acumulado (bisect + unos pocos)."""

    def __init__(self, p):
        self.p = p
        self._por: dict = {}

    def _de(self, mid: str):
        got = self._por.get(mid)
        if got is None:
            cl = sorted((c for c in self.p.clips.values() if c.media_id == mid and c.speed > 0),
                        key=lambda c: c.source_in)
            ini = [float(c.source_in) for c in cl]
            lejos, m = [], -1e18
            for c in cl:
                m = max(m, float(c.source_in) + float(c.src_len))
                lejos.append(m)
            got = self._por[mid] = (cl, ini, lejos)
        return got

    def tramo(self, mid: str, a: float, b: float) -> tuple[float, float] | None:
        from .mapping import TOL, _when
        cl, ini, lejos = self._de(mid)
        k = bisect.bisect_left(ini, b - TOL) - 1
        t0, t1 = None, None
        while k >= 0 and lejos[k] > a + TOL:
            c = cl[k]
            sa, sb = max(a, c.source_in), min(b, c.source_in + c.src_len)
            if sb - sa > TOL:
                x, y = _when(c, sa), _when(c, sb)
                lo, hi = min(x, y), max(x, y)
                t0 = lo if t0 is None else min(t0, lo)
                t1 = hi if t1 is None else max(t1, hi)
            k -= 1
        return None if t0 is None else (t0, t1)


class _Palabras:
    """Lo dicho en un tramo de un archivo (bisect sobre los inicios de las palabras, una vez por archivo)."""

    def __init__(self, p):
        self.p = p
        self._por: dict = {}

    def dicho(self, mid: str, a: float, b: float, n: int = 8) -> str:
        got = self._por.get(mid)
        if got is None:
            ws = (self.p.transcripts.get(mid) or {}).get("words") or []
            got = self._por[mid] = (ws, [float(w[0]) for w in ws])
        ws, ini = got
        k = max(0, bisect.bisect_left(ini, a - 30.0))      # (ninguna palabra dura 30 s)
        dentro = []
        while k < len(ws) and ini[k] < b - 0.03:
            if float(ws[k][1]) > a + 0.03:
                dentro.append(str(ws[k][2]))
            k += 1
        txt = " ".join(dentro[:n]) + (" …" if len(dentro) > n else "")
        return f"«{txt}»" if txt else ""


def pendientes(p) -> list:
    """Las propuestas de toma, muletilla o palabra repetida que aún se pueden decidir (el mismo filtro que la Revisión
    guiada: pendientes, que se pueden cortar, no tachadas a mano)."""
    from .model import SUG_PENDING
    return [s for s in p.suggestions if s.status == SUG_PENDING and s.cuttable and s.kind in TIPO_DE_PROPUESTA]


def _clave_toma(a: float, b: float) -> tuple:
    return (round(float(a), 2), round(float(b), 2))


def grupos_tomas(p, sugs=None) -> list[dict]:
    """Las tomas repetidas pendientes, AGRUPADAS: la IA propone una pareja (toma, la mejor) por cada toma que sobra, así
    que con 3 tomas hay 2 propuestas que comparten la mejor. Cada grupo: {"tomas": [(a, b)] en orden, "sugs": [...]}."""
    sugs = [s for s in (pendientes(p) if sugs is None else sugs) if s.kind == "retake"]
    padre: dict = {}

    def raiz(k):
        while padre.setdefault(k, k) != k:
            padre[k] = padre[padre[k]]
            k = padre[k]
        return k
    for s in sugs:
        k1 = _clave_toma(s.start, s.end)
        raiz(k1)
        if s.alt_start is not None and s.alt_end is not None:
            k2 = _clave_toma(s.alt_start, s.alt_end)
            padre[raiz(k2)] = raiz(k1)
    grupos: dict = {}
    for s in sugs:
        g = grupos.setdefault((s.media_id, raiz(_clave_toma(s.start, s.end))), {"tomas": set(), "sugs": []})
        g["sugs"].append(s)
        g["tomas"].add((float(s.start), float(s.end)))
        if s.alt_start is not None and s.alt_end is not None:
            g["tomas"].add((float(s.alt_start), float(s.alt_end)))
    out = []
    for g in grupos.values():
        tomas = sorted({_clave_toma(a, b): (a, b) for a, b in g["tomas"]}.values())
        out.append({"tomas": tomas, "sugs": g["sugs"], "media_id": g["sugs"][0].media_id})
    return out


def _plan_tomas(grupo: dict) -> dict[str, bool]:
    """{id de propuesta: keep_first} para quitar TODAS las tomas del grupo menos la última que se dijo (cada propuesta
    quita una distinta: con 3 tomas y la mejor la 1.ª, la 1.ª y la 2.ª; nunca la 1.ª dos veces)."""
    ultima = _clave_toma(*grupo["tomas"][-1])
    quitar = {_clave_toma(a, b) for a, b in grupo["tomas"][:-1]}
    opciones: dict[str, list] = {}
    for s in grupo["sugs"]:
        r1 = _clave_toma(s.start, s.end)
        r2 = _clave_toma(s.alt_start, s.alt_end) if s.alt_start is not None else None
        opciones[s.id] = [(r, kf) for r, kf in ((r1, False), (r2, True)) if r is not None and r != ultima and r in quitar]
    hechas: set = set()
    plan: dict[str, bool] = {}
    # (primero la propuesta con MENOS tomas posibles: con 3 tomas y la mejor la 1.ª, la pareja (1.ª, 3.ª) solo puede
    #  quitar la 1.ª; así la (1.ª, 2.ª) quita la 2.ª y no se quita la 1.ª dos veces)
    while len(plan) < len(opciones):
        sid, libres = min(((k, [o for o in v if o[0] not in hechas]) for k, v in opciones.items() if k not in plan),
                          key=lambda x: (len(x[1]) if x[1] else 99, x[0]))
        elegido = (libres or opciones[sid] or [None])[0]
        if elegido is None:
            plan[sid] = None                          # (no quita ninguna: se descarta abajo)
            continue
        hechas.add(elegido[0])
        plan[sid] = elegido[1]
    return {k: v for k, v in plan.items() if v is not None}


def capa(project, cut_issues=(), repetidos=None, huecos: bool = True) -> list[Marca]:
    """Todas las marcas, cada sitio una vez, en el orden del video. repetidos = {clip_id: [...]} (core/repetidos.mapa)
    o None para no mirarlos. ~10–30 ms con 1 h de proyecto (cada tramo se busca con bisect, no recorriendo todo)."""
    p = project
    ok = set(p.review_ok)
    out: list[Marca] = []
    linea, palabras = _EnLinea(p), _Palabras(p)
    tramos_sug: list[tuple[float, float]] = []
    pend = pendientes(p)
    # tomas: una marca por cada toma que sobra (todas menos la última de su grupo), con todas sus propuestas
    for g in grupos_tomas(p, pend):
        for a, b in g["tomas"][:-1]:
            k = _clave_toma(a, b)
            refs = [s.id for s in g["sugs"] if k in (_clave_toma(s.start, s.end),
                                                      _clave_toma(s.alt_start, s.alt_end) if s.alt_start is not None
                                                      else None)]
            span = linea.tramo(g["media_id"], a, b)
            if span is None or not refs:
                continue
            tramos_sug.append(span)
            n = len(g["tomas"])
            out.append(Marca(float(span[0]), float(span[1]), "toma",
                             f"Toma repetida{f' ({n} tomas)' if n > 2 else ''} {palabras.dicho(g['media_id'], a, b)}"
                             .strip(), ",".join(refs)))
    for s in pend:
        if s.kind == "retake":
            continue
        span = linea.tramo(s.media_id, s.start, s.end)
        if span is None:
            continue
        tramos_sug.append(span)
        out.append(Marca(float(span[0]), float(span[1]), "muletilla",
                         f"{NOMBRE_PROPUESTA[s.kind]} {palabras.dicho(s.media_id, s.start, s.end)}".strip(), s.id))
    tramos_sug.sort()
    inicios = [a for a, _b in tramos_sug]
    cut_ok = set(getattr(p, "cut_ok", []) or [])
    for c in cut_issues or []:                          # (encima de una propuesta: sale solo la propuesta)
        if c.get("key") in cut_ok:
            continue
        t = float(c["t"])
        k = bisect.bisect_right(inicios, t + JUNTO)
        if any(a - JUNTO <= t <= b + JUNTO for a, b in tramos_sug[max(0, k - 3):k]):
            continue
        razones = "; ".join(c.get("reasons") or [])
        out.append(Marca(t, None, "duda", "Corte de audio que puede estar mal" + (f": {razones}" if razones else ""),
                         c["key"]))
    for m in p.markers:
        if getattr(m, "resuelto", False):
            continue
        if m.kind == "topic":
            out.append(Marca(float(m.time), m.end, "tema", f"Tema: {m.label}".strip(), m.id))
        elif (m.color or "").lower() == COLOR_OBS:
            out.append(Marca(float(m.time), m.end, "obs", f"Marca de OBS: {m.label}".strip(), m.id))
        else:
            nota = (getattr(m, "note", "") or "").strip()
            out.append(Marca(float(m.time), m.end, "marcador", (m.label or "Marcador") + (f" — {nota}" if nota else ""),
                             m.id))
    if huecos:
        from . import autocompletar as AC
        from .model import TRACK_VIDEO
        vids = {t.id for t in p.tracks if t.kind == TRACK_VIDEO}
        visibles = [c for c in p.clips.values() if c.track_id in vids and c.enabled and c.text is None]
        if visibles:                                   # (sin ningún video, todo sería hueco)
            fines = sorted((c.end, c.id) for c in visibles)
            inis = sorted((c.start, c.id) for c in visibles)
            for a, b in AC.huecos(p, min_len=HUECO_MIN):
                mk = Marca(float(a), float(b), "hueco", f"Hueco sin imagen ({b - a:.1f} s)".replace(".", ","),
                           _clave_hueco(a, b, fines, inis))
                if mk.clave not in ok:
                    out.append(mk)
    if repetidos:
        for cid in repetidos:
            c = p.clips.get(cid)
            m = p.media.get(c.media_id) if c is not None else None
            if c is None or m is None or not repetidos[cid]:
                continue
            mk = Marca(float(c.start), float(c.end), "repetido", f"Material repetido: «{m.name}»", cid)
            if mk.clave not in ok:
                out.append(mk)
    out.sort(key=lambda x: (x.t, x.tipo))
    return out


def _clave_hueco(a: float, b: float, fines: list, inis: list) -> str:
    """Clave estable de un hueco: los clips de video que lo cierran por cada lado (si se mueve todo unas centésimas,
    sigue siendo el mismo hueco). Sin clip a un lado, el inicio o el final de la voz (al medio segundo)."""
    k = bisect.bisect_left(fines, (a - 0.05, ""))
    izq = next((cid for t, cid in fines[k:k + 4] if abs(t - a) <= 0.05), None)
    k = bisect.bisect_left(inis, (b - 0.05, ""))
    der = next((cid for t, cid in inis[k:k + 4] if abs(t - b) <= 0.05), None)
    return f"{izq or f'v{round(a * 2) / 2:g}'}~{der or f'v{round(b * 2) / 2:g}'}"


def contar(marcas: list[Marca]) -> dict[str, int]:
    n = {k: 0 for k in TIPOS}
    for m in marcas:
        n[m.tipo] = n.get(m.tipo, 0) + 1
    return n


def siguiente(marcas: list[Marca], t: float, paso: int, tipos=None, tol: float = 1e-3) -> Marca | None:
    """La marca siguiente (paso > 0) o anterior (paso < 0) al instante t, de los tipos dados (None = todos)."""
    lst = [m for m in marcas if tipos is None or m.tipo in tipos]
    if paso > 0:
        return next((m for m in lst if m.t > t + tol), None)
    return next((m for m in reversed(lst) if m.t < t - tol), None)


def tomas_viejas(project) -> list[str]:
    """Las propuestas de toma repetida pendientes que se pueden quitar (las que están en la línea de tiempo: las de un
    tramo que ya no está no encienden el botón)."""
    linea = _EnLinea(project)
    return [s.id for s in pendientes(project) if s.kind == "retake" and linea.tramo(s.media_id, s.start, s.end)]


def quitar_tomas_viejas(ctrl) -> str:
    """De cada grupo de tomas repetidas se quitan TODAS menos la última que dijiste (aunque la IA prefiriera otra: es
    lo que pide el botón). Todo en un Ctrl+Z, en todas las pistas (apply_suggestions)."""
    p = ctrl.project
    vivas = set(tomas_viejas(p))
    plan: dict[str, bool] = {}
    for g in grupos_tomas(p):
        if any(s.id in vivas for s in g["sugs"]):
            plan.update(_plan_tomas(g))
    plan = {k: v for k, v in plan.items() if k in vivas}
    if not plan:
        return "No hay tomas repetidas pendientes en la línea de tiempo."
    from .model import SUG_APPLIED
    n = ctrl.apply_suggestions(list(plan), keep_por=plan)
    if not n:
        return ""
    quitadas = set()
    for s in ctrl.project.suggestions:
        if s.id in plan and s.status == SUG_APPLIED and s.applied_start is not None:
            quitadas.add(_clave_toma(s.applied_start, s.applied_end))
    return (f"✓ Quitadas {len(quitadas)} toma(s) vieja(s): queda la última de cada una. Ctrl+Z lo deshace.")


def dar_por_revisada(ctrl, marca: Marca) -> str:
    """«Está bien así»: cada fuente con su estado de siempre (la propuesta se rechaza, el corte va a cut_ok, el
    marcador queda resuelto; huecos y material repetido, a review_ok). Un Ctrl+Z."""
    if marca.tipo in ("toma", "muletilla"):
        ctrl.reject_suggestions(marca.ref.split(","))     # (una toma puede tener varias propuestas)
    elif marca.tipo == "duda":
        ctrl.approve_cut(marca.ref)
    elif marca.tipo in ("obs", "tema", "marcador"):
        ctrl.update_marker(marca.ref, resuelto=True)
    else:
        ctrl.approve_review(marca.clave)
    return f"✓ {TIPOS[marca.tipo][0]}: revisado en {_mmss(marca.t)} (Ctrl+Z lo devuelve)."


def marcador_en(project, t: float, fps: float = 30.0):
    """El marcador puntual (no tema) que está en el instante t (± 1 fotograma), o None."""
    tol = 1.0 / max(1.0, float(fps or 30)) + 1e-6
    cerca = [m for m in project.markers if m.kind != "topic" and abs(m.time - t) <= tol]
    return min(cerca, key=lambda m: abs(m.time - t)) if cerca else None
