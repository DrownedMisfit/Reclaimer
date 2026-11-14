# Instalador de Reclaimer (lo abre INSTALAR.bat). Hace todo lo que falte, sin pasos a mano:
#   1. Python 3.12 (si no está, lo instala con winget, solo para tu usuario)
#   2. FFmpeg (si no está, lo instala con winget)
#   3. el entorno .venv con lo necesario (y, con tarjeta NVIDIA, lo que hace que la transcripción use la gráfica)
#   4. comprueba que todo arranca y crea los accesos directos «Reclaimer» (escritorio y menú Inicio)
# Se puede repetir cuando quieras: lo que ya está no se vuelve a instalar.
#   -SinPreguntas : responde «sí» a todo (instalación desatendida)
#   -Simular      : solo dice lo que haría; no instala ni cambia nada (para probar el instalador)
#   -SinAccesos   : no crea accesos directos
#   -FingirFalta python,ffmpeg,venv : (con -Simular) hace como si faltara eso, para probar cada camino
param([switch]$SinPreguntas, [switch]$Simular, [switch]$SinAccesos, [string[]]$FingirFalta = @())

# («Continue»: en Windows PowerShell 5.1, con «Stop», un aviso de pip por stderr pararía la instalación)
$ErrorActionPreference = "Continue"
$FingirFalta = @($FingirFalta | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
if (-not $Simular) { $FingirFalta = @() }
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Raiz
$Log = Join-Path $Raiz "instalar.log"
$Marca = Join-Path $Raiz ".venv\instalado.ok"      # solo existe si la última instalación terminó bien (INICIAR.bat la mira)
$env:PYTHONUTF8 = "1"                              # (rutas con tildes bien escritas en el registro)
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = "Reclaimer - Instalación" } catch {}

function Registrar($linea) { Add-Content -LiteralPath $Log -Value "$linea" -Encoding UTF8 }
function Escribir([string]$texto, [string]$color = "Gray") {
    Write-Host $texto -ForegroundColor $color
    Registrar ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $texto)
}
function Paso([int]$n, [string]$texto) { Escribir ""; Escribir "[$n/4] $texto" "Cyan" }
function Bien([string]$texto) { Escribir "   ✓ $texto" "Green" }
function Aviso([string]$texto) { Escribir "   ! $texto" "Yellow" }

function Fallo([string]$texto) {
    Escribir ""
    Escribir "✗ $texto" "Red"
    Escribir "  (Lo que pasó está en instalar.log, en esta misma carpeta.)" "Red"
    if (-not $SinPreguntas) { Read-Host "Pulsa Intro para cerrar" | Out-Null }
    exit 1
}

function Preguntar([string]$texto) {
    if ($SinPreguntas) { return $true }
    $r = Read-Host "   $texto (S/n)"
    return -not ($r -match '^\s*[nN]')            # (Intro a secas = sí)
}

function Abrir-Pagina([string]$url) { if (-not $SinPreguntas) { Start-Process $url } }

