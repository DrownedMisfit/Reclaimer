"""
♻ Sacar de la Papelera de Windows un archivo borrado por error y devolverlo a su sitio original.

restaurar(ruta) busca en la Papelera el archivo que estaba en esa ruta (por su carpeta de origen y su nombre) y lo
devuelve allí. Sin ventanas (PowerShell oculto) e independiente del idioma de Windows: no usa el verbo «Restaurar»
del menú, mueve el archivo de la Papelera ($R…) a su ruta y quita su ficha ($I…), que es lo mismo que hace Windows.
"""
from __future__ import annotations

import os
import subprocess
import sys

_PS = r"""
$ErrorActionPreference = 'Stop'
$dest = $env:RECLAIMER_RESTAURAR
$dir = [System.IO.Path]::GetDirectoryName($dest)
$name = [System.IO.Path]::GetFileName($dest)
$base = [System.IO.Path]::GetFileNameWithoutExtension($dest)
$ext = [System.IO.Path]::GetExtension($dest)
$rb = (New-Object -ComObject Shell.Application).Namespace(10)
$hallado = $null
foreach ($it in $rb.Items()) {
  $origen = $rb.GetDetailsOf($it, 1)
  if (-not $origen) { continue }
  if ([string]::Compare($origen.TrimEnd('\'), $dir.TrimEnd('\'), $true) -ne 0) { continue }
  $p = $it.Path
  $mismo = ([string]::Compare($it.Name, $name, $true) -eq 0) -or
           (([string]::Compare($it.Name, $base, $true) -eq 0) -and
            ([string]::Compare([System.IO.Path]::GetExtension($p), $ext, $true) -eq 0))
  if ($mismo) { $hallado = $it; break }
}
if ($null -eq $hallado) { Write-Output 'NO'; exit 0 }
if (Test-Path -LiteralPath $dest) { Write-Output 'EXISTE'; exit 0 }
$r = $hallado.Path
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Move-Item -LiteralPath $r -Destination $dest
$i = Join-Path ([System.IO.Path]::GetDirectoryName($r)) ('$I' + [System.IO.Path]::GetFileName($r).Substring(2))
if (Test-Path -LiteralPath $i) { Remove-Item -LiteralPath $i -Force }
Write-Output 'OK'
"""


def restaurar(ruta: str, timeout: float = 60.0) -> str:
    """Devuelve «OK» (ya está en su sitio), «NO» (no está en la Papelera), «EXISTE» (ya hay un archivo ahí) o
    «ERROR: …»."""
    if sys.platform != "win32":
        return "ERROR: solo en Windows"
    ruta = os.path.abspath(ruta)
    if os.path.exists(ruta):
        return "EXISTE"
    env = dict(os.environ, RECLAIMER_RESTAURAR=ruta)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _PS], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERROR: {exc}"
    salida = (r.stdout or "").strip().splitlines()
    res = salida[-1].strip() if salida else ""
    if res in ("OK", "NO", "EXISTE"):
        return "OK" if res == "OK" and os.path.exists(ruta) else res
    return "ERROR: " + ((r.stderr or "").strip()[-200:] or "PowerShell no respondió")
