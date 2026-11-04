"""
🤝 Puente para que Claude edite contigo (por MCP). OPCIONAL y APAGADO por defecto: menú Ayuda → «🤝 Dejar que Claude
edite conmigo». Reclaimer funciona exactamente igual sin esto.

  · Solo escucha en tu PC (127.0.0.1, puerto al azar) y exige una clave que cambia en cada arranque; los dos datos se
    dejan en datos/puente_claude.json para el servidor MCP (mcp_reclaimer.py), que es lo que arranca la app de Claude.
  · Cada orden usa las funciones normales de Reclaimer: todo aparece en tu línea de tiempo y se deshace con Ctrl+Z.
    Nada borra ni pisa archivos (guardar/exportar siempre con nombre nuevo si no hay uno).
  · Lo que hace Claude se ve en la barra de estado («🤝 Claude: …»).
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets

from PySide6.QtCore import QObject, QSettings
from PySide6.QtNetwork import QHostAddress, QTcpServer

from ..core.paths import app_data_dir

KEY = "mcp/activo"
MAX_MSG = 1 << 20


def bridge_file() -> str:
    return os.path.join(str(app_data_dir()), "puente_claude.json")


def enabled() -> bool:
    return str(QSettings("EditorIA", "EditorIA").value(KEY, "false")) == "true"


class ClaudeBridge(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.server: QTcpServer | None = None
        self.token = ""
        self.jobs: dict[str, dict] = {}            # trabajos lanzados por Claude (transcribir…)
        self._keep: list = []

    # ------------------------------------------------------------ encender / apagar
    def set_enabled(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue(KEY, "true" if on else "false")
        self.start() if on else self.stop()

    def start(self) -> bool:
        if self.server is not None:
            return True
        srv = QTcpServer(self)
        if not srv.listen(QHostAddress.LocalHost, 0):
            return False
        srv.newConnection.connect(self._on_conn)
        self.server, self.token = srv, secrets.token_hex(24)
        self._write_file()
        if not hasattr(self, "_watch"):            # si el archivo desaparece, se vuelve a escribir (si no, Claude no
            from PySide6.QtCore import QTimer     # encuentra Reclaimer aunque esté escuchando)
            self._watch = QTimer(self)
            self._watch.setInterval(3000)
            self._watch.timeout.connect(self._check_file)
        self._watch.start()
        return True

    def _data(self) -> dict:
        return {"port": self.server.serverPort(), "token": self.token, "pid": os.getpid()}

    def _write_file(self):
        tmp = bridge_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data(), f)
        os.replace(tmp, bridge_file())

    def _check_file(self):
        if self.server is None:
            return
        try:
            with open(bridge_file(), encoding="utf-8") as f:
                ok = json.load(f) == self._data()
        except (OSError, ValueError):
            ok = False
        if not ok:
            try:
                self._write_file()
            except OSError:
                pass

    def stop(self):
        if hasattr(self, "_watch"):
            self._watch.stop()
        if self.server is not None:
            self.server.close()
            self.server = None
        try:
            with open(bridge_file(), encoding="utf-8") as f:
                mine = json.load(f).get("pid") == os.getpid()
            if mine:                                  # (en Windows no se puede borrar mientras está abierto)
                os.remove(bridge_file())
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------ conexiones
    def _on_conn(self):
        while self.server is not None and self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty("buf", b"")
            sock.readyRead.connect(lambda s=sock: self._on_read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_read(self, sock):
        buf = bytes(sock.property("buf") or b"") + bytes(sock.readAll())
        if len(buf) > MAX_MSG:
            sock.abort()
            return
        if not buf.endswith(b"\n"):
            sock.setProperty("buf", buf)
            return
        sock.setProperty("buf", b"")
        try:
            msg = json.loads(buf.decode("utf-8"))
        except ValueError:
            self._reply(sock, False, "Mensaje no válido.")
            return
        if not hmac.compare_digest(str(msg.get("token", "")), self.token):
            self._reply(sock, False, "Clave incorrecta.")
            return
        tool, args = str(msg.get("tool", "")), msg.get("args") or {}
        fn = getattr(self, "t_" + tool, None)
        if fn is None:
            self._reply(sock, False, f"No conozco «{tool}».")
            return
        self.win.statusBar().showMessage(f"🤝 Claude: {tool.replace('_', ' ')}…", 6000)
        try:
            fn(args, lambda ok, text, image=None, s=sock, t=tool: self._done(s, t, ok, text, image))
        except Exception as exc:  # noqa: BLE001 - una orden fallida nunca tumba Reclaimer
            self._done(sock, tool, False, f"No se pudo: {exc}")

    def _done(self, sock, tool, ok, text, image=None):
        self.win.statusBar().showMessage(f"🤝 Claude · {tool.replace('_', ' ')}: {text.splitlines()[0][:120]}", 8000)
        self._reply(sock, ok, text, image)

    @staticmethod
    def _reply(sock, ok, text, image=None):
        out = {"ok": bool(ok), "text": text}
        if image:
            out["image"] = image
        try:
            sock.write((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
            sock.flush()
            sock.disconnectFromHost()
        except RuntimeError:
            pass

    # ------------------------------------------------------------ utilidades
    def _bg(self, title, fn, on_done, reply):
        """Trabajo pesado en segundo plano; on_done(resultado) en el hilo de la interfaz."""
        from .task_window import manager
        manager().start(title, lambda _p, _c: fn(), on_done,
                        lambda err: reply(False, f"Falló: {err}"))

    def _edit_result(self, before: int, what: str) -> tuple[bool, str]:
        n = self.ctrl.undo_stack.index() - before
        if n <= 0:
            return False, f"No se hizo nada ({what})."
        return True, f"✓ {what} (Ctrl+Z lo deshace)."

    def _media(self, mid):
        m = self.ctrl.project.media.get(mid or "")
        if m is None:
            raise ValueError(f"No existe el archivo «{mid}» (mira «estado»).")
        return m

    # ------------------------------------------------------------ herramientas
    def t_estado(self, a, reply):
        from ..core.model import TRACK_AUDIO, TRACK_VIDEO
        p, ctrl, win = self.ctrl.project, self.ctrl, self.win
        lines = [f"Proyecto «{p.name}» · {p.format} {p.width}×{p.height} {p.fps:g} fps · dura {p.duration():.1f} s · "
                 f"cabezal {win.engine.time:.2f} s · archivo: {ctrl.path or '(sin guardar)'}"
                 + (" · cambios sin guardar" if ctrl.dirty else "")]
        lines.append("Pistas (de arriba a abajo):")
        for tr in p.tracks:
            cl = p.clips_on(tr.id)
            flags = "".join(x for x, on in ((" 🔒", tr.locked), (" oculta", tr.hidden), (" muda", tr.muted)) if on)
            desc = ", ".join(f"{(p.media_of(c).name if p.media_of(c) else (c.text or {}).get('content', 'texto'))[:28]}"
                             f" {c.start:.1f}–{c.end:.1f}" for c in cl[:8]) + (" …" if len(cl) > 8 else "")
            lines.append(f"  · {tr.name} [{tr.kind}] id={tr.id}{flags}: {len(cl)} clips {desc}")
        lines.append("Archivos importados:")
        for m in list(p.media.values())[:60]:
            tr_ = " · transcrito" if m.id in p.transcripts else ""
            lines.append(f"  · {m.name} [{m.kind}, {m.duration:.1f} s] id={m.id}{tr_}")
        st = p.subtitles
        lines.append(f"Subtítulos: {'sí' if st.enabled else 'no'}" + (f" (estilo «{st.preset}», de {st.media_id})"
                                                                     if st.enabled else ""))
        for mid, j in self.jobs.items():
            lines.append(f"Transcribiendo {j.get('name', mid)}: {j.get('estado')}")
        try:
            for j in self.win.render_queue.jobs[-5:]:
                lines.append(f"Exportación «{j['name']}»: {j['status']} {int(100 * j.get('progress', 0))} %"
                             + (f" → {j['opts']['path']}" if j['status'] == 'done' else ""))
        except (AttributeError, KeyError, TypeError):
            pass
        _ = (TRACK_AUDIO, TRACK_VIDEO)
        reply(True, "\n".join(lines))

    def t_importar(self, a, reply):
        paths = [os.path.normpath(x) for x in a.get("rutas") or []]
        missing = [x for x in paths if not os.path.isfile(x)]
        if missing:
            return reply(False, "No existen: " + "; ".join(missing))
        ids = self.ctrl.import_now(paths)
        p = self.ctrl.project
        reply(True, "✓ Importados: " + "; ".join(f"{p.media[i].name} id={i}" for i in ids if i in p.media))

    def t_poner_en_linea_de_tiempo(self, a, reply):
        m = self._media(a.get("media_id"))
        t = float(a["inicio"]) if a.get("inicio") is not None else self.win.engine.time
        before = self.ctrl.undo_stack.index()
        self.ctrl.add_media([m.id], a.get("pista") or None, t)
        reply(*self._edit_result(before, f"«{m.name}» puesto en la línea de tiempo en {t:.1f} s"))

    def t_formato(self, a, reply):
        fmt = a.get("tipo")
        if fmt not in ("youtube", "short", "edit"):
            return reply(False, "Formato: youtube, short o edit.")
        before = self.ctrl.undo_stack.index()
        self.ctrl.set_project_format(fmt)
        p = self.ctrl.project
        ok, txt = self._edit_result(before, f"formato {fmt} ({p.width}×{p.height})")
        reply(True, txt if ok else f"Ya estaba en {fmt}.")

    def t_transcribir(self, a, reply):
        from ..ai import transcription
        m = self._media(a.get("media_id"))
        if m.id in self.jobs and self.jobs[m.id].get("estado") == "en marcha":
            return reply(True, "Ya se está transcribiendo.")
        ok, why = transcription.is_available()
        if not ok:
            return reply(False, why)
        if not transcription.is_downloaded("equilibrado"):
            return reply(False, "Falta descargar el modelo de transcripción: pídele al usuario que transcriba una vez "
                                "desde la pestaña «Limpieza» (allí se descarga con su permiso).")
        job = self.jobs[m.id] = {"name": m.name, "estado": "en marcha"}
        path = m.path

        def work():
            from ..core import media as media_tools
            return transcription.transcribe(media_tools.decode_mono(path, 16000), "equilibrado", "es")

        def done(tr, mid=m.id):
            self.ctrl.set_transcript(mid, tr)
            job["estado"] = f"terminado ({len(tr.get('words', []))} palabras)"

        def fail(err):
            job["estado"] = f"falló: {err}"
        from .task_window import manager
        manager().start(f"🤝 Transcribir «{m.name}»", lambda _p, _c: work(), done, fail)
        reply(True, f"✓ Transcribiendo «{m.name}» en segundo plano (mira «estado» para saber cuándo termina).")

    def _silence_targets(self, mid):
        from ..core.model import TRACK_AUDIO, TRACK_VIDEO
        p = self.ctrl.project
        out = []
        for tr in p.tracks:
            for c in p.clips_on(tr.id):
                m = p.media_of(c)
                if m is None or c.text is not None or (mid and m.id != mid):
                    continue
                if tr.kind == TRACK_AUDIO and (m.kind == "audio" or m.has_audio):
                    out.append(c.id)
                elif tr.kind == TRACK_VIDEO and m.has_audio and not c.link:
                    out.append(c.id)
        return out

    def t_eliminar_silencios(self, a, reply):
        from ..core import silence as S
        names = {"shorts": "Pausas cortas", "equilibrado": "Equilibrado", "natural": "Natural", "rapido": "Rápido"}
        want = names.get(a.get("ajuste") or "shorts", "Pausas cortas")
        preset = next((v for k, v in S.PRESETS.items() if k.startswith(want)), next(iter(S.PRESETS.values())))
        prot = a.get("proteccion") if a.get("proteccion") in S.PROTECT else "max"
        settings = dict(preset, mode="hibrido", protect=prot)
        ids = self._silence_targets(a.get("media_id"))
        if not ids:
            return reply(False, "No hay audio en la línea de tiempo (o de ese archivo).")
        p = self.ctrl.project
        paths = list(dict.fromkeys(p.media_of(p.clips[i]).path for i in ids))

        def done(_r):
            p2 = self.ctrl.project
            clips = [p2.clips[i] for i in ids if i in p2.clips]
            regs = S.plan(p2, clips, p2.fps, settings)
            total = sum(b - c for c, b in regs)
            if a.get("solo_mirar"):
                return reply(True, f"Quitaría {len(regs)} silencios ({total:.1f} s) con «{want}». No he cortado nada.")
            if not regs:
                return reply(True, "No hay silencios que quitar con ese ajuste.")
            before = self.ctrl.undo_stack.index()
            self.ctrl.remove_silence(ids, regs, "all", bool(a.get("fundido")))   # (fundidos solo si se piden)
            ok, txt = self._edit_result(before, f"quitados {len(regs)} silencios ({total:.1f} s) con «{want}», "
                                                f"híbrido, protección {prot}")
            reply(ok, txt)
        self._bg("🤝 Escuchando dónde hablas…", lambda: [S.analyze(x) for x in paths], done, reply)

    def t_subtitulos(self, a, reply):
        from ..core import subtitles as SUBS
        est = a.get("estilo")
        if est == "quitar":
            before = self.ctrl.undo_stack.index()
            self.ctrl.set_subtitle_style("🤝 Quitar subtítulos", enabled=False)
            return reply(*self._edit_result(before, "subtítulos quitados"))
        p = self.ctrl.project
        mid = a.get("media_id") or p.subtitles.media_id or next(iter(p.transcripts), "")
        if mid not in p.transcripts:
            return reply(False, "Ese archivo no está transcrito: usa «transcribir» primero.")
        name = {"shorts": SUBS.SHORTS, "mis_shorts": "Mis Shorts", "caja": "Caja oscura", "dinamico": "Shorts dinámico",
                "minimalista": "Minimalista"}.get(est, "YouTube clásico")
        before = self.ctrl.undo_stack.index()
        self.ctrl.set_subtitle_style(f"🤝 Subtítulos «{name}»", enabled=True, media_id=mid, preset=name,
                                     **SUBS.PRESETS[name])
        reply(*self._edit_result(before, f"subtítulos puestos con el estilo «{name}»"))

    def t_texto(self, a, reply):
        t = float(a["inicio"]) if a.get("inicio") is not None else self.win.engine.time
        before = self.ctrl.undo_stack.index()
        self.ctrl.add_text(t, float(a.get("duracion") or 3.0), str(a.get("contenido", "")).strip() or "Texto")
        reply(*self._edit_result(before, f"texto «{a.get('contenido', '')}» en {t:.1f} s"))

    def t_cortar(self, a, reply):
        before = self.ctrl.undo_stack.index()
        if a.get("en") is not None:
            self.ctrl.split(float(a["en"]))
            return reply(*self._edit_result(before, f"dividido en {float(a['en']):.2f} s"))
        if a.get("quitar_desde") is not None and a.get("quitar_hasta") is not None:
            x, y = sorted((float(a["quitar_desde"]), float(a["quitar_hasta"])))
            self.ctrl.remove_silence([], [(x, y)], "all", bool(a.get("fundido")))
            return reply(*self._edit_result(before, f"quitado el tramo {x:.2f}–{y:.2f} s y juntado lo de detrás"))
        reply(False, "Di «en» (dividir) o «quitar_desde» y «quitar_hasta».")

    def _pick(self, a) -> list[str]:
        """Clips elegidos por ids, por pista y/o por tramo (desde–hasta)."""
        p = self.ctrl.project
        ids = [i for i in (a.get("ids") or []) if i in p.clips]
        if not ids and (a.get("pista") or a.get("desde") is not None or a.get("hasta") is not None):
            lo = float(a["desde"]) if a.get("desde") is not None else -1e9
            hi = float(a["hasta"]) if a.get("hasta") is not None else 1e9
            ids = [c.id for c in p.clips.values() if (not a.get("pista") or c.track_id == a["pista"])
                   and c.end > lo and c.start < hi]
        return ids

    def t_clips(self, a, reply):
        p = self.ctrl.project
        ids = self._pick(a) if (a.get("pista") or a.get("desde") is not None or a.get("hasta") is not None) \
            else list(p.clips)
        rows = sorted((p.clips[i] for i in ids), key=lambda c: (c.track_id, c.start))
        out = [f"{len(rows)} clips" + (" (se muestran 200)" if len(rows) > 200 else "") + ":"]
        for c in rows[:200]:
            m = p.media_of(c)
            what = (m.name if m else "texto «" + str((c.text or {}).get("content", ""))[:30] + "»")[:40]
            fx = c.fx or {}
            extra = "".join([f" · fundidos {float(fx.get('fade_in', 0)):.2f}/{float(fx.get('fade_out', 0)):.2f} s"
                             if fx.get("fade_in") or fx.get("fade_out") else "",
                             "" if c.enabled else " · inactivo", " · 🔒" if c.locked else ""])
            out.append(f"  · id={c.id} pista={p.track(c.track_id).name} {c.start:.2f}–{c.end:.2f} {what} · "
                       f"vol {int(round(c.volume * 100))} %{extra}")
        reply(True, "\n".join(out))

    def t_ajustar_clips(self, a, reply):
        p = self.ctrl.project
        ids = self._pick(a)
        if not ids:
            return reply(False, "No hay clips con esa elección (mira «clips»).")
        changes, what = {}, []
        for cid in ids:
            c = p.clips[cid]
            ch = {}
            if a.get("volumen") is not None:
                ch["volume"] = max(0.0, min(4.0, float(a["volumen"]) / 100))
            if a.get("activo") is not None:
                ch["enabled"] = bool(a["activo"])
            fx = dict(c.fx or {})
            for key, arg in (("fade_in", "fundido_entrada"), ("fade_out", "fundido_salida")):
                if a.get(arg) is not None:
                    v = max(0.0, min(float(a[arg]), c.duration / 2))
                    if v > 0:
                        fx[key] = v
                    else:
                        fx.pop(key, None)
            if fx != (c.fx or {}):
                ch["fx"] = fx or None
            if ch:
                changes[cid] = ch
        for arg, lab in (("volumen", "volumen"), ("fundido_entrada", "fundido de entrada"),
                         ("fundido_salida", "fundido de salida"), ("activo", "activo")):
            if a.get(arg) is not None:
                what.append(f"{lab} {a[arg]}")
        if not changes:
            return reply(True, "Ya estaban así: no se cambió nada.")
        before = self.ctrl.undo_stack.index()
        self.ctrl.batch_clip_props(changes, "🤝 Ajustar clips")
        reply(*self._edit_result(before, f"{len(changes)} clips: " + ", ".join(what)))

    def t_borrar_clips(self, a, reply):
        ids = self._pick(a)
        if not ids:
            return reply(False, "No hay clips con esa elección (mira «clips»).")
        before = self.ctrl.undo_stack.index()
        self.ctrl.delete_clips(ids, ripple=bool(a.get("juntar")))
        reply(*self._edit_result(before, f"borrados {len(ids)} clips" + (" y juntado lo de detrás"
                                                                        if a.get("juntar") else "")))

    def t_efectos_pista(self, a, reply):
        from ..core.model import TRACK_AUDIO
        tr = self.ctrl.project.track(a.get("pista") or "")
        if tr is None or tr.kind != TRACK_AUDIO:
            return reply(False, "Esa no es una pista de audio (mira «estado»).")
        fx = dict(tr.fx or {})
        names = {"ecualizar": "eq", "reducir_ruido": "denoise", "de_esser": "deess", "compresor": "compress"}
        for arg, key in names.items():
            if a.get(arg) is not None:
                fx[key] = bool(a[arg])
        before = self.ctrl.undo_stack.index()
        self.ctrl.set_track_props(tr.id, "🤝 Efectos de la pista", fx=fx)
        on = [arg for arg, key in names.items() if fx.get(key)]
        ok, txt = self._edit_result(before, f"efectos de «{tr.name}»: " + (", ".join(on) or "ninguno"))
        reply(True, txt if ok else f"Ya estaba así: {', '.join(on) or 'ninguno'}.")

    def t_juntar_huecos(self, a, reply):
        from ..core.model import TRACK_AUDIO, TRACK_VIDEO
        before = self.ctrl.undo_stack.index()
        if a.get("en") is not None:
            t = float(a["en"])
            self.ctrl.join_gaps([(tr.id, t) for tr in self.ctrl.project.tracks if tr.kind in (TRACK_AUDIO, TRACK_VIDEO)])
        else:
            self.ctrl.close_gaps_on(None)
        reply(*self._edit_result(before, "huecos cerrados"))

    def t_ir_a(self, a, reply):
        self.win.engine.user_seek(max(0.0, float(a.get("segundo", 0))))
        reply(True, f"Cabezal en {self.win.engine.time:.2f} s.")

    def t_captura(self, a, reply):
        from ..core import media as media_tools
        from ..core.paths import temp_dir
        from ..core.still import render_frame
        p = self.ctrl.project
        t = float(a["segundo"]) if a.get("segundo") is not None else self.win.engine.time
        snap = p.__class__.from_dict(p.to_dict())
        out = os.path.join(str(temp_dir()), f"claude_captura_{secrets.token_hex(4)}.png")

        def done(path):
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
            from PySide6.QtGui import QImage
            img = QImage(path)
            if img.isNull():
                return reply(False, "No salió la imagen.")
            img = img.scaled(720, 720, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            try:
                os.remove(path)
            except OSError:
                pass
            reply(True, f"Así se ve en {t:.2f} s ({p.width}×{p.height}).", base64.b64encode(bytes(ba)).decode())
        self._bg("🤝 Captura del visor", lambda: render_frame(snap, t, out, media_tools.ffmpeg()), done, reply)

    def t_deshacer(self, a, reply):
        st, done = self.ctrl.undo_stack, []
        for _ in range(max(1, int(a.get("pasos") or 1))):
            if not st.canUndo():
                break
            done.append(st.undoText())
            st.undo()
        reply(bool(done), ("✓ Deshecho: " + " · ".join(done)) if done else "No hay nada que deshacer.")

    def t_rehacer(self, a, reply):
        st, done = self.ctrl.undo_stack, []
        for _ in range(max(1, int(a.get("pasos") or 1))):
            if not st.canRedo():
                break
            done.append(st.redoText())
            st.redo()
        reply(bool(done), ("✓ Rehecho: " + " · ".join(done)) if done else "No hay nada que rehacer.")

    def t_guardar(self, a, reply):
        if self.ctrl.path:
            return reply(bool(self.ctrl.save()), f"✓ Guardado en {self.ctrl.path}")
        ruta = os.path.normpath(str(a.get("ruta") or ""))
        if not ruta or not ruta.lower().endswith(".eia"):
            return reply(False, "El proyecto aún no tiene archivo: dime una ruta nueva terminada en .eia.")
        if os.path.exists(ruta):
            return reply(False, "Ya existe un archivo con ese nombre: no lo piso. Elige otro.")
        reply(bool(self.ctrl.save(ruta)), f"✓ Guardado en {ruta}")

    def t_exportar(self, a, reply):
        from ..export.ffmpeg_export import TARGETS, ExportOptions, target_bitrate, target_size
        key = a.get("destino")
        if key not in TARGETS:
            return reply(False, "Destino: youtube, tiktok o windows.")
        p = self.ctrl.project
        base = os.path.dirname(self.win.default_export_path())
        name = (str(a.get("nombre") or "").strip() or f"{p.name} - {TARGETS[key]['suffix'] or key}")
        name = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "video"
        path, k = os.path.join(base, f"{name}.mp4"), 2
        while os.path.exists(path):                 # nunca pisa un archivo
            path = os.path.join(base, f"{name} ({k}).mp4")
            k += 1
        os.makedirs(base, exist_ok=True)
        w, h = target_size(key, p.width, p.height)
        fps = p.fps if p.fps in (24, 25, 30, 50, 60) else 60
        opts = ExportOptions(path=path, width=w, height=h, fps=float(fps), codec="h264", encoder="gpu",
                             bitrate_mbps=target_bitrate(key, w, h), target=key)
        self.win.render_queue.add(p, opts, "🤝 " + TARGETS[key]["name"])
        self.win.render_queue.start()
        reply(True, f"✓ Exportando para {TARGETS[key]['name']} en segundo plano → {path} (progreso en «estado»).")