function Hay-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Instalar-Winget([string]$id, [string]$nombre) {
    # devuelve $true si winget dice que lo instaló (o ya estaba)
    if ($Simular) { Aviso "(simulación) aquí se instalaría $nombre con winget ($id)"; return $true }
    if (-not (Hay-Winget)) { return $false }
    Escribir "   Instalando $nombre… (puede tardar unos minutos)"
    $base = @("install", "-e", "--id", $id, "--source", "winget", "--accept-package-agreements",
              "--accept-source-agreements", "--silent")
    & winget @base --scope user 2>&1 | ForEach-Object { Registrar $_ }
    if ($LASTEXITCODE -eq 0) { return $true }
    # (algunos paquetes no tienen instalador «solo para tu usuario»: se intenta sin «--scope»)
    & winget @base 2>&1 | ForEach-Object { Registrar $_ }
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------- 1. Python
function Version-Python([string]$exe, [string[]]$extra = @()) {
    try {
        $v = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$v" -match '^3\.(\d+)$') { return [int]$Matches[1] }
    } catch {}
    return -1
}

function Buscar-Python {
    # devuelve @(ejecutable, argumentos) de un Python 3.10–3.12 (con lo que usa Reclaimer, 3.13+ aún da problemas)
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($m in 12, 11, 10) {
            if ((Version-Python $py.Source @("-3.$m")) -eq $m) { return @($py.Source, @("-3.$m")) }
        }
    }
    $candidatos = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidatos += $cmd.Source }   # (WindowsApps = el atajo a la Tienda)
    foreach ($m in 12, 11, 10) {
        $candidatos += Join-Path $env:LOCALAPPDATA "Programs\Python\Python3$m\python.exe"
        $candidatos += Join-Path $env:ProgramFiles "Python3$m\python.exe"
    }
    foreach ($c in $candidatos) {
        if ($c -and (Test-Path -LiteralPath $c)) {
            $m = Version-Python $c
            if ($m -ge 10 -and $m -le 12) { return @($c, @()) }
        }
    }
    return $null
}

# ---------------------------------------------------------------- 2. FFmpeg (lo busca igual que el programa)
function Buscar-FFmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $paquetes = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $paquetes) {
        $f = Get-ChildItem -LiteralPath $paquetes -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match 'FFmpeg' -and $_.Directory.Name -eq 'bin' } | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null
}

function Venv-Sano([string]$exe) {
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    $r = & $exe -c "print(1)" 2>$null
    return ($LASTEXITCODE -eq 0 -and "$r" -eq "1")
}

# ================================================================ inicio
Set-Content -LiteralPath $Log -Value "Instalación de Reclaimer — $(Get-Date)" -Encoding UTF8
Escribir "Reclaimer — instalación" "White"
Escribir "Instala lo que falte. Se puede repetir cuando quieras: lo que ya está no se repite."
if ($Simular) { Aviso "Modo simulación: no se instala ni se cambia nada." }
if ($Raiz -match 'OneDrive') {
    Aviso "La carpeta está dentro de OneDrive: se sincronizarán miles de archivos. Mejor muévela fuera (p. ej. C:\Reclaimer)."
}
if ($Raiz.Length -gt 100) {
    Aviso "La ruta de la carpeta es muy larga; si algo falla al instalar, muévela a una más corta (p. ej. C:\Reclaimer)."
}

Paso 1 "Python"
$python = if ($FingirFalta -contains "python") { $null } else { Buscar-Python }
if ($python) {
    Bien ("Python encontrado: " + $python[0] + " " + ($python[1] -join " "))
} else {
    Aviso "No encuentro Python 3.12 (hace falta para que Reclaimer funcione)."
    if (-not (Hay-Winget) -and -not $Simular) {
        Abrir-Pagina "https://www.python.org/downloads/release/python-31210/"
        Fallo "No puedo instalarlo solo (este Windows no tiene «winget»). Instala Python 3.12 desde python.org (marca «Add python.exe to PATH») y vuelve a abrir INSTALAR.bat."
    }
    if (-not (Preguntar "¿Instalo Python 3.12 ahora?")) { Fallo "Sin Python no se puede seguir." }
    if (-not (Instalar-Winget "Python.Python.3.12" "Python 3.12") -and -not $Simular -and -not (Buscar-Python)) {
        Fallo "No se pudo descargar Python 3.12 (¿sin internet?). Vuelve a abrir INSTALAR.bat cuando tengas conexión."
    }
    if ($Simular) { $python = @("python", @()) }
    else {
        $python = Buscar-Python
        if (-not $python) { Fallo "Se instaló Python pero no lo encuentro. Cierra esta ventana y abre INSTALAR.bat otra vez." }
        Bien ("Python instalado: " + $python[0])
    }
}

