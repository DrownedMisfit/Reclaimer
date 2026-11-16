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


def _bridge_files() -> list[str]:
    """Dónde puede estar el archivo del puente, por orden: la carpeta de datos de la versión «todo
    en uno» (este archivo dentro de app\\, con Reclaimer.exe y datos\\ al lado); la de este Reclaimer; y la copia que
    Reclaimer deja siempre en %LOCALAPPDATA%\\Reclaimer."""
    from editoria.core.paths import PROGRAM_DIR
    out = []
    if not (os.environ.get("EDITORIA_DATOS") or os.environ.get("RECLAIMER_DATOS")) \
            and (PROGRAM_DIR.parent / "Reclaimer.exe").exists():
        out.append(os.path.join(str(PROGRAM_DIR.parent / "datos"), "puente_claude.json"))
    from editoria.core.paths import app_data_dir
    out.append(os.path.join(str(app_data_dir()), "puente_claude.json"))
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    out.append(os.path.join(base, "Reclaimer", "puente_claude.json"))
    return out


def _bridge_file() -> str:
    """El primero que exista (o el de la carpeta de datos, si no hay ninguno)."""
    files = _bridge_files()
    return next((f for f in files if os.path.exists(f)), files[-2])


def _connect():
    """Prueba los archivos del puente EN ORDEN y se queda con el primero que conecta (uno viejo, de un Reclaimer que
    se cerró de golpe, no tapa la copia del que está abierto). Devuelve (socket, clave) o (None, motivo)."""
    found = incomplete = False
    last = None
    for path in _bridge_files():
        try:
            with open(path, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        found = True
        try:
            port, token = int(info["port"]), str(info["token"])
        except (KeyError, TypeError, ValueError, AttributeError):
            incomplete = True
            continue
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=10), token
        except OSError as exc:
            last = exc
    if not found:
        return None, ("Reclaimer no está abierto, o tiene apagado «🤝 Dejar que Claude edite conmigo» (menú Ayuda). "
                      "Pídele al usuario que lo abra y lo active.")
    if incomplete and last is None:
        return None, ("El archivo del puente de Reclaimer está incompleto. Pídele al usuario que apague y vuelva a "
                      "encender «🤝 Dejar que Claude edite conmigo» (menú Ayuda).")
    return None, (f"No pude hablar con Reclaimer ({last}). ¿Está abierto y con «🤝 Dejar que Claude edite conmigo» "
                  "activado?")


def call_bridge(tool: str, args: dict, timeout: float = 300.0) -> dict:
    """Manda una orden a Reclaimer y espera la respuesta {"ok", "text", "image"?}."""
    conn, token = _connect()
    if conn is None:
        return {"ok": False, "text": token}
    try:
        with conn as s:
            s.settimeout(timeout)
            msg = json.dumps({"token": token, "tool": tool, "args": args}, ensure_ascii=False) + "\n"
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
