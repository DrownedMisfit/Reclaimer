"""
🤝 Servidor MCP de Reclaimer: lo arranca la app de Claude (o Claude Code) para que Claude pueda editar contigo.

No hace nada por sí solo: pasa cada orden al «puente» que vive DENTRO de Reclaimer (127.0.0.1, con una clave que
cambia en cada arranque) y devuelve la respuesta. Si Reclaimer no está abierto o tienes apagado
«🤝 Dejar que Claude edite conmigo», responde que no puede. Reclaimer funciona igual sin esto.

Protocolo: MCP (JSON-RPC 2.0, una línea por mensaje, por la entrada/salida estándar). Sin librerías de fuera.
Uso (lo pone la configuración de Claude):  F:\\Reclaimer\\.venv\\Scripts\\python.exe F:\\Reclaimer\\mcp_reclaimer.py
"""
from __future__ import annotations

import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from editoria import mcp_tools as T  # noqa: E402


def _bridge_file() -> str:
    from editoria.core.paths import app_data_dir
    return os.path.join(str(app_data_dir()), "puente_claude.json")


def call_bridge(tool: str, args: dict, timeout: float = 300.0) -> dict:
    """Manda una orden a Reclaimer y espera la respuesta {"ok", "text", "image"?}."""
    try:
        with open(_bridge_file(), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return {"ok": False, "text": "Reclaimer no está abierto, o tiene apagado «🤝 Dejar que Claude edite conmigo» "
                                     "(menú Ayuda). Pídele al usuario que lo abra y lo active."}
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=10) as s:
            s.settimeout(timeout)
            msg = json.dumps({"token": info["token"], "tool": tool, "args": args}, ensure_ascii=False) + "\n"
            s.sendall(msg.encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "text": f"No pude hablar con Reclaimer ({exc}). ¿Está abierto y con «🤝 Dejar que Claude "
                                     "edite conmigo» activado?"}


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                        # notificación (p. ej. notifications/initialized): sin respuesta
        return None
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion") or T.PROTOCOL
        result = {"protocolVersion": want, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": T.SERVER_NAME, "version": "1.0"}, "instructions": T.INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": T.TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in T.NAMES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Herramienta desconocida: {name}"}}
        r = call_bridge(name, args)
        content = [{"type": "text", "text": str(r.get("text", ""))}]
        if r.get("image"):
            content.append({"type": "image", "data": r["image"], "mimeType": "image/png"})
        result = {"content": content, "isError": not r.get("ok", False)}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método no disponible: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON no válido"}}
        else:
            try:
                out = handle(msg)
            except Exception as exc:  # noqa: BLE001 - el servidor nunca se cae por una orden
                out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(exc)}}
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