Paso 2 "FFmpeg (para leer y exportar video)"
$ffmpeg = if ($FingirFalta -contains "ffmpeg") { $null } else { Buscar-FFmpeg }
if ($ffmpeg) {
    Bien "FFmpeg encontrado: $ffmpeg"
} else {
    Aviso "No encuentro FFmpeg."
    if (-not (Hay-Winget) -and -not $Simular) {
        Abrir-Pagina "https://www.gyan.dev/ffmpeg/builds/"
        Fallo "No puedo instalarlo solo (este Windows no tiene «winget»). Descarga FFmpeg de gyan.dev, ponlo en el PATH y vuelve a abrir INSTALAR.bat."
    }
    if (-not (Preguntar "¿Instalo FFmpeg ahora?")) { Fallo "Sin FFmpeg Reclaimer no puede abrir ni exportar video." }
    if (-not (Instalar-Winget "Gyan.FFmpeg" "FFmpeg") -and -not $Simular -and -not (Buscar-FFmpeg)) {
        Fallo "No se pudo descargar FFmpeg (¿sin internet?). Vuelve a abrir INSTALAR.bat cuando tengas conexión."
    }
    if (-not $Simular) {
        $ffmpeg = Buscar-FFmpeg
        if (-not $ffmpeg) { Fallo "Se instaló FFmpeg pero no lo encuentro. Cierra esta ventana y abre INSTALAR.bat otra vez." }
        Bien "FFmpeg instalado: $ffmpeg"
    }
}

Paso 3 "Lo que usa Reclaimer (en la carpeta .venv)"
$venvDir = Join-Path $Raiz ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$hayVenv = (Test-Path -LiteralPath $venvPy) -and $FingirFalta -notcontains "venv"
if ($Simular) {
    if ($hayVenv) { Aviso "(simulación) .venv ya existe: aquí se actualizaría lo que falte" }
    else { Aviso "(simulación) aquí se crearía .venv y se instalaría requirements.txt" }
} else {
    if (Test-Path -LiteralPath $Marca) { Remove-Item -LiteralPath $Marca -Force }
    if ((Test-Path -LiteralPath $venvDir) -and -not (Venv-Sano $venvPy)) {
        Aviso "El entorno .venv está dañado (¿se cortó una instalación o se desinstaló Python?): lo creo de nuevo."
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Escribir "   Creando el entorno…"
        $exe = $python[0]; $arg = @($python[1]) + @("-m", "venv", $venvDir)
        & $exe @arg 2>&1 | ForEach-Object { Registrar $_ }
        if (-not (Venv-Sano $venvPy)) { Fallo "No se pudo crear el entorno de Python (.venv)." }
    }
    Escribir "   Descargando e instalando… (la primera vez tarda unos minutos)"
    & $venvPy -m pip install --upgrade pip 2>&1 | ForEach-Object { Registrar $_ }
    & $venvPy -m pip install -r requirements.txt 2>&1 | ForEach-Object {
        Registrar $_
        if ("$_" -match '^Collecting\s+(\S+)') { Write-Host ("   · " + $Matches[1]) -ForegroundColor DarkGray }
    }
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo instalar lo necesario (¿sin internet?). Vuelve a abrir INSTALAR.bat cuando tengas conexión." }
    # Leer el texto de las miniaturas: sin sus dependencias (traería un segundo OpenCV que rompe el de arriba)
    & $venvPy -m pip install --no-deps "rapidocr-onnxruntime>=1.4" 2>&1 | ForEach-Object { Registrar $_ }
    $ocr = ($LASTEXITCODE -eq 0)
    & $venvPy -m pip install pyclipper shapely six pyyaml pillow 2>&1 | ForEach-Object { Registrar $_ }
    if (-not ($ocr -and $LASTEXITCODE -eq 0)) { Aviso "No se pudo instalar la lectura de texto de miniaturas (opcional)." }
    # Instalaciones antiguas: un segundo OpenCV (sin contrib) encima del bueno rompe el escalado → se quita
    $sobra = @("opencv-python", "opencv-python-headless", "opencv-contrib-python") | Where-Object {
        & $venvPy -m pip show $_ 2>$null | Out-Null; $LASTEXITCODE -eq 0 }
    if ($sobra) {
        Escribir "   Quitando un OpenCV repetido ($($sobra -join ', '))…"
        & $venvPy -m pip uninstall -y @sobra 2>&1 | ForEach-Object { Registrar $_ }
        & $venvPy -m pip install --force-reinstall --no-deps "opencv-contrib-python-headless>=4.9" 2>&1 | ForEach-Object { Registrar $_ }
    }
    Bien "Listo"
    $nvidia = $false
    try { $nvidia = [bool]((Get-CimInstance Win32_VideoController).Name -match 'NVIDIA') } catch {}
    if ($nvidia) {
        Escribir "   Tienes tarjeta NVIDIA: instalo lo que hace que la transcripción vaya por la gráfica…"
        & $venvPy -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10" 2>&1 | ForEach-Object { Registrar $_ }
        if ($LASTEXITCODE -eq 0) { Bien "La transcripción usará tu tarjeta NVIDIA" }
        else { Aviso "No se pudo; la transcripción irá por el procesador (más lenta, pero funciona)." }
    }
}

