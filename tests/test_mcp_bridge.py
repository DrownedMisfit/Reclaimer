"""
Prueba de «🤝 Dejar que Claude edite conmigo» (MCP): apagado por defecto; encendido, el servidor MCP (mcp_reclaimer.py)
habla con Reclaimer por el puente y cada orden usa las funciones normales (todo con Ctrl+Z):
  · apagado: el servidor responde que no puede (y Reclaimer sigue igual);
  · protocolo MCP: initialize, tools/list (20 herramientas), tools/call;
  · estado, importar, poner en la línea de tiempo, texto, cortar, juntar huecos, deshacer, captura (imagen), guardar
    (no pisa archivos), exportar (nombre nuevo); una clave incorrecta se rechaza.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_mcp_bridge.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def call(app, fn, *a, timeout=120):
    """Llama al servidor MCP desde otro hilo (como hace la app de Claude) mientras Reclaimer sigue funcionando."""
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("r", fn(*a)), daemon=True)
    th.start()
    t0 = time.time()
    while th.is_alive() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    assert "r" in box, "sin respuesta"
    return box["r"]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    import mcp_reclaimer as MCP
    from editoria import mcp_tools as T
    from editoria.core import media as M
    from editoria.ui.claude_bridge import bridge_file, enabled
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    pump(app, 0.3)
    win.a_mcp.setChecked(False)                     # (si en tus ajustes ya estaba activado: se prueba desde apagado)
    pump(app, 0.2)
    assert not enabled() and win.claude_bridge.server is None and not os.path.exists(bridge_file())
    r = MCP.call_bridge("estado", {})
    assert not r["ok"] and "no está abierto" in r["text"], r
    print("✓ apagado por defecto: el servidor MCP dice que no puede y Reclaimer no escucha nada")

    # protocolo MCP
    init = MCP.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert init["result"]["serverInfo"]["name"] == "reclaimer" and "tools" in init["result"]["capabilities"]
    assert MCP.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tl = MCP.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert len(tl) == len(T.TOOLS) >= 16 and all(t["inputSchema"]["type"] == "object" for t in tl)
    bad = MCP.handle({"jsonrpc": "2.0", "id": 3, "method": "nada"})
    assert bad["error"]["code"] == -32601
    print(f"✓ protocolo MCP: initialize, tools/list ({len(tl)} herramientas), errores bien")

    win.a_mcp.setChecked(True)                      # el usuario lo activa en el menú Ayuda
    pump(app, 0.2)
    assert enabled() and os.path.exists(bridge_file())
    info = json.load(open(bridge_file(), encoding="utf-8"))
    os.remove(bridge_file())                        # si alguien borra el archivo, se vuelve a escribir solo
    pump(app, 3.5)
    assert json.load(open(bridge_file(), encoding="utf-8")) == info
    print("✓ si el archivo del puente desaparece, se vuelve a escribir solo")
    with socket.create_connection(("127.0.0.1", info["port"]), timeout=5) as s:     # clave incorrecta
        s.sendall(b'{"token": "x", "tool": "estado", "args": {}}\n')
        buf = b""
        t0 = time.time()
        while not buf.endswith(b"\n") and time.time() - t0 < 5:
            app.processEvents()
            try:
                s.settimeout(0.05)
                buf += s.recv(4096)
            except socket.timeout:
                pass
    assert b"Clave incorrecta" in buf, buf

    def tool(name, args=None):
        res = call(app, MCP.handle, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                     "params": {"name": name, "arguments": args or {}}})["result"]
        return res, res["content"][0]["text"]

    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=d=8", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", vid], check=True)
    res, txt = tool("importar", {"rutas": [vid]})
    assert not res["isError"] and "id=" in txt, txt
    mid = txt.split("id=")[1].split()[0].strip(";")
    res, txt = tool("poner_en_linea_de_tiempo", {"media_id": mid, "inicio": 0})
    assert not res["isError"] and "Ctrl+Z" in txt, txt
    res, txt = tool("texto", {"contenido": "Rumor del día", "inicio": 1, "duracion": 2})
    assert not res["isError"], txt
    res, txt = tool("estado")
    assert "v.mp4" in txt and "Rumor del día" in txt and "Pistas" in txt, txt
    print("✓ importar, poner en la línea de tiempo y texto; «estado» lo cuenta todo")
    d0 = win.ctrl.project.duration()
    res, txt = tool("cortar", {"quitar_desde": 2, "quitar_hasta": 4})
    assert not res["isError"] and abs(win.ctrl.project.duration() - (d0 - 2)) < 0.05, (txt, win.ctrl.project.duration())
    fades = [(c.fx or {}).get(k, 0) for c in win.ctrl.project.clips.values() for k in ("fade_in", "fade_out")]
    assert not any(fades), fades                    # sin fundidos salvo que se pidan («fundido»: true)
    res, txt = tool("deshacer")
    assert not res["isError"] and abs(win.ctrl.project.duration() - d0) < 0.05, txt
    print("✓ cortar un tramo (sin fundidos que no se pidieron) y deshacerlo (como Ctrl+Z)")

    # herramientas de clips: listar, ajustar (volumen y fundidos), efectos de pista y borrar
    p = win.ctrl.project
    res, txt = tool("clips")
    assert not res["isError"] and "id=" in txt, txt
    vids = [c.id for c in p.clips.values() if c.text is None]
    res, txt = tool("ajustar_clips", {"ids": vids, "fundido_entrada": 0.5, "volumen": 50})
    assert not res["isError"], txt
    assert all(abs((win.ctrl.project.clips[i].fx or {}).get("fade_in", 0) - 0.5) < 1e-9 and
               abs(win.ctrl.project.clips[i].volume - 0.5) < 1e-9 for i in vids), txt
    res, txt = tool("clips")
    assert "fundidos 0.50" in txt and "vol 50 %" in txt, txt
    atr = next(t for t in win.ctrl.project.tracks if t.kind == "audio")
    res, txt = tool("ajustar_clips", {"pista": atr.id, "fundido_entrada": 0})     # quitar fundidos de una pista
    assert not res["isError"]
    assert not any((c.fx or {}).get("fade_in") for c in win.ctrl.project.clips_on(atr.id)), txt
    print("✓ «clips» y «ajustar_clips»: volumen y fundidos en lote (y quitarlos de toda una pista)")
    res, txt = tool("efectos_pista", {"pista": atr.id, "ecualizar": True})
    assert not res["isError"] and win.ctrl.project.track(atr.id).fx.get("eq"), txt
    n0 = len(win.ctrl.project.clips)
    txt_id = next(c.id for c in win.ctrl.project.clips.values() if c.text)
    res, txt = tool("borrar_clips", {"ids": [txt_id]})
    assert not res["isError"] and len(win.ctrl.project.clips) == n0 - 1, txt
    for _ in range(4):
        tool("deshacer")
    assert len(win.ctrl.project.clips) == n0 and not win.ctrl.project.track(atr.id).fx.get("eq")
    assert all(abs(win.ctrl.project.clips[i].volume - 1.0) < 1e-9 for i in vids)
    print("✓ «efectos_pista» (Ecualizar voz) y «borrar_clips» (un texto); todo se deshace con Ctrl+Z")
    res, txt = tool("captura", {"segundo": 1.5})
    assert not res["isError"] and len(res["content"]) == 2 and res["content"][1]["type"] == "image", txt
    assert len(res["content"][1]["data"]) > 1000
    print("✓ captura: devuelve la imagen del video en ese segundo (con el texto)")
    res, txt = tool("guardar")
    assert res["isError"] and ".eia" in txt
    eia = os.path.join(out, "prueba.eia")
    res, txt = tool("guardar", {"ruta": eia})
    assert not res["isError"] and os.path.exists(eia), txt
    print("✓ guardar: pide ruta si no hay archivo y nunca pisa uno existente")
    res, txt = tool("exportar", {"destino": "windows", "nombre": "prueba mcp"})
    assert not res["isError"] and "prueba mcp" in txt, txt
    t0 = time.time()
    while time.time() - t0 < 90:
        pump(app, 0.5)
        jobs = win.render_queue.jobs
        if jobs and jobs[-1]["status"] in ("done", "error"):
            break
    assert win.render_queue.jobs[-1]["status"] == "done", win.render_queue.jobs[-1]
    path = win.render_queue.jobs[-1]["opts"]["path"]
    assert os.path.exists(path)
    print(f"✓ exportar: en segundo plano y con nombre nuevo ({os.path.basename(path)})")
    os.remove(path)
    win.a_mcp.setChecked(False)
    pump(app, 0.2)
    assert not os.path.exists(bridge_file()) and win.claude_bridge.server is None
    print("✓ al apagarlo deja de escuchar")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
