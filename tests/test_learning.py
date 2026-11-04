"""
Prueba del «◈ Aprendizaje de mi estilo» (Fase 1): apagado no registra nada; activado cuenta acciones del editor
(lo deshecho enseguida no cuenta), resume al guardar, la confianza sube con varios proyectos parecidos, un
proyecto raro no manda, compara «propuesta de la IA → resultado final», preferencias aceptar/rechazar/editar,
excluir un proyecto, borrar el perfil, y la primera versión automática usa lo aceptado (con razonamiento).
Usa una carpeta de datos TEMPORAL.
Ejecutar:  .venv/Scripts/python.exe tests/test_learning.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import style_learning as SL  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import ORIGIN_AI, TRACK_VIDEO, Clip, new_id  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    vid = os.path.join(out, "l_video.mp4")
    if not os.path.exists(vid):
        r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=s=320x180:r=30:d=120", "-c:v", "libx264", "-preset", "ultrafast", vid],
                           capture_output=True)
        assert r.returncode == 0, r.stderr
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    ctrl = win.ctrl
    L = win.learner
    assert not L.enabled and win.btn_learning.property("estado") == "apagado", "apagado de fábrica"
    st = QSettings("EditorIA", "EditorIA")

    def build(n_clips: int, clip_len: float, trans: bool = False, ai: bool = False):
        """Proyecto con n planos de clip_len s en V1 (como si los hubiera puesto la IA si ai=True)."""
        ctrl.new_project()
        mid = ctrl.import_paths([vid])[0]
        while ctrl.analyzing:
            pump(app, 0.05)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]

        def fn(p):
            for k in range(n_clips):
                c = Clip(new_id(), mid, v1.id, k * clip_len, (k * 1.7) % 100, clip_len,
                         origin=ORIGIN_AI if ai else "user")
                if trans and k:
                    c.fx = {"trans": {"type": "fade", "dur": 0.4}}
                p.clips[c.id] = c
            return n_clips
        ctrl._edit("IA · Primera versión (prueba)" if ai else "Añadir clips", fn)
        return v1

    # --- 1) Apagado: no registra nada
    build(10, 2.5)
    ctrl.save(os.path.join(out, "p0.eia"))
    assert not L.session.actions and not SL.load()["projects"], "apagado no observa ni guarda"
    print("✓ apagado: no registra acciones ni crea perfil")

    # --- 2) Activado: cuenta acciones; lo deshecho enseguida no cuenta; resume al guardar
    L.set_enabled(True)
    assert win.btn_learning.property("estado") == "aprendiendo"
    v1 = build(12, 2.4)
    c0 = ctrl.project.clips_on(v1.id)[0]
    ctrl.set_clip_props([c0.id], "Bloquear clip", locked=True)
    ctrl.set_clip_props([c0.id], "Bloquear clip", locked=False)
    ctrl.split(c0.start + 1.0, [c0.id])
    ctrl.undo_stack.undo()                 # deshecho enseguida: no cuenta
    assert L.session.actions.get("Dividir clip", 0) == 0 and L.session.actions.get("Bloquear clip") == 2, \
        L.session.actions
    ctrl.save(os.path.join(out, "p1.eia"))
    d = SL.load()
    rec = d["projects"][SL.project_key(os.path.join(out, "p1.eia"))]
    assert abs(rec["final"]["clip_len"] - 2.4) < 0.01 and rec["actions"]["Bloquear clip"] == 2, rec
    pats = {p["key"]: p for p in SL.patterns(d, "youtube")}
    c1 = pats["clip_len"]["confidence"]
    assert c1 < 0.45, f"un solo proyecto no debe dar mucha confianza: {c1}"
    assert not d["prefs"], "con un proyecto no hay preferencias"
    print(f"✓ activado: cuenta acciones (deshacer enseguida no cuenta); 1 proyecto → confianza {c1:.0%}")

    # --- 3) Varios proyectos parecidos (la IA propone transiciones, tú las quitas y alargas un poco)
    for i, ln in enumerate((2.6, 2.5, 2.7)):
        v1 = build(12, ln - 1.2, trans=True, ai=True)            # propuesta de la IA (planos más cortos)
        assert L.session.baseline is not None
        clips = ctrl.project.clips_on(v1.id)
        ctrl.set_transition([c.id for c in clips[1:]], None)     # quitas las transiciones
        changes = {c.id: {"start": round(k * ln, 3), "duration": ln} for k, c in enumerate(clips)}
        ctrl.batch_clip_props(changes, "Alargar planos")          # y alargas los planos
        ctrl.delete_clips([clips[-1].id])
        ctrl.save(os.path.join(out, f"p{i + 2}.eia"))
    # un proyecto raro (planos de 20 s): no debe cambiar tu estilo
    build(4, 20.0)
    ctrl.save(os.path.join(out, "raro.eia"))
    d = SL.load()
    pats = {p["key"]: p for p in SL.patterns(d, "youtube")}
    assert abs(pats["clip_len"]["value"] - 2.5) < 0.2, pats["clip_len"]
    assert pats["clip_len"]["confidence"] > 0.6 > c1, pats["clip_len"]
    prefs = {pid.split(":", 1)[1]: p for pid, p in d["prefs"].items() if p["scope"] == "youtube"}
    assert "clip_len" in prefs and "cortos" in prefs["clip_len"]["text"], list(prefs)
    assert "ia_quitas_trans" in prefs and "ia_alargas" in prefs, list(prefs)
    assert all(p["state"] == "detectada" for p in d["prefs"].values())
    rec = d["projects"][SL.project_key(os.path.join(out, "p2.eia"))]
    assert rec["baseline"]["trans_min"] > 0 and rec["final"]["trans_min"] == 0 and rec["final"]["ai_kept"] < 1
    print(f"✓ 5 proyectos: planos ≈{pats['clip_len']['value']:.1f} s, confianza {pats['clip_len']['confidence']:.0%} "
          f"(el raro de 20 s no manda) · detectado: " + " | ".join(p["text"] for p in prefs.values()))

    # --- 4) La ventana: preferencias (aceptar, rechazar, editar), excluir proyecto, recursos
    win.open_learning()
    dlg = win._learning_dlg
    pump(app, 0.3)
    assert dlg.toggle.isChecked() and "Aprendiendo" in dlg.state.text()
    dlg.tabs.setCurrentIndex(1)
    dlg.scope.setCurrentIndex(dlg.scope.findData("youtube"))
    pump(app, 0.2)
    dlg.grab().save(os.path.join(out, "aprendizaje_estilo.png"))
    pid_len = next(pid for pid in d["prefs"] if pid.endswith(":clip_len") and pid.startswith("youtube"))
    pid_tr = next(pid for pid in d["prefs"] if pid.endswith(":ia_quitas_trans"))
    dlg._set_state(pid_len, "aceptada")
    dlg._set_state(pid_tr, "aceptada")
    dlg.tabs.setCurrentIndex(2)
    pump(app, 0.2)
    dlg.grab().save(os.path.join(out, "aprendizaje_prefs.png"))
    hints = SL.hints(L.data, "youtube")
    hs = {h["setting"]: h for h in hints}
    assert hs["ritmo"]["value"] == "fast" and hs["estilo"]["value"] == "natural", hints
    # rechazar: deja de usarse y no vuelve como «detectada»
    dlg._set_state(pid_tr, "rechazada")
    assert "estilo" not in {h["setting"] for h in SL.hints(L.data, "youtube")}
    L.analyze(force=True)
    assert L.data["prefs"][pid_tr]["state"] == "rechazada"
    dlg._set_state(pid_tr, "aceptada")
    u, prev = SL.process_usage(None)
    time.sleep(0.2)
    u, _ = SL.process_usage(prev)
    assert u["ram_mb"] > 50 and u["disk_kb"] > 0, u
    dlg._update_usage()
    assert "MB" in dlg.res_ram.text()
    print(f"✓ ventana: aceptar/rechazar; recursos: CPU {u['cpu']:.0f} %, RAM {u['ram_mb']:.0f} MB, perfil "
          f"{u['disk_kb']:.0f} KB")

    # --- 5) La primera versión automática usa lo aceptado (y explica por qué)
    from editoria.ui.auto_dialog import AutoDialog
    ad = AutoDialog(win)
    assert ad.pace.currentData() == "fast" and ad.style.currentData() == "natural", \
        (ad.pace.currentData(), ad.style.currentData())
    assert ad.style_reasons and any("≈2.5 s" in r or "≈2.6 s" in r for r in ad.style_reasons), ad.style_reasons
    ad.show()
    pump(app, 0.2)
    ad.grab().save(os.path.join(out, "primera_version_estilo.png"))
    ad.close()
    print("✓ primera versión: preselecciona ritmo rápido y estilo natural — «" + ad.style_reasons[0] + "»")

    # --- 6) Excluir un proyecto · pausa · desactivar · borrar el perfil
    ctrl.load(os.path.join(out, "raro.eia"))
    L.set_project_learn(False)
    n_before = len(SL.patterns(L.data, "youtube"))
    assert {p["key"]: p for p in SL.patterns(L.data, "youtube")}["clip_len"]["n"] == 4
    assert L.analyze(force=True).startswith("Este proyecto está excluido")
    L.set_paused(True)
    assert win.btn_learning.property("estado") == "pausa"
    ctrl.set_clip_props([ctrl.project.clips_on([t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1].id)[0].id],
                        "Bloquear clip", locked=True)
    assert not L.session.actions, "en pausa no registra"
    L.set_paused(False)
    dlg._delete.__func__  # (el botón pide confirmación; se prueba la función de fondo)
    SL.delete_profile()
    L.data = SL.load()
    assert not L.data["projects"] and not L.data["prefs"] and L.enabled
    L.set_enabled(False)
    assert not SL.load()["settings"]["enabled"]
    print(f"✓ excluir proyecto ({n_before} patrones siguen), pausa no registra, borrar perfil y desactivar")

    dlg.close()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    for k in ("ventana/paneles", "guia/colocada"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