Paso 4 "Comprobación y accesos directos"
if (-not $Simular -or $hayVenv) {
    $prueba = "import PySide6, numpy, cv2, onnxruntime, faster_whisper; assert hasattr(cv2, 'dnn_superres'), 'OpenCV sin contrib'; print('ok')"
    $res = & $venvPy -c $prueba 2>&1
    $codigo = $LASTEXITCODE
    $res | ForEach-Object { Registrar $_ }
    if ($codigo -ne 0) {
        if ($Simular) { Aviso "(simulación) la comprobación fallaría: falta algo en .venv" }
        else { Fallo "Algo no quedó bien instalado. Vuelve a abrir INSTALAR.bat (repite solo lo que falta)." }
    } else { Bien "Todo lo necesario se carga bien" }
}

$pyw = Join-Path $Raiz ".venv\Scripts\pythonw.exe"
$icono = Join-Path $Raiz "editoria\assets\reclaimer.ico"
$destinos = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
if ($SinAccesos) {
    Aviso "Sin accesos directos (-SinAccesos)."
} elseif ($Simular) {
    Aviso "(simulación) aquí se crearía «Reclaimer» en el escritorio y en el menú Inicio"
} else {
    $creados = 0
    $sh = New-Object -ComObject WScript.Shell
    foreach ($d in $destinos) {
        if (-not $d -or -not (Test-Path -LiteralPath $d)) { continue }
        try {
            $lnk = $sh.CreateShortcut((Join-Path $d "Reclaimer.lnk"))
            $lnk.TargetPath = $pyw
            $lnk.Arguments = '"' + (Join-Path $Raiz "main.py") + '"'
            $lnk.WorkingDirectory = $Raiz
            if (Test-Path -LiteralPath $icono) { $lnk.IconLocation = $icono }
            $lnk.Description = "Reclaimer, editor de video"
            $lnk.Save()
            $creados++
        } catch { Registrar "No se pudo crear el acceso directo en $d : $_" }
    }
    if ($creados -gt 0) { Bien "Acceso directo «Reclaimer» creado ($creados)" }
    else { Aviso "No pude crear accesos directos; abre el programa con INICIAR.bat." }
}

if (-not $Simular) { Set-Content -LiteralPath $Marca -Value (Get-Date) -Encoding UTF8 }
Escribir ""
if ($Simular) { Escribir "✓ Fin de la simulación (no se cambió nada)." "Green" }
else { Escribir "✓ Listo. Abre Reclaimer con el acceso directo del escritorio (o con INICIAR.bat)." "Green" }
if (-not $Simular -and -not $SinPreguntas) {
    if (Preguntar "¿Abro Reclaimer ahora?") {
        Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $Raiz "main.py") + '"') -WorkingDirectory $Raiz
    }
}
exit 0
