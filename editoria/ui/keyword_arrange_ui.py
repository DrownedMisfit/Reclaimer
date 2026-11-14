"""
⚡ Fila de palabras clave en la línea de tiempo (ver core/keyword_arrange.py): calcula las menciones de las palabras que
tienen carpeta, el tipo sugerido de cada una (🎮/🎬/🖼) y, con «⚡ Acomodar todo», el acomodo entero en segundo plano
(leer duraciones, huellas de la IA) para ponerlo en la pista de palabras clave en un solo Ctrl+Z.

Las carpetas se leen al enseñar la fila, con «⟳» y antes de cada ⚡ (no mientras editas). Las menciones se recalculan
solo si cambian las transcripciones o los clips de la narración; cambiar un chip solo recalcula los tipos.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QSettings, QTimer

from ..core import keyword_arrange as KA
from ..core import keyword_folders as KF

AJUSTE_FILA = "timeline/palabras_fila"
AJUSTE_ORDEN = "timeline/palabras_orden_archivos"
AJUSTE_CONTEXTO = "timeline/palabras_segun_lo_que_dices"


def _on(clave: str, defecto: bool = True) -> bool:
    return str(QSettings("EditorIA", "EditorIA").value(clave, "true" if defecto else "false")).lower() == "true"


class _LazyQ:
    """Huellas de lo que dices alrededor de cada mención, calculadas solo si hacen falta (y si el modelo ya está)."""

    def __init__(self, textos: dict[str, str]):
        self.textos, self.memo, self.enc = textos, {}, None

    def get(self, key):
        if key in self.memo:
            return self.memo[key]
        texto = (self.textos.get(key) or "").strip()
        v = None
        if texto:
            try:
                from ..ai import embeddings
                if self.enc is None:
                    self.enc = embeddings.get("clip_text") if embeddings.is_downloaded("clip_text") else False
                if self.enc:
                    v = self.enc.encode([texto])[0]
            except Exception:  # noqa: BLE001 - sin huella: va en orden
                v = None
        self.memo[key] = v
        return v


class KeywordArranger(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl, self.tl = win, win.ctrl, win.timeline
        self.mentions: list[dict] = []
        self.folders: list[dict] = []
        self.pools: dict[str, KA.Pool] = {}
        self._pools_ok = False               # ¿ya se leyeron las carpetas (aunque estén vacías)?
        self._pools_err = ""                 # por qué falló la última lectura (para avisar con el motivo real)
        self._pool_job = None
        self._after: list = []               # lo que espera a que acabe de leer las carpetas
        self._arr_job = None
        self._dur: dict[str, tuple[float, dict]] = {}      # ruta normalizada → (mtime, probe)
        self._memo = None                    # (firma, menciones, duraciones de frase)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._marks)
        self.tl.kw_toggled.connect(self._toggled)
        self.tl.kw_kind_requested.connect(self._kind)
        self.tl.kw_arrange_requested.connect(self.arrange)
        self.tl.kw_menu_hook = self._options_menu
        self.ctrl.project_changed.connect(self._later)
        self.ctrl.transcript_changed.connect(lambda _m: (setattr(self, "_memo", None), self._later()))
        if _on(AJUSTE_FILA, False):
            self.tl.set_kw_visible(True)
            QTimer.singleShot(1500, lambda: self.refresh(True))

    # ----------------------------------------------------------- datos
    def root(self) -> str:
        from .clips_panel import _raiz_guardada
        return _raiz_guardada()

    def _toggled(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue(AJUSTE_FILA, "true" if on else "false")
        if on:
            self.refresh(True)
        else:
            self.tl.set_kw_marks([])

    def _later(self):
        if self.tl.kw_visible:
            self._timer.start()

    def _ai_types(self) -> dict[str, str]:
        return {os.path.normcase(os.path.abspath(m.path)): (m.ai_type or "") for m in self.ctrl.project.media.values()}

    def refresh(self, pools: bool = False):
        """Rehace las menciones y, si se pide (o aún no se leyeron), el material de cada carpeta (en segundo plano)."""
        if not self.tl.kw_visible:
            return
        if pools or not self._pools_ok:
            self._load_pools()
        else:
            self._marks()

    def _load_pools(self, after=None):
        if after is not None:
            self._after.append(after)
        if self._pool_job is not None:
            return
        from .jobs import BackgroundJob
        raiz, tipos, orden = self.root(), self._ai_types(), _on(AJUSTE_ORDEN)

        def work(_p, _c):
            folders = KF.list_folders(raiz) if os.path.isdir(raiz) else []
            return folders, KA.build_pools(folders, lambda p: tipos.get(os.path.normcase(os.path.abspath(p)), ""),
                                           file_order=orden)
        job = BackgroundJob(work, self.win)
        job.title = "🔑 Leyendo las carpetas de palabras clave"

        def fin(res=None):
            self._pool_job = None
            self._pools_ok = True                 # (también si falló o no hay carpetas: no se relee en bucle)
            if isinstance(res, tuple):
                self.folders, self.pools = res
                self._memo = None
            else:
                self.folders, self.pools = [], {}
            self._marks()
            pend, self._after = self._after, []
            for fn in pend:
                fn()
        job.done.connect(lambda r: (setattr(self, "_pools_err", ""), fin(r)))
        job.failed.connect(lambda m: (setattr(self, "_pools_err", str(m)), fin()))
        self._pool_job = job
        job.start()

    def _firma(self) -> tuple:
        """Lo que cambia las menciones: las transcripciones, los clips de lo transcrito y las carpetas."""
        p = self.ctrl.project
        trans = tuple(sorted((mid, len((d or {}).get("words") or []), id(d)) for mid, d in p.transcripts.items()))
        clips = tuple(sorted((c.id, c.media_id, round(c.start, 3), round(c.source_in, 3), round(c.duration, 3))
                             for c in p.clips.values() if c.media_id in p.transcripts or c.media_id in p.compounds))
        return (id(p), trans, clips, tuple(f["label"] for f in self.folders))

    def _mentions(self) -> tuple[list[dict], dict[float, float]]:
        from ..ai import keyword_glossary as KG
        from ..ai.mentions import find_mentions
        from ..core.keyword_place import duracion_frase
        firma = self._firma()
        if self._memo is not None and self._memo[0] == firma:
            return self._memo[1], self._memo[2]
        p = self.ctrl.project
        try:
            found = find_mentions(p, extra_terms=KF.terms(self.folders), glossary=KG.load())
        except Exception:  # noqa: BLE001 - sin transcripción todavía
            found = []
        ms = KA.collect(found, self.folders)
        frases = {m["t"]: duracion_frase(p, m["t"]) for m in ms}
        self._memo = (firma, ms, frases)
        return ms, frases

    def _marks(self):
        if not self.tl.kw_visible:
            return
        p = self.ctrl.project
        if not self.folders:
            self.mentions = []
            self.tl.set_kw_marks([])
            return
        self.mentions, frases = self._mentions()
        kinds = [KA.kind_for(m, p.kw_choices, self.pools.get(m["folder"]))[0] if self.pools.get(m["folder"])
                 else "none" for m in self.mentions]
        durs = KA.durations(self.mentions, kinds, lambda t: frases.get(t, 4.0))
        marks = []
        for m, kind, dur in zip(self.mentions, kinds, durs):
            pool = self.pools.get(m["folder"])
            manual = KA.kind_for(m, p.kw_choices, pool)[1] if pool else False
            marks.append({"key": m["key"], "t": m["t"], "dur": dur if dur >= KA.DUR_MIN else 0.0, "kind": kind,
                          "manual": manual, "term": m["folder"], "avail": pool.available() if pool else ["none"]})
        self.tl.set_kw_marks(marks)

    def _options_menu(self, menu):
        """Opciones de la secuencia (en el clic derecho de un chip); se recuerdan."""
        sub = menu.addMenu("Secuencia")
        for clave, texto in ((AJUSTE_ORDEN, "Seguir el orden de los archivos (01, 02…)"),
                             (AJUSTE_CONTEXTO, "Elegir el momento por lo que dices (con las huellas de la IA)")):
            a = sub.addAction(texto)
            a.setCheckable(True)
            a.setChecked(_on(clave))
            a.toggled.connect(lambda on, c=clave: (QSettings("EditorIA", "EditorIA").setValue(c, "true" if on else "false"),
                                                     self.refresh(c == AJUSTE_ORDEN)))
        menu.addAction("⟳ Volver a leer las carpetas", lambda: self.refresh(True))

    # ----------------------------------------------------------- acciones
    def _kind(self, keys: list, kind: str):
        self.ctrl.set_kw_choice(keys, kind or None)
        self._marks()

    def arrange(self, _leidas: bool = False):
        """⚡ Acomodar todo: primero relee las carpetas; el plan se hace en segundo plano (duraciones, huellas) y se
        pone en un solo Ctrl+Z (si mientras tanto cambió la narración o el proyecto, no se pone: se avisa)."""
        if self._arr_job is not None:
            return
        if not self.tl.kw_visible:
            self.tl.set_kw_visible(True)
            QSettings("EditorIA", "EditorIA").setValue(AJUSTE_FILA, "true")
        if not _leidas:
            self.win.statusBar().showMessage("🔑 Leyendo tus carpetas de palabras clave…", 4000)
            self._load_pools(after=lambda: self.arrange(True))
            return
        if self._pools_err:
            self.win.statusBar().showMessage(f"⚡ No pude leer tus carpetas de palabras clave: {self._pools_err}", 10000)
            return
        if not self.folders:
            self.win.statusBar().showMessage(
                "⚡ No hay carpetas de palabras clave: crea una en Medios → 🔑 Palabras clave (o enlaza una carpeta de tu "
                "PC) y vuelve a pulsar ⚡.", 10000)
            return
        self._marks()
        if not self.mentions:
            self.win.statusBar().showMessage(
                "⚡ No dices ninguna de tus palabras clave (¿falta transcribir la narración?).", 9000)
            return
        from .jobs import BackgroundJob
        p = self.ctrl.project
        mentions = [dict(m) for m in self.mentions]
        choices = dict(p.kw_choices)
        pools = self.pools
        _ms, frases = self._mentions()
        fin_linea = p.duration() or None
        contexto = _on(AJUSTE_CONTEXTO)
        conocidas = {os.path.normcase(os.path.abspath(m.path)): float(m.duration)
                     for m in p.media.values() if m.probed and m.duration > 0}
        dur_memo = self._dur
        firma = (id(p), tuple((m["key"], round(m["t"], 3)) for m in mentions))

        def work(prog, cancelado):
            from ..ai import clip_analysis
            from ..core import media as media_tools
            infos: dict[str, dict] = {}

            def probe(path):
                k = os.path.normcase(os.path.abspath(path))
                try:
                    mt = os.path.getmtime(path)
                except OSError:
                    return k, {"duration": 0.0}
                got = dur_memo.get(k)
                if got is None or got[0] != mt:
                    try:
                        got = (mt, media_tools.probe(path))
                    except Exception:  # noqa: BLE001 - archivo dañado: se salta
                        got = (mt, {"duration": 0.0})
                    dur_memo[k] = got
                return k, got[1]

            def duration_of(path):
                k = os.path.normcase(os.path.abspath(path))
                if k in conocidas:
                    return conocidas[k]
                k, info = probe(path)
                infos[k] = info
                prog(0.0, f"Leyendo {os.path.basename(path)}")
                return float(info.get("duration") or 0.0)

            def vecs_of(path):
                got = clip_analysis.load_cached(path)
                return (got[0], got[1]) if got else None
            q = _LazyQ({m["key"]: m["context"] for m in mentions}) if contexto else None
            items, res = KA.plan(mentions, choices, pools, duration_of, lambda t: frases.get(t, 4.0), fin_linea,
                                 context=contexto, vecs_of=vecs_of if contexto else None, qvecs=q,
                                 cancel=cancelado)
            if cancelado():                      # cancelado desde las tareas: no se pone nada (ni a medias)
                from ..ai.base import Cancelled
                raise Cancelled()
            for it in items:                     # (las imágenes nuevas también: importar no las lee otra vez)
                k = os.path.normcase(os.path.abspath(it.path))
                if it.kind == "image" and k not in conocidas and k not in infos:
                    infos[k] = probe(it.path)[1]
            return items, res, infos
        job = BackgroundJob(work, self.win)
        job.title = "⚡ Acomodando las palabras clave"
        self.win.statusBar().showMessage(f"⚡ Acomodando {len(mentions)} palabras clave…", 6000)

        def fin(out=None):
            self._arr_job = None
            if not isinstance(out, tuple):
                return
            items, res, infos = out
            self._marks()
            ahora = (id(self.ctrl.project), tuple((m["key"], round(m["t"], 3)) for m in self.mentions))
            if self.ctrl.project is not p or ahora != firma or dict(self.ctrl.project.kw_choices) != choices:
                self.win.statusBar().showMessage(
                    "⚡ La narración o los tipos cambiaron mientras acomodaba: no puse nada. Pulsa ⚡ otra vez.", 9000)
                return
            if not items:
                self.win.statusBar().showMessage("⚡ No hay material que poner (¿carpetas vacías o todo en ✕?).", 8000)
                return
            vivas = {m["key"] for m in mentions} | {k for k in choices          # (de narración que sigue existiendo)
                                                    if k.count("|") >= 2 and k.split("|")[1] in self.ctrl.project.transcripts}
            ids = self.ctrl.arrange_keywords(items, infos, keep_keys=vivas)
            if not ids:
                return                           # (el controlador ya avisó del motivo)
            partes = [f"✓ {len(ids)} clips acomodados en las palabras clave"]
            if res.get("by_context"):
                partes.append(f"{res['by_context']} elegidos por lo que dices")
            if res.get("skipped"):
                partes.append(f"{res['skipped']} sin sitio o sin material")
            if res.get("repeated"):
                partes.append("se acabó el material de alguna palabra y volvió a empezar")
            self.win.statusBar().showMessage(" · ".join(partes) + " · Ctrl+Z lo quita", 12000)
            self._marks()
        job.done.connect(fin)
        job.failed.connect(lambda msg: (setattr(self, "_arr_job", None),
                                        self.win.statusBar().showMessage(f"No se pudo acomodar: {msg}", 9000)))
        self._arr_job = job
        job.start()
