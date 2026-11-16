<p align="center"><img src="editoria/assets/reclaimer_oscuro_512.png" width="200" alt="Reclaimer"></p>

<h1 align="center">Reclaimer</h1>

<p align="center">
Editor de video gratuito para Windows con un asistente de IA que <b>propone</b> y tú decides.<br>
Videos de YouTube, Shorts y edits musicales. Todo funciona en tu PC: sin cuentas, sin nube, sin marcas de agua.
</p>

<p align="center"><a href="https://github.com/DrownedMisfit/Reclaimer/releases/latest/download/Reclaimer_instalador.exe"><img src="https://img.shields.io/badge/%E2%AC%87%20Descargar-Windows%2010%20%2F%2011-orange?style=for-the-badge" alt="Descargar para Windows"></a><br><sub>Instalador con todo incluido · gratis · <a href="#-descargar-e-instalar-windows-10--11">cómo instalarlo</a></sub></p>

<p align="center"><a href="https://ko-fi.com/pigmeofurtivoyt"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Apóyame en Ko-fi"></a><br><sub>Es gratis. Si te sirve, puedes invitarme un café ☕</sub></p>

---

## Qué hace

- **Edición como en DaVinci Resolve**: páginas abajo, Inspector a la derecha, línea de tiempo con pistas,
  recortes, fundidos con tiradores, fotogramas clave, capas de ajuste, color y mezcla de audio.
- **Limpieza de la voz**: quita silencios, muletillas y tomas repetidas, con una vista previa antes de cortar.
  Ecualizador, reducción de ruido y voz separada del juego en grabaciones de OBS.
- **Subtítulos automáticos** (faster-whisper, local) y edición del video **desde el texto**: tachas una frase y se
  corta del video. Clic derecho en una palabra para corregirla.
- **Palabras clave**: una carpeta por tema (un juego, una compañía…); cuando lo dices en tu narración te ofrece ese
  material y «⚡ Agregar todo» lo pone justo donde lo dices. Pestaña «🗂 Carpetas» con lo de cada palabra.
- **Edits musicales automáticos**: cortes al ritmo de la canción, sin repetir escenas, con efectos variados y
  vistas previas de cada efecto. 🥁 Los golpes, compases y el drop se ven en la regla y el imán se pega a ellos.
- **Shorts**: encuadre vertical que sigue la acción, subtítulos grandes y elección de tramos.
- **Taller de miniaturas** integrado: propuestas a partir de tus imágenes, texto de impacto, recorte del
  personaje con IA, deformar en perspectiva y un buscador de PNG con fondo transparente.
- **Buscar momentos** en tu biblioteca por lo que se ve (texto, siluetas, imágenes de ejemplo).
- **Guía paso a paso (F1)**, un **🎓 proyecto de ejemplo** (Ayuda) para practicar sin tu material y clic derecho en
  cualquier botón → «❓ ¿Qué hace esto?».

Todo lo que hace la IA se puede deshacer con Ctrl+Z.

## ⬇ Descargar e instalar (Windows 10 / 11)

<p align="center"><a href="https://github.com/DrownedMisfit/Reclaimer/releases/latest/download/Reclaimer_instalador.exe"><b>⬇ Descargar Reclaimer (instalador, 1,7 GB)</b></a></p>

1. Abre el archivo que se descargó (**Reclaimer_instalador.exe**).
2. Si Windows dice **«Windows protegió su PC»**, pulsa **«Más información» → «Ejecutar de todas formas»**.
   Sale con casi todos los programas gratuitos que no pagan un certificado; el código completo está aquí, a la vista.
3. **Siguiente → Instalar.** No pide contraseña de administrador y **trae todo lo necesario** (no hay que instalar
   Python, FFmpeg ni nada más).
4. Abre **Reclaimer** desde el escritorio o el menú Inicio. La primera vez te enseña qué trae y qué es opcional.

- **Sin instalar (portátil):** descarga
  [Reclaimer_todo_en_uno.zip](https://github.com/DrownedMisfit/Reclaimer/releases/latest/download/Reclaimer_todo_en_uno.zip),
  descomprímelo (clic derecho → Extraer todo) y abre **Reclaimer.exe**. Sirve también desde un disco USB.
- **Desinstalar:** Configuración → Aplicaciones → Reclaimer. Tus proyectos y videos no se borran.
- **Necesitas:** Windows 10 u 11 de 64 bits y unos 4 GB libres (8 GB de RAM recomendados).
- **Motor de IA (opcional):** separar voz y música, recortar personajes y transcribir con la tarjeta gráfica.
  Se instala desde el propio programa, con su barra de progreso (Ayuda → ◈ Motor de IA). Descarga entre 3 y 6 GB.
- Todas las versiones: [página de descargas](https://github.com/DrownedMisfit/Reclaimer/releases).

<details>
<summary>Para programadores: instalar desde el código</summary>

1. Descarga este repositorio (botón verde **Code → Download ZIP**) y descomprímelo.
2. Doble clic en **`INSTALAR.bat`**: instala lo que falte (Python 3.12 y FFmpeg con winget, si no los tienes),
   comprueba que todo funciona y crea el acceso directo «Reclaimer» en el escritorio.
3. Abre Reclaimer con el acceso directo (o con **`INICIAR.bat`**). El motor de IA:
   **`motor_ia/INSTALAR_MOTOR_IA.bat`**.
</details>

El manual completo está en **[MANUAL.md](MANUAL.md)**.

## Licencia

Reclaimer es software libre bajo la **[GNU GPL v3](LICENSE)**: puedes usarlo, estudiarlo, modificarlo y
compartirlo; si distribuyes una versión modificada, tiene que seguir siendo libre y con su código.

Incluye o descarga material de terceros con sus propias licencias:

| Qué | Licencia |
|---|---|
| Letra Anton (`editoria/assets/fuentes`) | SIL Open Font License 1.1 |
| Diccionarios de español e inglés (`editoria/assets/diccionarios`) | ver los archivos de licencia de esa carpeta |
| PySide6 (Qt) | LGPL v3 |
| faster-whisper | MIT |
| Modelo IS-Net para recortar (se descarga al usarlo) | Apache 2.0 |
| FFmpeg (incluido en el instalador y el zip; su código fuente está en la misma página de descargas) | GPL v3 |
| Python 3.12 (incluido en el instalador y el zip) | PSF License |
| Narración del proyecto de ejemplo (voz sintética Kokoro) | Apache 2.0 (modelo); la grabación es de este proyecto |
| Clips del proyecto de ejemplo (se descargan de Pexels al crearlo, no van en el repositorio) | Licencia de Pexels |
