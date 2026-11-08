# Reclaimer

![Reclaimer](editoria/assets/reclaimer_oscuro_512.png)

Editor de video para Windows 11 pensado para videos de YouTube (crítica y análisis de videojuegos),
YouTube Shorts y edits musicales, con un asistente de IA que **propone** ediciones y nunca quita el
control al usuario. La interfaz se parece a DaVinci Resolve (páginas abajo, Inspector a la derecha).

**¿No sabes qué hace algo?** Clic derecho sobre cualquier botón o panel → «❓ ¿Qué hace esto?».

## Cómo abrirlo

Doble clic en **`INICIAR.bat`**.
(Si algún día mueves la carpeta a otro PC: primero `INSTALAR.bat`, después `INICIAR.bat`.)

## Uso básico

1. **Importar**: arrastra tu narración y tu carpeta de clips al panel *Biblioteca*
   (o usa «＋ Archivos» / «＋ Carpeta»). Los clips se ordenan solos por el nombre de sus carpetas
   (`Gameplay`, `Cinematics`, `Music`, `SFX`, `Images`…). Las subcarpetas (`Combat`, `Marcus`…)
   se convierten en etiquetas que puedes buscar.
2. **Montar**: arrastra clips desde la biblioteca a la timeline (o doble clic = se añade en el cabezal).
3. **Editar**: mueve clips arrastrándolos, recorta arrastrando sus bordes, corta con **S**.
4. **Proteger**: 🔒 en una pista o **Ctrl+L** en un clip = bloqueado (nadie, ni la IA, podrá tocarlo).
5. **Exportar**: **Ctrl+E** → elige preset → Exportar (usa tu tarjeta gráfica por defecto: NVIDIA, AMD o Intel).

## 📖 Guía paso a paso (F1)

**F1** (o Ayuda → Guía paso a paso) abre la guía: lecciones cortas («Primeros pasos», «Cortar y recortar»,
«Limpiar la narración», «Subtítulos», «Miniatura»…) con un buscador («¿qué quieres hacer?», sin preocuparte
por las tildes). En cada paso la guía **te lleva a la opción** (abre su panel o su pestaña), la marca con un
**recuadro naranja tenue** que no estorba (puedes hacer clic a través) y muestra una **imagen real** de esa
opción. «📍 Muéstrame» la vuelve a marcar. La guía flota a un lado; arrástrala o acóplala donde quieras.
La primera vez que abres Reclaimer aparece sola. **Ctrl+F1** = todos los atajos de teclado; clic derecho en
cualquier botón → «❓ ¿Qué hace esto?».

## Paneles a tu gusto (como en DaVinci Resolve)

Por defecto: **[Medios · Efectos · IA] | [Visor] | [Inspector · Limpieza · Texto · Subtítulos · Historial]**
arriba y la **línea de tiempo sola abajo**, a todo lo ancho. Cada panel se arrastra por su pestaña o su
título a otro sitio (también junto a la línea de tiempo, si quieres), se junta con otros en pestañas, se
saca como ventana flotante (doble clic en su título lo devuelve) y se cierra o abre desde el menú
**Ventana**. La distribución se recuerda; **Ventana → Restablecer la distribución de paneles** la deja
como al principio. La barra de abajo (Medios · Efectos · Editar · Audio · IA · Entrega) muestra los
paneles de cada área.

**Calidad de reproducción** (selector «Calidad» del visor, o Reproducción → Resolución de la línea de
tiempo): «Media» o «Un cuarto» reproducen copias ligeras de tus videos (se crean solas en segundo plano)
para editar con fluidez material 1440p/4K. **Exportar usa siempre los originales.**
Timeline → «↕ Altura de las pistas de video» y «Forma de onda → pistas de audio compactas» hacen la línea
de tiempo más pequeña.

## Línea de tiempo

- **Pistas**: un proyecto nuevo trae una sola pista de audio. Encima de los nombres: **➕ Pista** (video o audio),
  **🎞 ↕** (alto de las pistas de video) y **🔊 ↕** (alto de las de audio): barrita para el tamaño exacto, tamaños
  rápidos o rueda del ratón. Arrastra algo a la franja de abajo de la última pista y se crea una pista nueva. **Doble clic en el nombre** = renombrar a tu
  gusto, con sugerencias (Narración, Música, Efectos…) que le dan su papel: «Música» baja sola al hablar,
  «Efectos» recibe los sonidos. Si la IA necesita pista para música o sonidos, crea una nueva (nunca sobre tu voz).

- **Rectángulo de selección**: arrastra desde una zona vacía y selecciona todo lo que toque (video, audio,
  imágenes, textos). Ctrl = añadir a la selección.
- **Huecos**: clic en un hueco entre clips → queda marcado; **Supr** lo elimina y lo de detrás se desplaza a la
  izquierda hasta tocar el clip anterior (su sonido vinculado también, sin pisar nada en su pista). Clic
  derecho → «Eliminar todos los huecos de esta pista». Funciona igual en las pistas de **audio** (narración,
  música, sonido de los videos). **Timeline → «⇤ Eliminar huecos»**: en todas las pistas de audio, en todas las de
  video, en todas o solo en la pista del clip elegido (un solo Ctrl+Z). Al cerrar un hueco del sonido de un video,
  su imagen lo acompaña para no desincronizarse.
- **Sin sobrescribir sin querer**: al arrastrar, un clip se detiene al tocar a otro; al soltar archivos
  donde ya hay algo, van a otra pista libre del mismo tipo (o a una nueva).
- **Desde Windows**: arrastra videos, audios o imágenes del Explorador directamente a la línea de tiempo;
  cada uno va a su tipo de pista (MP4 → video + su sonido debajo, MP3/WAV → audio, PNG/JPG → video).

## Novedades de la línea de tiempo y la imagen (2026-10-06)

- **Tira de miniaturas**: a lo largo de cada clip de video se ven sus fotogramas (el de cada momento), no solo el
  primero. Se prepara una vez por video, en segundo plano.
- **Indicador de la IA** (contorno naranja, % y ■): en la barra de debajo de la imagen, a la derecha.
- **Texto que desenfoca lo de debajo**: Inspector ▸ Texto ▸ «Desenfocar lo de debajo» (activado en tus textos).
- **🟩 Pantalla verde**: Efectos ▸ «Quitar fondo de color» (detecta el color solo; Tolerancia y Suavidad).
- **🧩 Clip compuesto «cocinado»**: selecciona varios clips → clic derecho → «Hacer clip compuesto». Se renderizan
  (efectos, color, textos, transiciones y sonido) a UN video que los sustituye: el visor va más fluido. Clic
  derecho → «Deshacer clip compuesto» devuelve los originales. Los videos cocinados van a `datos\compuestos`.
- Estilo de edit «🔥 Agresivo / Intenso» (antes «Phonk») y 7 estilos nuevos: 🎭 Dramático, 🌧 Triste / melancólico,
  🌑 Misterioso / oscuro, ⚠ Tenso, 🕰 Nostálgico, 🌅 Inspirador / épico y ◻ Minimalista.
- **Clic derecho en un hueco → ✨ IA**: «💡 Ver sugerencias para este hueco» / «⚡ Rellenar este hueco con lo mejor»
  (según lo que DICES en ese hueco) y «🔎 Buscar en Medios: «tu frase»».
- **⌨ Atajos → «⬇ Traer mis atajos de DaVinci Resolve…»**: lee tu keyboard.preset.xml de Resolve (solo lectura)
  y te deja elegir qué atajos copiar (Ctrl+B dividir, Ctrl+T transición, T recorte, Mayús+Z ajustar…).
- **IA que escucha tus palabras + el movimiento**: si dices «paisaje», «ciudad», «edificio»… la búsqueda y el
  B-roll prefieren los momentos quietos; con «personaje», «pelea», «carro»… los que tienen movimiento; con
  «gameplay» / «cinemática», los clips de ese tipo (ligero: usa el movimiento que ya se guarda de cada video).
- **¿Gameplay o cinemática? ¿Primera o tercera persona?** Al analizar tus clips se usan pistas sencillas (rápidas):
  HUD fijo en los bordes (vida, mapa, munición) → gameplay; barras negras → cinemática; arma/manos fijas abajo en
  el centro → primera persona; el centro cambia menos que lo de alrededor → tercera persona. Si son claras,
  mandan sobre la IA de imágenes.
- **🧍 Quitar el fondo quieto** (Efectos, junto a la pantalla verde): sin tela verde, con la cámara fija (facecam,
  plano quieto) aprende el fondo vacío y quita lo que no se mueve. Si la cámara se mueve, te avisa.
- **✨ Ideas para esto** (clic derecho en uno o varios clips): cómo meterlo encima del video con un clic —
  entrada (desde la derecha, abajo, izquierda, arriba o apareciendo suave), sombra y contorno, centrado o en una
  esquina; una captura de texto (tuit, noticia) se reconoce y se propone como tarjeta; varios clips se escalonan.
- **⊞ Composición** (junto a «Guías»): elige 2, 3, 4, 6 o 9 huecos; el visor enseña un «+» en cada uno. Arrastra
  desde Medios a un hueco (imagen, video o GIF) y se pone ahí desde el cabezal; fuera de los huecos va de fondo.
  Van en pistas propias («⊞ Composición» arriba, «⊞ Fondo» abajo) para no mezclarse con tu línea principal.
- **▦ Guías** (junto a «Calidad»): tercios, centro, zona segura de Shorts/TikTok y borde del encuadre (no se exportan).

## Edición como en DaVinci Resolve

- **J / K / L**: atrás / parar / adelante (pulsa otra vez = 2×, 4×, 8×; se ve «▶▶ 2×» en el visor).
- **I / O**: entrada y salida de un tramo (banda en la regla). Mayús+I / Mayús+O = ir a ellas, Alt+X = quitarlas,
  **Alt+/** = reproducir el tramo, **🔁 / Ctrl+/** = en bucle, Editar → «Quitar el tramo marcado» lo borra
  cerrando el hueco, y al exportar puedes elegir **solo el tramo marcado**. Se guardan con el proyecto.
- **Velocidad (R)**: Inspector → «Velocidad»: 10 %–400 % (50 % = cámara lenta, 200 % = rápido), **◀ hacia atrás**
  y «mover lo que viene detrás». El sonido vinculado cambia igual, sin voz de ardilla. **Mayús+R** congela la
  imagen desde el cabezal hasta el final del clip (el sonido sigue). En el clip se ve «50%», «◀» o «❄».
  También con clic derecho → «🐢 Velocidad».
- **Transiciones** (Efectos → ⧉ Transiciones, clic derecho en un clip → «⧉ Transición», o **Alt+T**): disolver,
  fundido a negro, destello blanco, latigazo, zoom, deslizar, barrido, círculo, reloj, pixelado, viento, aplastar…
  Se centran en el corte (el video no cambia de duración); si el archivo no tiene más material, se alarga el
  borde con una imagen quieta. En la línea de tiempo es una pajarita sobre el corte; en el visor se aproxima con
  un fundido y **«▶ Ver la transición»** prepara el resultado exacto en unos segundos.
- **Recortes avanzados** (herramienta **⇿**, Mayús+T): borde = **ripple** (lo de detrás se mueve), Mayús+borde en
  un corte = **roll** (mueve el corte), centro = **slip** (otra parte del video, sin moverse), Mayús+centro =
  **slide** (se desliza entre sus vecinos). Con la herramienta normal: Ctrl+borde = ripple, Ctrl+Mayús+borde = roll.
- **Copiar / cortar / pegar** clips (Ctrl+C / Ctrl+X / Ctrl+V en el cabezal, sin tapar nada) y **Alt+V · Pegar
  atributos**: efectos, encuadre/zoom, volumen y ecualizador, velocidad o transición de un clip a otros.
- **Solo y vúmetros**: en las pistas de audio, **S** = solo (solo suenan esas; la Revisión avisa si exportas así)
  y **M** = silenciar. Cada pista muestra su nivel con una barrita, y el visor un medidor en dB.
- El bloqueo de clips pasa a **Ctrl+L** (la L es ahora «reproducir», como en Resolve).

## Imagen y sonido «Studio»

- **Color por clip** (Inspector → pestaña **Color**): exposición, contraste, saturación, temperatura, tinte, sombras
  y luces; **✨ Color automático** (mira el fotograma del cabezal); **🎨 LUT .cube** con su intensidad; «👁 Ver sin
  corrección» para comparar. El visor usa la misma tabla de color que la exportación: lo que ves es lo que sale.
  Para repetirlo en otros clips: Ctrl+C y Alt+V → «Color».
- **📊 Gráficas** (panel nuevo, como los scopes de Resolve): forma de onda, desfile RGB, histograma y vectorscopio
  del fotograma del cabezal, con avisos («quemado», «muy oscuro», «muy saturado»).
- **〰 Curvas** (Mayús+C): la línea de **volumen** en los clips de audio y de **opacidad** en los de video; clic =
  punto, arrastrar = moverlo, clic derecho = borrarlo, Mayús+arrastrar = subir/bajar toda. Inspector → Video:
  **opacidad** y **modo de fusión** (pantalla, añadir, multiplicar, superponer, luz suave…).
- **Cámara lenta suave** (por debajo del 100 %: inventa fotogramas al exportar, como Speed Warp) y **📈 rampas de
  velocidad** (rápido → lento → rápido, entrar/salir de cámara lenta, acelerar, frenar). «▶ Ver cómo queda»
  prepara unos segundos exactos.
- **🛠 Mejorar imagen** (Inspector → Clip): **reducir ruido**, **estabilizar** (analiza el temblor) y **✂ detectar
  cortes de escena** (corta un tráiler o una cinemática en sus planos, o pone marcadores).
- **🚀 Cola de exportación** (Archivo, Ctrl+Mayús+E; o «➕ Añadir a la cola» al exportar): varias exportaciones
  seguidas (video, solo audio, tramo marcado, 4K), cada una con el proyecto tal como estaba al añadirla.

## 🧹 Caché y diagnóstico (Ayuda → Caché y diagnóstico)

- **Caché**: cuánto ocupa cada cosa que guarda Reclaimer. «🧹 Borrar todo lo que se rehace solo» libera las copias
  ligeras, formas de onda, miniaturas, vistas previas y tablas de color sin perder nada. Los análisis de la IA y de
  estabilización se pueden borrar con aviso (cuesta rehacerlos). Lo que usan tus miniaturas o proyectos (recortes,
  fotogramas de miniaturas, sonidos generados) no se borra desde aquí; los modelos y las copias de seguridad solo
  se muestran (📂 abre su carpeta).
- **Diagnóstico**: versión y ruta de FFmpeg, con qué tarjeta exporta (NVIDIA, AMD o Intel) y dónde transcribe, IA local, espacio libre, archivos del
  proyecto que faltan y tamaño del historial. «📋 Copiar informe» por si algo falla.
- El **historial de deshacer** se guarda comprimido (y sin duplicar): un proyecto largo ya no se come la memoria.

## 🔠 Letra más grande (botón «🔠 Letra» arriba a la derecha, o Ventana → Tamaño de letra)

Dos controles que se ven al momento y se recuerdan: **Paneles, menús y ventanas** (todo lo que no es la línea de
tiempo) y **Global** (todo, también la línea de tiempo, cuyas pistas y cabeceras crecen para que quepa).

## 🔎 Buscar momentos (panel «Momentos», Ctrl+Mayús+F)

Busca **dónde aparece algo** en tus medios: por texto, por una **imagen de referencia** o por un nombre que
la IA ya aprendió. Cada miniatura es una **aparición con inicio y fin**. Puedes verla, recortarla,
**insertarla en el cabezal** (en una pista libre), **reemplazar** el clip seleccionado, **añadirla después**
o guardarla en ⭐ favoritos. También con clic derecho: en la transcripción («Buscar material para esta
frase») y en la línea de tiempo (submenú **✨ IA**: momentos parecidos a un clip, material para lo que dices
ahí, más impacto visual, rehacer el B-roll solo de una parte).

**🌐 Internet** (en el mismo panel, «Buscar en»): imágenes de Openverse con licencias libres que permiten uso
comercial y modificación. Se muestran como resultados y **no se descarga nada hasta que pulses «Usar»**;
entonces van a Vídeos/Reclaimer/Imágenes de internet con su crédito en «créditos.txt». También hay un botón
para abrir la búsqueda en Google Imágenes (ahí revisas tú la licencia).

## Autoedición (tarjeta ✨ de la pestaña IA)

Además de lo de la primera versión automática, eliges: **tipo de edición** (comentario, review, ensayo,
gameplay comentado, Short, video largo, cinemático…), **ritmo** (rápido, normal, pausado), **material**
(mezclar automáticamente o priorizar gameplay/cinemáticas/imágenes), **qué cortar** (silencios,
respiraciones, muletillas, repeticiones; nunca a media palabra) y **estilo visual**: Natural, Dinámico (zooms
de golpe) o Cinematográfico (zoom lento, fundidos y whoosh en los cambios de tema, cortes al ritmo de la
música).

La pestaña **IA** empieza con un **mapa**: cada herramienta, qué hace, qué encontró ya y un clic para usarla.

## 🖼 Miniaturas (botón «Miniatura» de abajo, o Archivo → Crear miniatura, Ctrl+Mayús+M)

Un taller aparte (no interfiere con la edición) para YouTube (1280×720) o Shorts (1080×1920):

- **✨ Propuestas**: frases cortas sugeridas a partir del título y los temas (no copia el título: p. ej.
  «¿DÓNDE ESTÁN?», «ANTES vs AHORA», el nombre del juego) y **3 composiciones** con tus mejores fotogramas
  (A: personaje + texto grande, con el texto donde no tapa la cara; B: el personaje **recortado** con
  contorno blanco tipo pegatina sobre el fondo desenfocado; C: dos elementos + texto central). Lo que cambias
  en una propuesta (fuente, tamaño, lado del texto, giro) se recuerda para las siguientes.
- **🎨 Mi estilo…** (abajo en Propuestas): elige las carpetas con TUS miniaturas y, si quieres, referencias
  de otros canales; «🔍 Analizar estilo» lee (sin tocar nada) cuántas palabras usas, tamaño y lado del texto,
  color, contorno, la **palabra clave en otro color**, el tamaño de la cara y tus colores. Las propuestas
  arrancan con eso (nunca copian una miniatura); lo que corriges a mano manda. Si aún no lo has enseñado,
  se usa lo aprendido de estudiar miniaturas exitosas de crítica de videojuegos: 2–3 palabras grandes en
  mayúsculas, blanco + una palabra en rojo, contorno oscuro, cara grande a un lado.
- **Material**: «✨ Buscar los mejores fotogramas» (caras grandes, personajes, nitidez, contraste, color y
  relación con el tema; descarta lo oscuro, borroso o repetido, y dice por qué recomienda cada uno),
  «📷 Fotograma del visor» y tus imágenes. Clic = encima, doble clic = de fondo.
- **Texto, Formas, Fondo, Capas** y, a la derecha, las opciones de lo elegido: fuente, tamaño, grosor,
  espaciado; exposición, contraste, saturación, temperatura, sombras, luces, nitidez, desenfoque, viñeta,
  recorte; contorno, sombra y brillo.
- **✂ Quitar fondo** (en las opciones de una imagen): automático (la IA recorta al sujeto), «⬚ Marcar con
  recuadro» (dibujas un recuadro alrededor de lo que quieres conservar) y el pincel **🖌 Borrar / 🖌 Recuperar**
  para retocar a mano. Al recortar se le pone contorno blanco y sombra, y el cuadro se ajusta al sujeto sin
  moverlo. «Quitar el recorte» lo deshace; cada retoque se puede deshacer con Ctrl+Z.
- **Lienzo**: arrastrar = mover (se pega al centro y a los tercios), esquinas = tamaño, círculo = girar.
- **👁 Vista previa**: cómo se verá a tamaño real (inicio, móvil, sugeridos; o el estante de Shorts), con la
  duración encima. **🩺 Analizar**: ¿se lee en pequeño?, contraste del texto, tamaño de la cara, demasiadas
  palabras o elementos, la duración que tapa el texto, la interfaz de Shorts… cada aviso con su arreglo.
  **✨ Mejorar**: ajustes suaves (sin saturar).
- **⬇ Exportar**: JPG por debajo de 2 MB (límite de YouTube) o PNG. Todo se guarda con el proyecto.

## ✂ Eliminar silencio y limpieza automática de la voz

- **✂ Eliminar silencio** (barra de encima del visor, o Ctrl+Mayús+Supr), como el de DaVinci Resolve: umbral (dB),
  - **🎙 Voz precisa** (por defecto, oct. 2026): una IA de detección de voz (Silero VAD, MIT, ya incluida con la
    transcripción) dice dónde hablas; cada borde se ajusta cada 5 ms siguiendo el sonido hasta el ruido de fondo de esa
    zona (medido, no fijo) y un detector de agudos sigue las «s»/«f» finales; seguro de 80 ms antes y 50 ms después de
    cada voz; sonidos suaves con algo de voz a menos de 0,5 s de una frase se quedan con ella; con transcripción, ningún
    corte atraviesa una palabra. Probado: 0 ms de voz tocados con ruido de fondo de -62 a -40 dB y los 3 ajustes de
    Resolve (el modo «solo volumen», como Resolve, se comía 0,6–1 s en 30 s). Con la voz real del usuario, «Equilibrado»
    al estilo Resolve quitaba 271 de 300 s (casi toda la voz). Análisis: ~11 s por hora de audio, una vez (se guarda).
  - También en el **clic derecho de un audio → «✂ Eliminar silencios (y juntar lo de detrás)…»**.
  antes del inicio, después del final y mínimo a eliminar (en fotogramas) y fundido cruzado. Tus ajustes de Resolve
  vienen guardados (Equilibrado −26.8 dB · 2/4 · 14; Natural −32 dB · 5/8 · 20; Rápido −32 dB · 1/10 · 2) y puedes
  guardar más. Lo que se quitará se marca en naranja en la línea de tiempo. «Mover todo lo de detrás» corta en todas
  las pistas (no se desincroniza nada) o «Solo en estos clips». Un Ctrl+Z lo deshace. La misma barra tiene «⇤ Huecos».
- **⚡ Limpieza automática** (pestaña Limpieza): muletillas seguras, posibles muletillas, palabras repetidas y
  cortadas («el el», «pro… problema»; «muy muy» o «no no» se respetan), **tomas repetidas** y silencios, de una vez.
  En las tomas repetidas la IA se queda con la **mejor** (no siempre la última): la que no quedó a medias, la más
  completa, sin muletillas ni trabas y que se entiende mejor; en la lista verás ⭐ y el porqué. Puede hacerlo sola
  al terminar de transcribir. El modo manual (▶ Escuchar / ✓ Aplicar / ✗ Ignorar) sigue igual.
- **🔁 Escucha literal** (pestaña Limpieza → Transcribir, marcada por defecto, oct. 2026): Whisper aprendió con
  textos «limpios» y, cuando repites una frase, muchas veces escribe solo una: esa toma no salía en el texto y no se
  podía quitar. Ahora el modelo wav2vec2 del alineador escucha TODO el audio letra a letra (sin arreglar nada), se
  compara con Whisper por cómo suena cada palabra y cuándo suena (b/v, s/z/c, ll/y y las cifras en palabras valen
  igual), y lo que falta se vuelve a transcribir en corto y en «modo literal». Si Whisper sigue sin escribirlo, se
  quedan las palabras tal cual se oyeron solo si rellenan un hueco y se parecen a algo dicho al lado (una toma
  repetida); si no, se deja como estaba. Probado con una narración real de 12 min: encontró 14 trozos que Whisper se
  había comido (casi todos, tomas repetidas; Whisper escribió 11 al volver a escucharlos) y lo que la IA propone
  quitar pasó del 26 al 36 % de lo que el usuario quitó a mano (el resto eran ideas quitadas para acortar). Tarda:
  unos 2 min de Whisper + 5½ min del oído literal + 2 min de recuperar por cada 12 min de audio (3 h ≈ 2 h en total).
  Código: `editoria/ai/verbatim.py`.
- **Tomas repetidas en tres niveles**: **se repite** (casi igual, o la empezaste y la volviste a empezar), **se medio
  repite** («ayer estaba jugando» → «ayer estaba trabajando») y **suena parecido** (lo mismo con otras palabras,
  según el modelo de frases MiniLM; solo se avisa). Se detectan también dentro de una misma frase, entre trozos
  separados por comas («No sé si se superó, no sé si superó…») y cuando el final de una frase se repite al principio
  de la siguiente. No cuentan como tomas las enumeraciones («Lo que sí puedo cuestionar es… / Lo que sí puedo decir
  es…») ni los contrastes («No estoy pensando en la actriz / Estoy pensando en la dirección artística»). La toma
  que se queda es la más reciente salvo que esté peor (a medias, «dis…», dice menos o se traba).
- **Muletillas**: además de «eh, este, o sea…», las **coletillas** «¿no?», «¿verdad?», «¿me explico?»… (posibles
  muletillas) y **Mis muletillas** (Limpiar → la casilla de texto: «¿por qué?, la verdad»; con «?» solo cuenta como
  pregunta suelta). Las tuyas cuentan como seguras.

## 🌐 Imágenes de internet que aprenden (Momentos → Buscar en: Internet)

Busca varias páginas y también los nombres del glosario en inglés («Jefe Maestro = Master Chief»). La IA local ordena
por parecido a lo que escribiste y esconde lo que claramente no es. En la esquina de cada imagen: **✓** «esta es»
(suben las parecidas) y **✗** «no es» (se quita, y también las casi iguales). «✨ Buscar más como las ✓» trae más;
«Mostrar las escondidas» las enseña. Lo que marcas se recuerda para esa búsqueda.

Lo mismo en **📁 Mis archivos** (momentos de tus videos): ✓ en un momento = «aquí está» → además busca **más
apariciones parecidas** que el texto no encontraba; ✗ = «no es» → aparta las parecidas. La tarjeta **«🤔 ¿Es
esto?»** (en los dos buscadores) te pregunta: primero por su mejor candidato y luego por lo más dudoso, que es lo
que más le enseña. Si buscas un nombre que la IA conoce («Jefe Maestro»), tus ✓/✗ le enseñan cómo es: se usan en
«Lo que conoce la IA» y en el B-roll automático.

## Efectos (pestaña Efectos)

- **Sonidos de Reclaimer**: whooshes, impactos, subidas, glitch, clics… generados por el programa: son
  tuyos, sin licencias ni reclamaciones de Content ID. Clic = escuchar, doble clic = ponerlo en el
  cabezal, o arrástralo a la timeline. «📁 Mi carpeta de efectos» añade los que descargues.
- **Efectos de imagen** para los clips seleccionados: blanco y negro, viñeta, grano, desenfoque, glitch,
  película antigua, tono cálido/frío, destello, temblor, fundidos. Clic = en los seleccionados; o
  **arrástralo encima de un clip** de la línea de tiempo (igual con tus ⭐ y con las transiciones).
- **Gratis en internet** (revisados para videos monetizados): Kenney.nl (CC0), Sonniss GDC Bundle,
  Freesound (solo CC0) y Mixkit (revisa su licencia).

## 🔬 Entender mi biblioteca a fondo (IA ✨ o menú IA)

La IA revisa cada segundo de tus videos, los divide en planos y aprende **quién y qué aparece**. Aprende
los nombres de tus **imágenes** («jefe maestro.png» le enseña cómo es y lo busca en tus videos por
parecido), de tus archivos y carpetas, de los nombres propios que dices y de un **glosario de apodos**.
Después, el B-roll muestra un plano donde aparece lo que nombras; si no nombras nada concreto, el
gameplay sigue de fondo de forma continua (sin saltar entre clips).

## Imagen y sonido separados (como en DaVinci Resolve)

Al poner un video en la timeline, la imagen va a V1 y **su sonido a la pista «Audio de video»**, justo
debajo, **vinculados** (🔗): se seleccionan, mueven, recortan, cortan con la cuchilla y borran juntos.
**Alt+clic** selecciona solo uno de los dos (p. ej. para quitar el sonido o moverlo aparte). El botón 🔗
de la barra de la timeline (Ctrl+Mayús+L) activa/desactiva la selección vinculada. Clic derecho en un
clip: «Desvincular audio y video», «Vincular» o «Separar el audio» (para clips de proyectos antiguos).
En el Inspector, la imagen y su sonido se ven como un solo clip: la pestaña Audio edita el sonido.

**Forma de onda** — menú Timeline → «〰 Forma de onda»: estilo espejo, rectificada (desde abajo) o solo
contorno; escala en dB (se ven mejor los sonidos bajos); silencios sombreados y una marca amarilla
**«fin del sonido»** donde se acaba el audio; picos saturados en rojo; pistas de audio normales, altas o
muy altas.

## ✨ Primera versión automática (menú IA o botón grande en «IA ✨», Ctrl+Shift+A)

Importa tu narración y tus clips, elige la narración (y una música de fondo si quieres), pulsa
**Empezar** y vete. La IA hace, uno detrás de otro:

1. Pone la narración en la timeline y la **transcribe**.
2. **Limpia la voz**: silencios largos, respiraciones, muletillas, repeticiones y tomas repetidas
   (se queda la última). Los cortes se pueden restaurar uno a uno en «Limpieza».
3. **Mira tus clips** y **detecta los temas** (bandas de color arriba de la timeline).
4. Coloca **B-roll** que encaja con lo que dices, a tu ritmo (como en tus videos: cada 3–6 s; en
   Shorts cada 2–3 s), desde el segundo 0 y sin huecos negros.
5. **Zooms** rápidos cuando dices «miren», «fíjense»… (a la cara si la hay). Las comparaciones
   solo se sugieren (en IA ✨ → Sugerencias visuales), porque tú eliges los dos clips.
6. **Toques de cine**: zoom lento en los planos largos y en las imágenes, un fundido breve a negro
   en cada cambio de tema, fundido al empezar y al acabar.
7. **Audio**: tu ecualizador «Mi voz», mejora de voz, música que baja sola cuando hablas (con
   fundidos) y volumen final −14 LUFS.
8. **Subtítulos** (marcado de serie en Shorts) y **revisión final**.

Al terminar ves un resumen. Todo queda como clips normales y **un solo Ctrl+Z deshace la primera
versión entera**.

## Tres tipos de proyecto

Al crear un proyecto nuevo eliges (y se puede cambiar en Inspector → Proyecto → «Tipo»):

| Tipo | Formato | Qué cambia |
|---|---|---|
| 🎬 **Video de YouTube** | 16:9 | Lo normal: narración, B-roll cada 3–6 s, subtítulos «YouTube clásico». |
| 📱 **YouTube Short** | 9:16 | Como tus Shorts: clip horizontal en el centro con **fondo desenfocado** del mismo clip, subtítulos «Mis Shorts» (blancos con contorno, debajo del video), etiquetas encima del video, capturas superpuestas en el centro, comparación arriba/abajo, B-roll cada 2–3 s y aviso si pasa de 3 min. |
| 🎵 **Edit musical** | 9:16 | Sin comentario, manda la música: el clip con su **reflejo** arriba y abajo, cortes a ritmo, destellos, zooms de golpe, temblor. |

## Edit musical automático (pestaña IA ✨ → «🎵 Edit musical», Ctrl+M)

**Barra «🎵 Edit»** (en la barra de la línea de tiempo, si hay un edit): **👍 / 👎** califican el edit entero
(si lo retocaste a mano, aprende de tu versión comparándola con la de la IA; los siguientes salen con lo
aprendido: planos más largos o cortos en cada parte, más o menos de cada efecto) · **🔀 Remix** lo rehace
entero de otra manera, al ritmo (Ctrl+Z vuelve) · **🎛 Mix** rehace solo los planos seleccionados o el tramo
I/O. Lo aprendido se guarda en `datos/aprendizaje_edits.json`. **✂ Elegir tramos**: en la ventana del edit,
doble clic en un video (o «✂ Elegir tramos…») para marcar a mano de dónde a dónde puede sacar planos la IA
(se guardan con el video y valen también para Remix y Mix). **🔑 Planos donde se dice** (pestaña «Frases»):
escribe palabras y la IA busca en el sonido de tus videos dónde se dicen y prefiere esos planos (uno en el drop,
si lo marcas). La ventana del edit va en pestañas: Canción y estilo · Efectos · Clips · Frases. **👎 veta los planos**: ya no vuelven a salir
(Remix, Mix ni edits nuevos de este proyecto); con solo unos planos seleccionados, 👎 los veta y los cambia al
momento. Ctrl+Z los vuelve a permitir.

Eliges la canción, el **estilo**, la duración y los clips (y, si quieres, frases para la intro). La IA
(inspirada en los generadores libres *mugen* y *AV-Sync* y en cómo se editan los edits de internet):
1. Escucha la canción: tempo, **bombo, caja y platillos** por separado, el inicio de cada compás, las partes
   (intro · **subida** · **drop** · pausa · final) y las **paradas**. Ajusta los golpes sobre el bombo real.
2. Mira tus clips: dónde hay acción, cortes u oscuridad (se guarda: la 2ª vez es instantáneo).
3. Monta según la parte: intro y pausas con planos largos; en la subida los cortes se aceleran
   (golpe → medio → cuarto, con estrobo); en el **drop**, el golpe (destello o negativo) y cortes a ritmo;
   en las paradas la imagen se congela; al final, fundido a negro.

| Estilo | Qué hace |
|---|---|
| 🔥 Agresivo / Intenso | Velocity (lento en el golpe y acelerón), destellos, temblor con el bajo, color duro |
| 🗿 Épico clásico (blanco y negro) | B/N muy contrastado, grano, viñeta, barras de cine, cámara lenta dramática, negativo en el drop, letra clásica |
| ⚡ Hype gaming | Cortes rapidísimos, color saturado, glitch RGB, zooms; intro con frases y un instante a negro antes del drop |
| 🎬 Cinemático | Barras de cine, color de película, planos largos y fundidos |
| 💧 Emocional / lento | Cámara lenta suave, colores apagados, fundidos |
| 📼 Analógico / VHS | Grano fuerte, glitch, colores retro |

Cada efecto se puede activar o quitar: velocity, temblor, zoom de golpe, glitch, estrobo, congelar,
cámara lenta en lo tranquilo, transiciones, color, grano, viñeta, barras de cine. Duración 30/45/60 s,
automática o la canción entera; cortes tranquilo/normal/intenso/frenético. «Crear otra versión» elige
otros planos. Todo queda como clips normales (con velocidad, color, transiciones y efectos): muévelos,
cámbialos o deshazlo entero con Ctrl+Z.

## ⭐ Mis efectos para la IA (panel Efectos)

Eliges tus efectos favoritos (imagen, sonidos —también los de tu carpeta— y transiciones) con «➕ Añadir
efecto…» o clic derecho → ⭐. «🧠 Proponer dónde ponerlos» (todo el video, clips seleccionados o marcas I–O;
pocos/normal/muchos) busca momentos: cambios de tema, cortes, golpes y drop de la música, lo que dices
(«fíjense», «hace años», «error», «increíble»…) y lo que se ve (acción, calma, oscuridad). Cada propuesta
sale en la lista y como rombo dorado en la timeline: **✓** la pone (cortando el clip si cae en medio),
**✗** la descarta, **🎯** la pone en los clips que elijas. Aprende de cada respuesta (por tipo de momento y
por cómo es la imagen) en `aprendizaje_efectos.json`. Un Ctrl+Z deshace cada aplicación.

## 🎯 Buscar con un ejemplo (Momentos)

Botón «🎯 Ejemplo» junto a Buscar, o clic derecho en un clip de la timeline o en un archivo de Medios →
«🎯 Usar como ejemplo de lo que busco». Eliges el momento (tira de fotogramas o barra), opcionalmente dibujas
un recuadro sobre lo que buscas y escribes qué es. «✓ Esto es» / «✗ Esto NO es» guardan el ejemplo y la
ventana sigue abierta para marcar más; «🔎 Buscar» busca con todos; «✓ Es esto y buscar» hace ambas cosas.
Varios fotogramas a la vez: Ctrl+clic / Mayús+clic en la tira o la casilla «Varios fotogramas» (un ejemplo por fotograma).
**🧠 Dónde sale**: encima de la barra de tiempo se pinta en naranja dónde se parece a lo que escribiste (tus ✓/✗
mandan); ◀ ▶ saltan al anterior/siguiente. Al moverte, el recuadro se quita (era de otro fotograma). Usa la IA de
imágenes solo si ya está descargada (nunca descarga por su cuenta).

## Ritmo de la música (automático)

Pones tu canción en tu pista de música (la que llamaste «Música», o un archivo de la categoría Música) y se escucha sola, en
segundo plano y una sola vez (luego queda en caché): **tempo**, golpes **pegados al bombo** (aunque el
detector se enganche al contratiempo, se corrige por tramos), **inicio de cada compás**, **golpes fuertes**
(bombo o caja), **partes** (intro, subida, drop, pausa, final), el **drop** y las paradas.
- En la canción: rayita en cada golpe, más larga al empezar el compás, punto naranja en los golpes fuertes
  y línea roja en el drop.
- **Imán**: los clips y la cuchilla se pegan a esos golpes (Timeline → «🥁 Imán también a los golpes»).
- Clic derecho en la canción → **📍 Poner marcadores en el drop y en cada parte** · 🔁 volver a escuchar.
- «🥁 Cortes al ritmo» (Audio inteligente) y la primera versión automática usan este mismo análisis y
  prefieren el inicio de compás, los golpes fuertes y el drop.

## Ecualizador (Inspector → clip → «Audio»)

Como el de Fairlight en DaVinci Resolve: 6 bandas (B1…B6), curva que arrastras con el ratón (rueda =
ancho de la banda, doble clic = apagarla) y el espectro de tu voz detrás. Preset **«Mi voz»** = tu
ecualización de Resolve (voz más grave y llena). «🎧 Escuchar con EQ» repite un trozo con los
cambios en directo; puedes guardar tus propios presets y aplicarlo a todos los clips del mismo archivo.

## Limpieza de voz (panel derecho → «Limpieza»)

1. Elige tu narración y pulsa **🎙 Transcribir y analizar** (o **Ctrl+T**).
   La primera vez se descarga el modelo de voz (~1,6 GB). Todo funciona en tu PC, gratis y sin internet.
2. La IA busca: silencios largos, respiraciones/ruidos, muletillas, palabras repetidas,
   tomas repetidas, palabras dudosas y saturación. **No corta nada por su cuenta.**
3. Revisa la lista de sugerencias (también aparecen en color sobre la voz en la timeline):
   - **▶ Escuchar** (o doble clic) — oyes ese momento.
   - **✓ Aplicar** — se corta en todas las pistas y se cierra el hueco (la voz y el video siguen sincronizados).
     En las tomas repetidas eliges con qué toma quedarte, o las comparas primero.
   - **✗ Ignorar** — la sugerencia se descarta.
   - **↺ Restaurar** — devuelve un corte concreto, aunque después hayas hecho otros cambios.
4. Cada corte de la IA queda marcado con **✂ naranja** en la timeline y registrado en **Historial**.
5. Los silencios nunca se eliminan del todo: se deja una pausa natural (configurable, 0,25 s por defecto).

### ✎ Corregir una palabra de la transcripción (panel «Texto», clic derecho en la palabra)

- Arriba salen **las correcciones que ya hiciste de esa palabra** («como antes») y, si no existe, la **ortografía**.
- **🎙 Volver a escuchar esta palabra**: Whisper oye otra vez solo ese trocito y te enseña lo que oye (sus 5 mejores
  interpretaciones de una escucha; ~5 s con el modelo ya cargado). Eliges una y listo; los tiempos no cambian.
- **✎ Escribir la correcta…** (también doble clic) · **Cambiar en todo el texto (N veces)…**
- **Tener en cuenta «…» al transcribir**: nombres de juegos, personas… Whisper los tendrá presentes en las próximas
  transcripciones (se guardan en `datos/vocabulario.json`; las correcciones, en `datos/correcciones_texto.json`).

## Subtítulos dentro del video (panel derecho → «Subtítulos»)

1. Marca **«Mostrar subtítulos dentro del video»** (necesita la narración transcrita).
2. Elige un estilo: **YouTube clásico**, **Caja oscura**, **Shorts dinámico** (grandes, mayúsculas,
   karaoke) o **Minimalista**, y pulsa «Aplicar estilo». Después puedes cambiar fuente, tamaño,
   colores, contorno, caja, posición, letras por línea y animación.
3. **Resaltar palabras** (p. ej. «NO»): pestaña «Texto» → clic derecho sobre la palabra (o sobre
   varias seleccionadas) → «⭐ Resaltar en subtítulos».
4. Lo que ves en el visor es lo que saldrá al exportar. Al exportar, la casilla
   «Incluir los subtítulos dentro del video» los incrusta.

Los subtítulos salen de la transcripción, así que **siguen a la voz aunque cortes o restaures**
fragmentos. Para corregir una palabra mal escrita: doble clic sobre ella en «Texto».

## IA que entiende tu video (Fase 2)

**Analizar clips** — botón **🧠** de la biblioteca (o menú IA). La IA mira varios fotogramas
de cada clip y anota su tipo (Gameplay, Cinemáticas, Menús…) y lo que se ve (combate,
exploración, diálogo, personaje…). La primera vez descarga ~500 MB de modelos; luego los
clips nuevos se analizan solos en segundo plano. Si se equivoca: clic derecho →
«🧠 Corregir lo que vio la IA».

**Buscar por contenido** — activa **🧠 Buscar**, escribe una frase («Marcus peleando contra
varios enemigos», «una cinemática triste») y pulsa Enter. Mezcla lo que la IA ve con lo que
sabe del clip (tus carpetas y etiquetas). Doble clic en un resultado = se añade desde su
mejor momento.

**Temas** — pestaña «IA ✨» → **🧭 Detectar temas**. Tu narración se divide en
INTRODUCCIÓN, HISTORIA, COMBATE, CINEMATOGRAFÍA… como bandas de color arriba de la
timeline. Doble clic = cambiar el tema, arrastra el borde para ajustarlo, clic derecho = quitar.

**B-roll** — pestaña «IA ✨» → **🎬 Proponer B-roll**. Para cada frase, 3 clips que encajan
con lo que dices (y con el tema de esa parte), con el porqué. Doble clic = insertar ese.
**⚡ Rellenar huecos con lo mejor** = modo automático: solo rellena huecos libres, nunca tapa
lo que colocaste tú. Ajustes: cambiar de clip cada 3–6 s, preferir Gameplay/Cinemáticas,
no repetir clips, volumen del sonido del clip.

## Edición avanzada (Fase 3)

**Encuadre y zoom** — selecciona un clip: en «Detalles» → «Encuadre y zoom» cambias zoom y centro,
o directamente en el visor con **Alt + arrastrar** (mover el encuadre) y **Alt + rueda** (zoom).

**⤧ Mover / escalar cada capa en el visor** (como el «Transform» de Resolve) — selecciona un clip de video o
imagen: sale su caja con 4 esquinas. **Arrastra** dentro = moverla · **esquina** o **rueda** = tamaño sin
deformar · **doble clic** = pantalla completa. Cada capa es independiente y deja ver las pistas de debajo
(una imagen en V2 encima del video de V1, por ejemplo). Sale igual al exportar; Ctrl+Z deshace cada movimiento.
«◆ Clave aquí» añade un fotograma clave: el zoom se anima suavemente entre claves (rombos
amarillos en el clip). «En pantalla» coloca el clip en una mitad, arriba/abajo o en una esquina.

**Seguir personaje u objeto (tracking)** — «Detalles» → «🎯 Seguir personaje u objeto…». Dibuja
un recuadro sobre lo que quieres seguir (o «👤 Detectar caras» y elige una): la IA crea un zoom
que lo acompaña. Las claves se pueden editar después.

**Sugerencias visuales** — «IA ✨» → «🔍 Buscar momentos». Cuando dices «miren…», «fíjense…»
o hablas de una cara, propone un zoom rápido (a la cara si la encuentra). Cuando comparas dos
cosas («comparado con…», «a diferencia de…», original y remake…), propone una Comparación.

**Comparación** — menú IA → «⧉ Comparación…». Eliges los dos clips (original y remake, dos juegos,
dos versiones…); «🔗 Sincronizar con IA» busca en el clip derecho el momento que más se parece al
izquierdo. Se crean en pantalla dividida con una etiqueta encima de cada uno (por defecto el nombre
del clip; puedes escribir otra).

**Textos en pantalla** — tecla **T** (o clic derecho en la timeline → «Añadir texto aquí»).
Se editan en «Detalles»: contenido, tamaño, posición, color y caja.

**Audio inteligente** — «IA ✨» → «Audio inteligente»: mejorar la voz (ruido, ecualización,
de-esser, compresor), **bajar la música cuando hablas** (se oye también en el visor), volumen
final a -14 LUFS para YouTube, «🎧 Escuchar 10 s con los efectos» y «🥁 Llevar los cortes del
B-roll al ritmo de la música».

**Revisión del proyecto** — menú IA → «🩺 Revisar el proyecto…» (Ctrl+R); también aparece sola al
exportar si hay posibles problemas: pantallas negras, silencios, audio saturado o bajo, música
que tapa la voz, planos largos, clips repetidos (con alternativas), posibles inconsistencias
(«hablas de combate pero se ve exploración»), palabras dudosas en subtítulos, pistas ocultas.

**🎬 Modo Director** — «IA ✨» → «Modo Director». Escribe lo que quieres para una parte, p. ej.:
*«Usa gameplay de combate, cambia de clip cada 3-5 segundos y cuando diga 'el problema' haz un
pequeño zoom al personaje. No agregues texto.»* Se aplica al tema bajo el cabezal, o a
«de 1:20 a 1:40», o «durante 20 segundos». Verás el plan antes de aplicarlo y se deshace entero
con un Ctrl+Z. También entiende «pon el texto 'X'» y «no modifiques esta parte» (protege ese
tramo). «📍 Leer instrucciones de los marcadores» aplica lo que escribas en los marcadores de la
timeline, hasta el marcador siguiente.

La pestaña **«Texto»** muestra la transcripción sincronizada: la palabra que suena se resalta,
clic en una palabra = ir a ese momento, doble clic = corregirla. Desde ahí se exportan los
**subtítulos .srt** (ya ajustados a los cortes) para subirlos a YouTube.

**✂ Editar con el texto** (oct. 2026): lo que se va a quitar sale **tachado en rojo** (según las casillas de
«⚡ Limpieza automática»). Clic en lo tachado = se queda; clic en algo con fondo de color = se tacha; en una toma
repetida, clic en la toma que se queda = te quedas con la otra. Selecciona texto y pulsa **Supr** (o clic derecho →
«✂ Tachar») para quitarlo tú. **✂ Cortar lo tachado (N · ~X s)** lo quita del video en todas las pistas, de una vez
(un Ctrl+Z lo deshace; cada corte se puede devolver en «Limpieza → Sugerencias → Aplicadas»). Lo que taches o
destaches manda sobre las casillas, también para «⚡ Limpiar automáticamente».

**📋 Resumen** (botón junto a «Transcripción»): solo los sitios con algo que quitar, agrupados — 🔁 se repite, ≈ se
medio repite y 〜 suena parecido (cada uno con las tomas, ⭐ la que se queda, «Después dijiste: …» y el porqué),
💬 muletillas por palabra («¿no?» × 37, con cada aparición y su contexto), palabras repetidas, lo tachado a mano,
silencios y 🧩 lo que recuperó la escucha literal. Casilla marcada = se quita · desmarcada = se queda · doble clic =
escucharlo. Con 3 horas de narración (30 000 palabras) el texto se dibuja en ~0,4 s y el resumen en ~1,3 s.

## 🎵 Convertir un video en solo audio (Medios → clic derecho)

«🎵 Convertir en solo audio» (uno o varios videos): si el sonido ya es AAC o MP3 se copia tal cual (idéntico y
rápido); si no, se convierte a AAC 256 kbps. Se guarda en `F:\Reclaimer\Audio extraído` y aparece en Medios ▸
«Audio extraído». Los originales no se tocan.

## 🚀 Exportar (botón «Exportar» / pestaña «Entrega»)

Eliges **para dónde es** con un clic y listo:
- **▶ YouTube**: H.264 High, 60 FPS, 24 Mbps en 1080p (40 en 1440p, 80 en 4K), audio AAC 384 kbps, color BT.709,
  fotograma clave cada medio segundo y «faststart»: lo que recomienda YouTube (también para Shorts).
- **♪ TikTok**: siempre vertical 1080×1920, 60 FPS, H.264 a 20 Mbps, AAC 256 kbps (vale para Reels y Shorts).
- **🪟 Para ver en Windows**: H.264 + AAC, se abre con doble clic en cualquier PC o móvil.
- **⚙ Personalizado**: resolución, FPS, códec (H.264 / H.265), tarjeta gráfica o procesador y calidad.

**Más rápido**: el video se parte por los cortes del montaje y se hacen **varios trozos a la vez** (hasta 8,
según tu procesador); el sonido se hace entero una vez y al final se juntan sin volver a comprimir. Solo se
corta donde no queda nada a medias (ni transiciones ni textos que crucen el corte); si no se puede, se exporta
de una vez como antes. Con la tarjeta gráfica se usa además la cuantización adaptativa de cada marca (VBAQ en AMD, AQ en NVIDIA, look-ahead en Intel): menos bloques en lo oscuro y en el movimiento.

- **Calidad → «Máxima calidad»**: la tarjeta analiza cada fotograma antes de comprimirlo. Tarda casi el doble y, a
  estos bitrates, casi no se nota (YouTube y TikTok vuelven a comprimir). Apagada por defecto.
- **Mientras exporta → «Dejar libre el PC»**: la exportación va en prioridad baja y con la mitad de trozos a la vez;
  puedes seguir usando el PC (otro programa, un juego o el propio editor) sin tirones. Tarda algo más.
- ⚡ **Velocidad** (octubre 2026): el color se aplica en 16 bits (el mismo resultado, menos de la mitad de trabajo); en
  los verticales con copias o fondo, el color y los looks se hacen al clip antes de montarlo; un bloque de clips que
  llena todo el video ya no se pinta sobre un lienzo negro. Un edit vertical de 2,5 min: de 133 s a ~72 s; un video
  de YouTube de 10 min en 1080p60: de ~130 s a ~90 s (1 hora ≈ 9 min).

Si la tarjeta gráfica falla al codificar, se reintenta sola con el procesador. Recuerda la última carpeta y el
último destino; si el proyecto no está guardado, va a `F:\Reclaimer\Exportados`. Los proyectos nuevos son a
**60 FPS** (Edit y Short en vertical, Video de YouTube en 16:9).

## ✂ Recortar sujeto con IA (clic derecho → ✨ IA, o pestaña IA ✨)

Marca en un fotograma QUÉ quieres separar (clic = sí, clic derecho = no, arrastrar = recuadro) y la IA (SAM 2.1
de Meta, licencia Apache-2.0, en tu Radeon RX 9060 XT) lo sigue en todo el clip: entiende su interior y sus
detalles, no solo el contorno. **Quitar el fondo** (queda el sujeto, como pantalla verde) o **quitar el sujeto**;
«Bordes finos» para pelo y telas. Unos 0,2–0,3 s por fotograma. Se ve en el visor y sale al exportar; Ctrl+Z.

## 🎞 Cómo se ve cada efecto (vistas previas)

Cada efecto de imagen, cada transición y cada efecto del edit musical tiene su **miniatura** con el efecto puesto
y, al pasar el ratón, su **animación en bucle**. Están hechas con el mismo motor que la exportación (es el efecto
de verdad), sobre una toma de muestra creada a partir del panorama **«Venice Sunset» de Poly Haven**
(polyhaven.com, licencia **CC0**: dominio público, uso comercial sin atribución). Van en
`editoria\assets\efectos` (~11 MB). Para regenerarlas: `.venv\Scripts\python.exe -m editoria.core.fx_previews`.

## 🎙 Tu voz y el juego por separado (grabaciones de OBS)

Si OBS graba el micrófono y el juego en pistas distintas, al importar el video Reclaimer las separa solo y, al
ponerlo en la línea de tiempo, va: imagen + 🎮 juego en una pista + 🎙 tu voz en «🎙 Micrófono» (con mejora de
voz), todo vinculado. Los audios quedan en «Audio extraído/Pistas de OBS».
**OBS** (una vez): Ajustes → Salida → Modo de salida «Avanzado» → pestaña Grabación → «Pistas de audio»: marca
1, 2 y 3. Luego, en el Mezclador de audio → ⚙ → «Propiedades avanzadas de audio»: «Audio del escritorio» en
las pistas 1 y 2; «Mic/Aux» en las pistas 1 y 3. (1 = todo junto, 2 = juego, 3 = tu voz.)

## ✂ Elegir tramos para el edit

En «Crear edit musical» → Clips → «✂ Elegir tramos…»: reproduce (Espacio) y con **un solo botón** marca
«[ Entrada» y luego «Salida ]» (tecla I): el tramo se añade solo. O activa **«↔ Arrastrar»**, arrastra sobre la
barra de dónde a dónde y pulsa «➕ Añadir tramo». Lo ya elegido no se duplica. La IA solo usará esos tramos.
**🔍 Acercar / alejar la barra**: Ctrl + rueda del ratón (o los botones «🔍−» «🔍+», a la derecha de −1 s / +1 s).
A los lados de la barra ves entre qué tiempos estás (sin acercar: de 0 a lo que dura el video). Acercada, la
rueda sola te mueve por el video y, si el cabezal rojo se sale, la vista lo sigue.
**⬛ Imágenes negras**: las rayitas amarillas DEBAJO de la barra marcan dónde la imagen se queda completamente negra
(fundidos a negro, pantallas de carga, un fotograma negro suelto; un fondo negro con texto no cuenta). Se buscan
solas al abrir, después de las escenas, y abajo a la derecha dice en cuántos sitios hay. Se guardan: la segunda vez
salen al momento. Lo que eliges con **«↔ Arrastrar»** NO incluye esas partes en negro: el tramo se añade en trozos,
saltándolas (con «[ Entrada / Salida ]» sí puedes coger negro si lo quieres).
En la línea de tiempo, la **barrita ↕ a la izquierda de las pistas**: arrastra hacia arriba = pistas más grandes,
hacia abajo = más pequeñas.
**↔ Arrastrar** se apaga solo al pulsar «➕ Añadir tramo»; marca **«Continuar»** (a su lado) para seguir añadiendo
tramos arrastrando sin volver a activarlo (se recuerda).
**⏱ Regla de tiempos** encima de la barra: números entre el principio y el final de lo que ves, con su unidad según el
zoom (décimas «11.2s», segundos «45s», minutos «2m 30s», horas «1h 05m»).

## ⚡ Copias ligeras más rápidas
- **Copias ligeras** (para reproducir fluido): con tu tarjeta gráfica y todas las de un video de una sola pasada,
  unas 3 veces más rápido (un video de 38 min: de ~13 min a ~4). La barra dice cuánto falta.

## ✂ Ritmo de corte de los edits (más pausado) y ⚡ Ráfaga

- La edición automática corta menos: los planos duran como mínimo ~3 s (Tranquilo), 1,7 s (Normal), 1,2 s
  (Intenso) u 0,8 s (Frenético), y siempre en los golpes/compases de la canción (con canciones rápidas el plano se
  alarga al doble de golpes para seguir en el ritmo).
- **Ráfaga automática** (cortes muy seguidos): como mucho UNA por edit, justo antes del drop, y solo si la canción
  es enérgica (rock, metal, phonk: batería muy marcada; se mide la «pegada» real del sonido). Con «Tranquilo», nunca.
- **⚡ Ráfaga** (barra de la línea de tiempo, entre Dividir y Eliminar): cuando TÚ quieras cortes seguidos. Clic =
  1 compás desde el cabezal a medio golpe; la flechita: 2 compases, ¼ de golpe o entre las marcas I–O. Cada trozo
  salta a otro plano (otro video del proyecto) para que el corte se vea; el sonido no se toca; Ctrl+Z.
- **YouTube y Shorts** (primera versión automática y B-roll): planos de 4–7 s (Shorts 2,5–4 s) por defecto y
  nunca menos de 3 s (Shorts 2 s), ni con el ritmo «Rápido». Si hay música de fondo, los cortes caen en sus
  golpes en todos los estilos.

## ◢ Fundidos con tiradores (como Resolve) y bordes de la línea de tiempo

- Pasa el ratón por un clip (o selecciónalo): en sus **esquinas de arriba** aparece un **tirador blanco**. Arrástralo
  hacia dentro = **fundido de salida** (derecha) o **de entrada** (izquierda): la imagen va a negro / el sonido baja
  hasta el silencio. Se ve como un triángulo oscuro. Va de fotograma en fotograma y Ctrl+Z lo deshace.
- **Seleccionado = borde rojo sólido.** Los clips de la IA llevan su borde naranja por dentro (mismo grosor).
- Solo resalta lo que te impide seguir: el candado es gris si la pista está libre y **ámbar si está bloqueada**; las
  herramientas activas (selección, imán, enlace…) solo se ven un poco más claras.

## 🎞 Animar posición y tamaño (fotogramas clave)

Para que una capa (imagen en imagen, una captura, un logo) entre desde un lado, crezca o se mueva:
1. Selecciona el clip y pon el cabezal donde empieza el movimiento → Inspector → «Posición y tamaño» → **◆ Clave**.
2. Mueve el cabezal y **arrastra o escala la capa en el visor**: se crea la clave de ese momento.
3. Entre claves el movimiento es suave. **◀ ▶** saltan entre claves, **✕ Clave** quita la del cabezal y
   **Quitar animación** la deja quieta donde está. Ctrl+Z en todo.
Las claves van pegadas al contenido (al dividir o recortar el clip, el movimiento sigue igual). En la línea de tiempo
el clip lleva 🎞 y sus claves son rombos azules. Al exportar sale igual (también en 📸 fotograma). Elegir una
disposición fija en «En pantalla» quita la animación.

## 🎙 Voz en off · 📑 Capítulos · 📸 Fotograma

- **🎙 Grabar voz en off** (Voz → «Grabar voz en off…», Ctrl+Mayús+R): pon el cabezal, ⏺ Grabar, cuenta atrás de
  3 s y grabas viendo el video (el sonido del proyecto se silencia para que no se cuele en el micro). ⏹ Parar o
  Espacio: la toma (WAV) cae en la pista de voz en ese sitio, sin tapar nada; Ctrl+Z la quita. Las tomas se
  guardan en «Grabaciones de voz» junto al proyecto (o en `F:\Reclaimer\Grabaciones de voz` si aún no lo guardaste).
- **📑 Capítulos para YouTube** (Archivo, Ctrl+Mayús+K): el texto «0:00 Intro · 3:12 Jugabilidad…» desde tus
  marcadores con nombre (M) o desde los temas de la narración; aplica solas las reglas de YouTube (0:00, mínimo 3,
  10 s o más) y te avisa. 📋 Copiar o 💾 guardar .txt.
- **📸 Exportar este fotograma** (Archivo, Ctrl+Alt+G): PNG a la resolución del proyecto, tal como saldrá en el
  video (efectos, textos, capas, subtítulos), junto al proyecto o en Exportados, y copiado al portapapeles.

## 🗂 Pestañas: 🎬 YouTube · 🎵 Edits · 📱 Shorts

Arriba, en el centro, hay una pestaña por tipo de trabajo y cada una tiene **su propio proyecto**:
- Al cambiar de pestaña se guarda lo que llevabas y se abre el de la otra tal como lo dejaste.
  Con nombre (.eia) se guarda en su archivo; sin nombre, en `datos/espacios/<pestaña>.eia`.
- Al abrir Reclaimer vuelves a la última pestaña, con su proyecto.
- **Ctrl+N** = proyecto nuevo en la pestaña actual (en Edits abre directamente «Crear edit musical»).
  Si el anterior no tenía nombre, queda en las copias de seguridad (Archivo → «⟲ Recuperar una copia»).
- **Abrir** un .eia lo pone en la pestaña de su tipo.
- **Ctrl+1 / Ctrl+2 / Ctrl+3** = ir a 🎬 YouTube / 🎵 Edits / 📱 Shorts (también en el menú Archivo; se pueden
  cambiar en «⌨ Personalizar atajos»).
- Cada pestaña tiene **su propio Ctrl+Z**: al volver a ella puedes deshacer (y rehacer) lo que hiciste allí,
  también lo de antes de cambiar. Dura mientras Reclaimer esté abierto (al cerrarlo, el trabajo queda guardado).
- Mientras se transcribe o la IA analiza la narración, no se cambia de pestaña (te avisa).

## ✎ Nombre del video y capas

- **Nombre del video/proyecto**: arriba a la izquierda del visor; clic para cambiarlo (Intro = listo, Esc = dejarlo,
  Ctrl+Z lo deshace). Es el nombre al guardar y el del archivo al exportar.
- Un clip con **✂ recorte de sujeto**, pantalla verde, opacidad o mezcla deja ver en el visor la pista de debajo
  (igual que al exportar).

## 🧍 Identificar por silueta (clic derecho → ✨ IA, o 🔎 Momentos)

Le enseñas un personaje con un clic encima (en verde ves la silueta que aprende, recortada por SAM 2.1; clic
también en lo que le falte) y lo busca en todos tus videos. Aprende sus **colores propios en su proporción**
(p. ej. pelo rosa + vestido negro: algo solo rosa no cuenta), su tamaño, su figura y su dibujo de líneas. Ligero:
cada video se recorre una vez en miniatura (1 fotograma/s, se guarda en `datos\cache\siluetas`) y solo los
mejores candidatos se miran de cerca. 2–5 ejemplos en momentos distintos = más fiable. Lo aprendido:
`datos\personajes_silueta.json`. Sin el motor de IA, se usa el recuadro que dibujes.

## 🗣 Diálogos sin ruido de fondo

Demucs v4 (Meta, MIT) separa las voces de la música del juego y del ambiente: clic derecho en un clip → ✨ IA →
«🗣 Separar los diálogos…», o en el edit musical «Opción de sonido → Solo los diálogos». Se guarda por archivo.

**Motor de IA**: `F:\Reclaimer\motor_ia` (un Python aparte con PyTorch para la gráfica: CUDA en NVIDIA, ROCm en AMD; los modelos en
`motor_ia\modelos`). Si algo del motor falla, Reclaimer sigue funcionando.
- **Instalar / reparar**: Ayuda → «🧠 Motor de IA…» → «Instalar»/«Reparar», o doble clic en
  `motor_ia\INSTALAR_MOTOR_IA.bat` (hace falta Python 3.12). Detecta tu tarjeta: NVIDIA → PyTorch CUDA, AMD → PyTorch
  ROCm (usan la gráfica); si no, la versión para procesador. Si cambias de tarjeta, «Reparar» instala la versión de la nueva. Instala SAM 2.1 y Demucs con las versiones probadas y descarga los
  modelos. Se puede repetir cuando quieras (lo que ya está no se repite). Registro: `motor_ia\instalar.log`.
- Si la tarjeta deja de detectarse (p. ej. tras un cambio de controlador), Reclaimer te avisa al arrancar.
  Hace falta AMD Adrenalin 26.2.2 o más nuevo, o el controlador de NVIDIA 570 o más nuevo.
- **✂ Recortar sujeto — Calidad**: «Máxima» (modelo grande, 1280 px, bordes finos) o «Rápida» (modelo mediano,
  854 px: ~2 veces más rápido).

## 🔑 Palabras clave (ligero)

Escribe palabras o frases y te dice dónde se dicen en tus videos/audios, gastando poco: un detector de voz
(Silero VAD, incluido) se salta la música y el silencio y solo esos trozos se escuchan con Whisper «base»
(~140 MB, en `datos\modelos`) con 2 núcleos; la tarjeta gráfica queda libre. Tolera acentos y errores
(«Marcos» → «Marcus»). Lo escuchado se guarda (`datos\cache\palabras`): repetir es instantáneo; si el archivo
ya está transcrito, usa esa transcripción. Pestaña IA ✨, clic derecho en un clip (✨ IA) o en Medios.
Resultados: ir ahí, arrastrar a la línea de tiempo, poner en el cabezal o 📍 marcadores.

## 🔁 Convertir y ⚡ Exportar rápido

- Menú **Convertir** (junto a Ayuda): arrastra videos/audios, elige MP4 o MP3 y la carpeta (Escritorio,
  Descargas, Videos, Música, Exportados…). H.264+AAC → MP4 sin recomprimir (instantáneo).
- **⚡ Exportar rápido** (arriba a la derecha): YouTube / TikTok / Windows y carpeta en dos clics.
- Edit musical: **arrastra una canción (o un video: se usa su sonido) al campo «Canción»**, y videos a la lista.
  También **un video de la propia lista «Clips»**: arrástralo a «Canción» (o clic derecho → «🎵 Usar como canción») y su
  sonido será la canción, sin convertirlo antes en Medios (ese video se desmarca de los clips).

## ↔ Deformar el video en el visor
Con un clip seleccionado y el visor en «⤧ Transformar»: las **asas azules a media arista** estiran o aplastan la
imagen solo a lo ancho o solo a lo alto (la imagen llena su caja). **Mayús + esquina** = ancho y alto por separado.
Las esquinas sin Mayús siguen cambiando el tamaño sin deformar. «Sin deformar» (Inspector) le devuelve su proporción.

## 🎯 Encuadre vertical que sigue la acción (Shorts y edits)
Clic derecho en un clip horizontal → «🎯 Encuadre vertical que sigue la acción»: llena la pantalla vertical y el
recorte se mueve con lo que pasa (descuenta el giro de la cámara y el HUD quieto; caras en las cinemáticas). Para
seguir algo concreto: «Seguir personaje u objeto…» → «📱 Sin zoom: llenar la pantalla vertical y que el encuadre lo
siga». «Quitar «sigue la acción»» vuelve al recorte centrado.

## ✨ Efectos solo al personaje
Clic derecho → ✨ IA → «✨ Efectos solo al personaje…»: marcas al personaje, la IA lo sigue en todo el clip y pone
encima una COPIA recortada a él. Lo que le pongas a la copia solo le afecta a él; lo del clip de abajo, al fondo.
Efectos ya hechos: personaje a color y fondo en B/N, resplandor, colores más vivos, fondo oscuro, fondo desenfocado.

## 🎨 Capa de ajuste · 🟦 Color sólido y degradados
Timeline → «🎨 Añadir capa de ajuste»: un clip transparente; su color y sus efectos se aplican a TODO lo de debajo
mientras dura (con opacidad y fundidos, el efecto entra poco a poco). Timeline → «🟦 Añadir color sólido o
degradado…» (clic derecho → «Cambiar color…» para cambiarlo). Van a Medios → «Generadores».

## 📦 Recopilar proyecto
Archivo → «📦 Recopilar proyecto…»: una copia del proyecto con todos sus archivos en una carpeta (respaldo, otro
disco u otro PC). «Solo lo que se usa» guarda de las grabaciones largas solo los trozos que usas (+2 s, con todas sus
pistas de audio). Aunque muevas la carpeta, el proyecto encuentra sus archivos en «Medios».

## 🎚 Analizar y proponer mezcla
Voz → «🎚 Analizar y proponer mezcla…» (o IA → Audio): la IA propone, tramo a tramo y con su motivo, cómo va la
música: baja al hablar (mucho en frases emotivas, poco en las de acción), sigue la forma de la canción y respeta tus
marcadores «voz» / «música» y las pistas bloqueadas. No cambia nada hasta «Aplicar lo marcado».

## ⊞ Pistas de composición aparte
Cuando hay composición, la barra de la línea de tiempo enseña «▤ Principal» (tu montaje) y «⊞ Pistas de composición»
(solo sus pistas y el audio). Es el mismo video: se ve y se exporta todo junto.

## 🎲 Edits musicales más variados
La IA ya no repite el mismo corte, efecto, movimiento ni transición: nunca 3 planos seguidos iguales, cada efecto
descansa unos planos, el velocity va en algunos planos (con rampas distintas) y la cantidad de efectos depende de la
canción y de cada parte. El clip compuesto se cocina con la tarjeta gráfica y en trozos a la vez (~2,5× más rápido).

## 🎴 Estilos nuevos aprendidos de tus edits de ejemplo
La IA aprendió de tus edits de ejemplo (no es una opción: ya forma parte de cómo edita):
- **🎴 Estilizado (looks en los golpes)**: imágenes casi quietas que cambian de look en los golpes fuertes (🟣 duotono,
  negativo, glitch, RGB), casi sin destellos y con un final que se queda.
- **📜 Historia / lore**: planos que respiran, la misma imagen cambia de tono en los golpes, fundidos y un parpadeo
  rápido antes del final.
- En **todos** los estilos, los cortes van a los golpes fuertes reales de la canción (bombo, caja).
- Efecto nuevo **🟣 Duotono** (Efectos → Imagen): sombras moradas y luces verdes.

## ⤧ Transformar, ▦ Relleno y clic en el visor (como en Resolve)
- **Al añadir** un video o una imagen ya no se le pone nada solo (ni fondo desenfocado ni copias arriba y abajo): se
  ve entero con su forma; en una pista de encima, alrededor se ve lo de debajo.
- **Inspector → ⤧ Transformar** (pestaña Video): Tamaño X / Y con 🔗 (suelto = estirar o aplastar), Posición X / Y,
  Rotación, Voltear ↔ ↕ y ▦ Relleno, cada fila con su ↺. Varios cambios seguidos = un solo Ctrl+Z.
- **▦ Relleno** (Efectos → Imagen, o el Inspector): lo que queda vacío alrededor del clip se llena con la propia imagen
  ampliada y desenfocada (Desenfoque, Oscurecer, Zoom). Lo pones tú cuando lo quieres.
  «Vertical con fondo desenfocado» ya no está en «En pantalla» (hacía lo mismo sin poder ajustarse); los clips que ya
  lo tenían lo conservan y lo siguen mostrando.
- **Clic en una capa del visor** (modo ⤧ Transformar) = la seleccionas; **Ctrl+clic** = la de debajo.

## Visor como en Resolve

- **Modos** (abajo a la izquierda): ⤧ Transformar · ✂ Recortar bordes · 🔍 Zoom dinámico (verde → rojo) ·
  ✏ Anotaciones (no se exportan).
- **Rueda** = zoom de la vista; rueda pulsada = mover la vista; clic en el % = ajustar. Ctrl+rueda = tamaño de
  la capa; Alt+rueda/arrastrar = encuadre dentro de la caja.
- **▦ Guías**: redes (1:1, 4:5, 9:16, 1.91, 16:9), cine (1.33–2.40), acción/título, centro, Shorts, reglas.

## Interfaz limpia (como Resolve)

Cada panel tiene sus pestañas y las explicaciones van en la ayuda al pasar el ratón (y en «?»):
**Efectos** (Imagen · Transiciones · Sonidos · ⭐ Para la IA) · **Limpieza** (Transcribir · Limpiar · Sugerencias)
· **Subtítulos** (arriba **⚡ Subtítulos para Short**: transcribe si hace falta y los pone con tu estilo; debajo
Letra · Colores · Posición · Animación) · **IA ✨** (Inicio con las herramientas · Temas · B-roll · Zooms · Audio
· Director).

**Aspecto (28/10/2026)**: todas las funciones a la vista; el texto explicativo, solo al pasar el ratón. Los símbolos
(✂ 🎬 ✨…) se ven como iconos de un solo color, del color del texto (no como emojis de colores); botones, campos,
casillas y desplegables con un estilo propio; el naranja solo para lo activo y el botón principal. Al abrir, los
paneles de los lados tienen siempre un ancho cómodo (si una distribución guardada los dejó en una tira, se ensanchan).

## Efectos de edits musicales nuevos (panel Efectos → Imagen)

🌈 Separación RGB · ✨ Brillo soñador · ≈ Desenfoque de movimiento · 🔥 Contraste intenso · 📼 VHS ·
⚡ Parpadeo · ↻ Giro de cámara al entrar · ☀ Destello de luz. Son los que más se usan en velocity, phonk y AMV
(revisado en tutoriales de CapCut, Alight Motion y After Effects). Se ven en el visor y salen al exportar; los
estilos del edit musical ya los usan (Agresivo e Hype: RGB y contraste, parpadeo en el drop y giros; Emocional,
Nostálgico e Inspirador: brillo y destellos de luz; VHS: cinta VHS; el acelerón del velocity lleva desenfoque de
movimiento).

## 🧭 Temas: quedarte con unos o guardarlos en Medios

Clic derecho en un tema de la barra de temas → «🧭 Temas: quedarme o mandar a Medios…». Marca los temas
(Combate, Historia, Cinemáticas…) y elige:
- **Quedarme solo con estos en la línea de tiempo**: lo demás se quita y se junta (un Ctrl+Z).
- **Mandar a Medios**: cada tramo se guarda como un video en Medios, carpeta «Temas · <tema>», con el tema como
  palabra clave (búscalo luego). Se hace en segundo plano (archivos en `datos\segmentos_temas`).
- **Las dos cosas**.
Los temas se limpian solos: los trozos diminutos se unen al de al lado, los seguidos iguales se juntan, y si borras
la narración, sus temas se van también. Clic derecho → «Quitar todos los temas».

## Primera versión automática

Casilla **«🎙 Transcribir la voz»**: apágala si el audio del video no es tu voz (gameplay, cinemáticas). Entonces
no se transcribe y se saltan los pasos que necesitan tu voz (limpieza, temas, B-roll según lo que dices, zooms al
decir «miren», subtítulos); lo demás se hace igual.

## Copias ligeras automáticas

Aunque uses «Calidad: Completa», se preparan solas en segundo plano las copias «Media» y «Un cuarto» (prioridad
baja, 4 hilos): al cambiar de calidad ya están listas. Reproducción → Resolución de la línea de tiempo →
«Preparar copias ligeras solo» para apagarlo.

## Línea de tiempo

- **✂ Cortar en los cambios de escena** (clic derecho en un video): donde la imagen cambia de golpe (corte de
  cámara en una cinemática, otra escena, el menú de pausa…) se corta, sin IA. «Cortes claros» o «También cambios
  más suaves». Un solo Ctrl+Z.
- **Clic derecho ordenado como Resolve**: crear clip compuesto · copiar/pegar/pegar e insertar/insertar
  espacio/pegar y eliminar atributos/cortar/cortar y propagar · eliminar (y propagar) · **eliminar solo el
  audio / solo el video** · activar/desactivar (D) · cambiar duración (Ctrl+D) · cambiar velocidad ·
  normalizar volumen · color de clip · vincular · buscar en el panel multimedia (Alt+F) · atributos del clip.
- Seleccionado = **celeste**; hecho por la IA = **amarillo** (se ven los dos).
- Alargar un clip **se come** lo de al lado; con el imán se queda pegado un momento donde choca.
- Si un archivo falta (rojo) y lo vuelves a añadir (aunque esté en otra carpeta), sus clips se reconectan solos.
- 👍 cocina el edit en un 🧩 clip compuesto; 🎛 Mix te lleva al principio del tramo rehecho.
- Toda la IA está en la pestaña **IA ✨** (ya no hay un menú «IA» repetido arriba).
- **🗑 Vaciar** (barra de la línea de tiempo y menú Editar): quita todos los clips, textos y marcadores de un
  golpe (lo bloqueado 🔒 se queda; tus archivos siguen en Medios). Ctrl+Z lo devuelve.

## Seguridad de tu trabajo

- Los archivos originales **nunca** se modifican: la timeline solo guarda qué trozo de cada archivo usar.
- Todo se puede deshacer (**Ctrl+Z**) y rehacer (**Ctrl+Y**).
- Autoguardado cada minuto y recuperación si el programa se cierra de golpe.
- Cada vez que guardas se hace una copia de seguridad (se conservan las 30 últimas) en
  `F:\Reclaimer\datos\copias_de_seguridad`.
- **Todo en la carpeta de Reclaimer**: los datos del programa (modelos de IA, caché, copias, autoguardado, registros y temporales) viven
  en `F:\Reclaimer\datos`, junto al programa, para no llenar el disco C:. Lo que había antes en
  `%LOCALAPPDATA%\EditorIA` se muda solo la primera vez que abres Reclaimer (con una barra de progreso).
- **Ctrl+Alt+S** guarda una versión numerada: `Proyecto_v01.eia`, `Proyecto_v02.eia`…

## Estado del desarrollo

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Importación, biblioteca, búsqueda básica, timeline, preview, deshacer, bloqueos, guardado, exportación | ✅ |
| 1 | Transcripción, limpieza de voz (silencios, muletillas, repeticiones, tomas), cortes reversibles, subtítulos .srt | ✅ |
| 1 | Subtítulos dentro del video (estilos, animaciones, karaoke, palabras resaltadas) | ✅ |
| 2 | IA: clasificación de clips, búsqueda por contenido, temas, sugerencias de B-roll | ✅ |
| 2 | Avisos de continuidad (en la Revisión del proyecto) | ✅ |
| 3 | Encuadre/zoom con claves, tracking, zoom por contexto, comparaciones, textos en pantalla | ✅ |
| 3 | Audio inteligente (voz, ducking, -14 LUFS), cortes a ritmo, Revisión, Modo Director | ✅ |
| + | Ecualizador tipo Fairlight, ayuda con clic derecho, interfaz tipo DaVinci Resolve | ✅ |
| + | Tipos de proyecto: Video de YouTube / YouTube Short / Edit musical (estudiado de tus Shorts) | ✅ |
| + | Edit musical automático (drop, cortes a ritmo, destellos, zooms, temblor, reflejo) | ✅ |
| + | Edits 2.0: estilos (Agresivo / Intenso, Épico B/N, Hype, Cine, Emocional, VHS), batería y partes de la canción, velocity, impact frames, congelar en paradas, cada efecto activable | ✅ |
| + | Ritmo de la música automático: golpes sobre el bombo, compases, drop y partes en la timeline, imán a los golpes, marcadores del drop | ✅ |
| 4 | Proxies (edición fluida con 1440p/4K), caché, diagnóstico, historial ligero | ✅ |
| + | «Primera versión automática» de un video comentado (de la narración al video casi terminado) | ✅ |

## Estructura del código

```
main.py                    arranque
editoria/
  core/                    datos y lógica (sin interfaz)
    model.py               proyecto, pistas, clips, marcadores
    controller.py          TODAS las ediciones (deshacer, bloqueos)
    media.py               FFmpeg: info, miniaturas, forma de onda
    organize.py            clasificación por carpetas y búsqueda
    mapping.py             tiempo del archivo original ↔ tiempo de la timeline
    subtitles.py           subtítulos desde la transcripción
    transform.py           zoom con fotogramas clave y disposición en pantalla
    audio_fx.py            efectos de voz, ducking de música, normalización
    project_tools.py       recortar un tramo del proyecto (escuchar con efectos)
    equalizer.py           ecualizador de 6 bandas (misma curva en pantalla y al exportar)
    effects.py             destellos, fundidos, temblor y efectos de imagen
    sfx.py                 efectos de sonido propios (generados)
    proxies.py             copias ligeras para la calidad de reproducción
  ui/                      interfaz (biblioteca, visor, timeline, paneles, exportar)
  export/ffmpeg_export.py  timeline → video final
  export/ass_subtitles.py  subtítulos con estilo (.ass) que FFmpeg incrusta
  ai/                      módulos de IA independientes
    transcription.py       voz → texto con tiempos por palabra (Whisper local)
    silence_detection.py   silencios, ruidos, saturación (por volumen)
    repetition_detection.py muletillas, palabras y tomas repetidas (se repite / se medio repite / suena parecido)
    verbatim.py            🔁 escucha literal: lo que Whisper no escribió (oído wav2vec2 + Whisper en corto)
    voice_cleanup.py       reúne los detectores y produce sugerencias (y qué se quita: will_cut)
    embeddings.py          "huellas de significado" de frases e imágenes (modelos ONNX locales)
    clip_analysis.py       qué se ve en cada clip + búsqueda por contenido
    topic_detection.py     temas de la narración
    broll_selection.py     clips propuestos para cada frase
    tracking.py            seguir objetos (OpenCV) y detectar caras
    visual_suggestions.py  zooms y comparaciones según lo que dices
    music_analysis.py      golpes y tempo de la música
    audit.py               revisión del proyecto y continuidad
    director.py            Modo Director (instrucciones escritas → plan)
    edit_maker.py          edit musical automático (drop, ritmo, movimiento de los clips)
    edit_engine.py         edits 2.0: estilos y montaje según la estructura de la canción
    song_structure.py      batería (bombo/caja/platillos), compases, partes y paradas de la canción
    rhythm.py              ritmo de la música que pones (caché): golpes, compases, drop, partes
    effect_memory.py       ⭐ mis efectos para la IA: momentos, propuestas y aprendizaje ✓/✗
    first_version.py       primera versión automática (B-roll, toques de cine, música)
    library_understanding.py entender la biblioteca a fondo (planos, nombres, referencias)
    moments.py             buscar apariciones (texto, imagen de referencia, nombres)
    web_images.py          imágenes libres de internet (Openverse)
tests/                     pruebas automáticas
```

Pruebas: `tests\test_core.py`, `tests\test_voice.py`, `tests\test_subtitles.py`, `tests\test_ai.py`,
`tests\test_framing.py`, `tests\test_phase3.py`, `tests\test_ui.py`, `tests\test_ui_voice.py`,
`tests\test_eq.py`, `tests\test_help.py`, `tests\test_shorts.py`, `tests\test_edit.py`, `tests\test_auto.py`, `tests\test_link.py`, `tests\test_effects.py`, `tests\test_understand.py`, `tests\test_timeline2.py`, `tests\test_moments.py`, `tests\test_web_images.py`, `tests\test_thumbnail.py`, `tests\test_cutout.py`, `tests\test_style.py`, `tests\test_guide.py`, `tests\test_speed.py`, `tests\test_transitions.py`, `tests\test_trims.py`, `tests\test_edit_tools.py`, `tests\test_fonts.py`, `tests\test_color.py`, `tests\test_curves.py`, `tests\test_tanda2.py`, `tests\test_tanda3.py`, `tests\test_gaps_audio.py`, `tests\test_silence.py`, `tests\test_voice_auto.py`, `tests\test_image_feedback.py`, `tests\test_moment_feedback.py`, `tests\test_texto_tachado.py`
(ejecutar con `.venv\Scripts\python.exe`).


## ✍ Ortografía de tus textos (octubre 2026)
En el texto en pantalla (Inspector), las frases del edit musical y los textos de las miniaturas (nada que ver con la
transcripción): subrayado rojo ondulado, clic derecho → sugerencias («despues» → después, «aora» → ahora, «porfavor»
→ por favor, «becuase» → because), «📖 Añadir al diccionario» (se guarda en tu diccionario personal) o «Ignorar».
Idioma común a todos los cuadros: **Mixto** (español de México + inglés; por defecto), Español (México), English o Sin
corregir. Acepta el español de México («chido», «órale», «güey») y vocabulario gamer («gameplay», «speedrun», «boss»).
Diccionarios Hunspell de LibreOffice (es_MX: GPL/LGPL/MPL; en_US: SCOWL) en `editoria/assets/diccionarios` con sus
licencias, leídos con spylls (MPL-2.0). Funciona sin internet. No revisa gramática (esta/está).


## 📺 Texto de los Shorts: a lo mucho 3 palabras, grande, sobre el borde del video (octubre 2026)
- Estilo **«Shorts · 3 palabras»** (el de los Shorts por defecto; «Mis Shorts», el anterior, sigue en la lista): letra
  blanca muy gruesa (Segoe UI Black), sombra suave difuminada, centrada sobre el borde de abajo del video del medio
  (~66 % de la altura) y a lo mucho 3 palabras a la vez. Los bloques se eligen probando todas las formas de partir cada
  frase: nunca acaban en «de / la / el…» («Rumor del día» va junto), casi nunca una palabra sola, y un bloque largo
  pasa a 2 líneas en vez de cortarse. Panel «Subtítulos»: «Palabras a la vez» y «Sombra suave».
- Panel **«Texto → 📺 En pantalla»** (derecha): los bloques en orden y sincronizados; lo que suena ahora, grande y en
  naranja, siempre a la vista; lo que ya pasó, apagado. Clic = el cabezal salta ahí; doble clic = corregirlo (con
  ortografía; si cambias el número de palabras se reparten en el mismo tramo). Sin subtítulos puestos aún, muestra la
  sugerencia (cómo quedarían).
- El visor ya dibuja «Segoe UI Black» / «Arial Black» igual que al exportar (antes, sin ventana, caía en Arial).


## ⋮ Opciones rápidas en Medios, 🔄 Reinicio y 🤝 Claude (octubre 2026)
- **«⋮»** al final de cada archivo de Medios: 🗑 Eliminar de Medios (el archivo no se borra) · 📂 Mover a… ·
  🎵 Separar audio (grabación de OBS con varias pistas → tu micrófono y el juego por separado; con una pista → su
  audio aparte) · ✂ **Cortar en cada cambio de escena al ponerlo en la línea de tiempo** (lo arrastras y llega ya
  cortado; si no hay cambios de escena, entero; Ctrl+Z quita los cortes; en Medios se ve «✂ por escenas»).
- Las pistas de OBS **ya no se separan solas** al importar: solo si eliges «Separar audio».
- Menú **🔄 Reinicio → Reinicio de proyecto**: empieza de cero en esta pestaña (línea de tiempo, Medios, subtítulos,
  marcadores). Antes guarda una copia de seguridad («… antes del reinicio»); tu .eia y tus videos no se tocan.
- **🤝 Dejar que Claude edite conmigo** (menú Ayuda; apagado por defecto): Claude, desde su app o Claude Code, puede
  editar tu proyecto con las funciones de Reclaimer (silencios, subtítulos, textos, cortes, exportar, capturas…).
  Solo en tu PC (127.0.0.1 con clave), todo con Ctrl+Z, nunca pisa archivos. Reclaimer funciona igual sin esto.

## ▭ Quitar barras negras · ✦ pastilla «fx» · edits sin repetir (28/10/2026)

- **▭ Quitar barras** (encima de la línea de tiempo): detecta solas las franjas negras de los videos (a los lados o
  arriba y abajo) en los clips seleccionados o, si no hay ninguno, en todos, y el video se encuadra como si no las
  tuviera: se amplía y el fondo desenfocado tampoco las lleva (en el visor y al exportar). Ctrl+Z o volver a
  pulsarlo las devuelve. Una escena oscura o una pantalla en negro no hacen que recorte de más.
- **✦ Pastilla «fx»** en la barra de título de los clips con efectos de imagen (no cuentan los fundidos ni la
  transición): al pasar el ratón dice cuáles; **clic** = seleccionarla y **Supr** = quitarlos; **clic derecho** =
  quitar uno concreto. Ctrl+Z los devuelve.
- **Edits musicales sin repetir**: no vuelve a la misma escena (entre cortes de cámara) hasta haber usado todas;
  los mismos segundos, casi nunca. Los efectos descansan el doble y, cuanto más se han usado, menos salen.
- **Ver qué hace cada efecto**: al pasar el ratón por un efecto, la toma de muestra **sin** y **con** el efecto,
  lado a lado y a la vez (iconos más grandes).

## 🎬 Escenas sin usar (IA ✨ → Inicio, debajo de las herramientas)

Las escenas de tus videos (entre cortes de cámara; las largas, en trozos de 8 s) que aún no salen en la línea de
tiempo, con su miniatura. Elige las que quieras (Ctrl+clic: el número es el orden en que las eliges) y:
- **➕ Añadir a los huecos**: van, en tu orden, a los huecos de la pista de video que tienen audio debajo. Si la
  canción tiene su ritmo reconocido, cada plano termina en un golpe (como mucho 2 compases); si no, cada escena
  dura lo que dura.
- **Desde cero**: vacía la pista de video en el tramo de la canción y la rellena SOLO con esas escenas, un plano
  por compás, turnándolas en tu orden (cada vez que vuelve a una, sigue por donde se quedó).
Un Ctrl+Z lo deshace. La lista se pone al día sola al editar.

## ⚡ Subtítulos sin cortes (04/11/2026)

- **«⚡ Subtítulos para Short»** transcribe solo el texto (modo rápido) y **no busca errores al hablar** (bostezos,
  titubeos, respiraciones, tomas repetidas): eso sigue en Limpieza → «Transcribir y analizar».
- Arreglado: en videos de más de un minuto Whisper podía quedarse escribiendo «... ... ...» y saltarse frases (los
  subtítulos desaparecían). Además, si un tramo con voz se queda sin texto, se vuelve a escuchar solo.

## 🖼 Miniatura como página · ◇ Deformar · Medios comunes (04/11/2026)

- **🖼 Miniatura** (abajo, o Ctrl+Mayús+M) es una página más, como en Resolve: el taller ocupa toda la ventana y al
  pulsar «Editar» (u otra página) todo vuelve como estaba. La miniatura se guarda con el proyecto.
- **◇ Deformar** (barra del taller): arrastra cada esquina de lo elegido a donde quieras (perspectiva libre, como
  «Distorsionar» de Photoshop). «↺» la quita; Ctrl+Z la deshace. Se exporta igual que se ve.
- **≈ Licuar** (barra del taller, como «Licuar» de Photoshop): pinta sobre lo elegido para **inflar**, **encoger**,
  **empujar** o **restaurar** (mantén pulsado para más). Tamaño y fuerza en el panel derecho. **Caras
  graciosas de un clic** sobre la cara más grande de una imagen: 👀 Ojos saltones, 👄 Bocota, 🗿 Cabezón,
  😁 Sonrisota, 🥴 Cara estirada, 🤏 Carita. Cada clic o trazo se deshace con Ctrl+Z; «↺ Quitar licuado» lo quita.
- **Capas** (columna entre el panel izquierdo y el lienzo, siempre a la vista): arriba = delante, con miniatura;
  arrastra para cambiar el orden. **🗑 Eliminar** quita lo seleccionado y **Eliminar todo** quita todas las capas
  (las bloqueadas se quedan; Ctrl+Z las recupera). **↖ Seleccionar** (o Esc) vuelve al ratón normal.
- **✋ Estirar** (junto a «≈ Licuar»): agarra lo que hay dentro del círculo y llévalo con el ratón; lo de alrededor se
  estira con ello (si deja estela, agranda el círculo).
- En la capa elegida de la lista: **👁 ocultar** y **🗑 eliminar**; clic derecho = más opciones. Al elegir otra
  imagen, la herramienta activa (Licuar, Estirar, Deformar, pinceles) se apaga: vuelve el ratón normal.
- **Ctrl+C / Ctrl+V** en el lienzo o en «Capas»: copia lo elegido (con sus efectos) y lo pega encima. También pega
  una imagen copiada en otro programa.
- **Arrastrar y soltar**: imágenes o carpetas del Explorador o del escritorio sobre «Material» (entran también en
  «Medios»), o sobre el lienzo (caen donde las sueltas; de un video, un fotograma).
- **⇱ Mejorar ×2 / ×4** (panel de la imagen): agranda con IA (EDSR / FSRCNN de OpenCV, en tu PC). Dice si una
  imagen se ve borrosa (agrandada más de ×1.3).
- **🔎 PNG → «Sin marca de agua»** (encendido): quita de Google los bancos de imágenes que ponen marca de agua
  (Shutterstock, iStock, pngtree…) y avisa si usas una de ellos.
- El selector de color ya no sale teñido del color elegido, y los diálogos de Qt salen en español.
- **Efectos más rápidos** (contorno, sombra, brillo): una imagen grande que se ve pequeña se calcula a su tamaño
  visible (un logo de 4200 px a ×0.17: de ~10 s a ~0,25 s por cambio). Sus valores tienen **barrita + número**
  a la derecha (se escribe o se arrastra; se aplica al parar). La sombra y el brillo tienen además «Opacidad».
- **🪄 Combinar con lo de abajo** (panel de la imagen): «Integrar» le da la luz, las sombras, el tono y el grano de
  lo que tiene debajo (unos ojos encima de una cara dejan de parecer pegados); «Fundir», además, la mezcla como
  impresa en la piel. Sale como capa nueva; la original queda oculta debajo. «Fuerza» = cuánto.
- **🔍 Zoom**: Ctrl + rueda sobre el lienzo (donde está el ratón), o − 100 % + en la barra (100 % = encajar,
  Ctrl+0). Lo que se sale del encuadre se ve en tenue. Botón del medio del ratón = moverse.
- **▦ Guías** (barra): centro, tercios, cuartos, o «Lo que tapa YouTube» (la duración en los videos; la barra, los
  botones y el título en los Shorts). No salen al exportar.
- **📁 Carpetas** (en «Material»): tus carpetas de material (Fuego, Ojos, Agua…) en orden de abecedario, cada una
  con su portada. «＋ Carpeta» crea una; suelta imágenes encima (se copian dentro). Doble clic = entrar, «⬅» =
  volver. Clic derecho en una imagen: «⭐ Poner como principal» (la portada) o «🗑 Eliminar» (a la Papelera).
  «🔗 Vincular…» (o soltar una carpeta del Explorador) muestra una carpeta tuya del disco en su sitio, carpeta
  dentro de carpeta, sin copiar ni borrar nada en ella («Quitar de la lista» la deja como estaba). Sugiere las
  carpetas de imágenes que encuentra en tus discos.
- **Medios comunes**: lo que importas en 🎬 YouTube, 🎵 Edits o 📱 Shorts aparece también en las otras pestañas (sin
  tocar su línea de tiempo).
- **🎨 Mi estilo**: arrastra carpetas o imágenes a las listas, o usa «Carpeta…» / «Imágenes…».
- **🔥 Tu estilo en un clic** (pestaña Texto): «Texto de impacto» (Anton blanca, la *palabra entre asteriscos* en
  rojo, borde negro y resplandor rojo), «Recuadro del logo» y «Marco rojo a lo elegido». Anton viene con Reclaimer.
- **🔎 PNG** (pestaña del taller): escribe «fuego» y Enter → Google Imágenes con solo PNG de fondo transparente.
  Clic derecho en una → «Usar en la miniatura»: se baja la imagen grande, se comprueba y, si trae un fondo liso
  (blanco, negro), se le quita. Abajo dice qué es («PNG transparente · 1600×1200»).
- **✨ Propuestas** salen de tu imagen («🖼 Usar una imagen mía…» o la que tengas en el lienzo) y siempre son 3.

## 🖥 Intel, NVIDIA y AMD (04/11/2026)

- **Exportar, Convertir y las copias ligeras** usan la tarjeta gráfica que tenga el equipo: **NVIDIA** (NVENC),
  **AMD** (AMF) o **Intel** (Quick Sync), con los ajustes de calidad de cada una. Se elige sola (con NVIDIA + gráficos
  Intel, la NVIDIA). Sin ninguna, el procesador. La ventana Exportar dice cuál usa.
- **Transcribir**: con una NVIDIA, Whisper va en la tarjeta (CUDA, mucho más rápido) si `INSTALAR.bat` instaló sus
  librerías (lo hace solo al ver una NVIDIA); si no, el procesador en int8, que en Intel y AMD ya va muy optimizado.
- **Motor de IA avanzada**: PyTorch CUDA en NVIDIA, ROCm en AMD.
- Ayuda → Diagnóstico: con qué tarjeta exporta y dónde transcribe.

## 🪶 Equipos modestos y gráficas de 4 GB (05/11/2026)

Reclaimer mide el equipo una vez (RAM, núcleos, memoria de la gráfica) y elige solo lo ligero; todo se cambia a mano
y Ayuda → Diagnóstico dice qué eligió (fila «Equipo»).
- **Menos de 12 GB de RAM o 4 núcleos o menos**: transcripción «Rápido» y vista previa a media calidad (copias
  ligeras) de entrada.
- **Gráfica con menos de 6 GB**: el recorte con IA usa el modelo «Rápida» y guarda lo que recuerda de cada fotograma
  en la RAM (no en la tarjeta); con NVIDIA, Whisper en modo int8+float16 (la mitad de memoria). Separar voz, si la
  tarjeta se queda sin memoria, sigue con el procesador en vez de fallar. En NVIDIA antiguas (GTX 10/16) el recorte
  usa float16 en vez de bf16.

## 🖼 Miniatura: arrastrar, llenar, Ctrl+X y barra de mejora (05/11/2026)
- **Arrastra** cualquier imagen de «Material» (también los «🔎 PNG») al lienzo: se pone donde la sueltes.
- **⛶ Llenar el lienzo** (panel de la derecha, «Posición»): la imagen elegida cubre toda la miniatura.
- **Ctrl+X** quita lo elegido; **Ctrl+V** lo vuelve a poner en el mismo sitio.
- **⇱ Mejorar ×2 / ×4**: barra de 0 a 100 % (en el panel y abajo, aunque elijas otra capa).

## 🖼 Miniatura: más cómoda (05/11/2026)
- **Clic derecho en una capa** (en «Capas» o en el lienzo): cortar, copiar, pegar, duplicar, orden, voltear,
  ocultar, bloquear, llenar el lienzo, fondo desenfocado, quitar fondo, mejorar ×2/×4, cara graciosa, quitar
  deformación/licuado y eliminar (y «❓ ¿Qué hace esto?» al final).
- **⬚ Recortar con los lados**: el rectángulo del centro de cada lado recorta por ahí (el otro lado no se mueve).
  Va fluido: la imagen se procesa una sola vez, al soltar.
- **Guías inteligentes**: al mover, se pega a los bordes y centros de las otras capas y del lienzo (Ctrl = sin pegarse).
- **Alt+arrastrar** = arrastrar una copia · **Alt+rueda** = agrandar/achicar lo elegido.
- **Varias capas**: Mayús+clic (o Ctrl+A todas); se mueven, se empujan con las flechas y se borran juntas. Esc suelta.
- **Doble clic en un texto** del lienzo: a escribirlo. **Ctrl+RePág / Ctrl+AvPág**: adelante / atrás (con Mayús, del todo).
- **🌫 Fondo desenfocado detrás** (panel «Posición» o clic derecho): la misma imagen, llenando la miniatura,
  desenfocada y oscura, detrás del sujeto.
- **📐 Plantillas** (barra de arriba): guardar una miniatura como plantilla y reutilizar su composición.
- **📱 Pasar a Short** (barra, en la de YouTube): crea la vertical a partir de la de YouTube.

## ⚡ Editar más rápido (06/11/2026)

- **🔴 Cortes dudosos**: tras quitar silencios, cada corte de la voz que se come una palabra, queda pegado o corta con
  la voz sonando sale como una **línea roja** en la línea de tiempo (motivo al pasar el ratón). «⚠ N cortes» en la
  barra de la línea de tiempo con ◀ ▶ (o **Alt+← / Alt+→**) te lleva a cada uno. Clic en la línea roja: ajustar
  «Antes / Después del corte» (−40, +40, +120 ms), «▶ Escuchar», «✓ Está bien así» o «↺ Devolver todo el silencio».
  El ajuste mueve todas las pistas (el B-roll no se desincroniza) y el aviso se quita solo al arreglarlo.
- **🎬 Clips · carpetas por palabra** (pestaña junto a «Momentos»): ten una carpeta (por defecto
  `Vídeos\Reclaimer - Clips por palabra`, «Cambiar…» para elegir otra) con una subcarpeta por tema —«Fortnite»,
  «Minecraft», lo que quieras— llena de TUS videos e imágenes. «Dijiste…» lista lo que nombras en la narración
  («Fortnite · 3 veces») con «📁 12» si ya tiene carpeta (12 archivos) o «＋» si no. Los nombres de tus carpetas
  también se buscan en lo que dices. Alias con coma: una carpeta «Fortnite, fortnait» vale para las dos.
  Al elegir una palabra ves su carpeta en miniaturas: «＋ Crear carpeta» si no existe, suelta ahí archivos o carpetas
  desde el Explorador (se copian) o en la propia palabra de la lista. Doble clic = ponerlo donde lo dices.
- **🖼 Imágenes encima del video**: suelta una imagen en una pista de video encima de otra: dura hasta que acaba la
  frase que dices ahí (1,5–6 s), centrada con sombra, entrada suave y el video de debajo desenfocado solo en ese
  tramo. Clic derecho → «🖼 Estilo de imagen» (esquina, costados, pantalla completa, sin animación) y «⏱ Ajustar a la frase».
- **⚡ Revisión rápida con teclas** (menú IA, **Ctrl+Mayús+Q**, o «Limpieza»): una a una, las propuestas de la IA y
  los cortes dudosos; **Enter** acepta, **Supr** rechaza, **→/Espacio** salta, **←** vuelve, **P** escucha.
  La «✨ Primera versión automática» la ofrece al terminar.
- **📋 Plantillas de proyecto** (Archivo): «Guardar como plantilla…» (formato, pistas, estilo de subtítulos…; sin
  clips) y «Nuevo desde plantilla ▸».
- Estilo cinematográfico: cada cambio de tema empieza con plano nuevo, fundido y whoosh. «Más impacto visual» da zoom
  a TODOS los clips elegidos.
- Miniatura: **⚖ Comparar A/B** (A y B se guardan con el proyecto).

- **🔴 Cortes dudosos, más rápido** (06/11): pulsa «⚠ N cortes» y sale la LISTA de todos (clic = ir ahí). Cada uno
  trae «💡 Sugerencia» (p. ej. «Recuperar 160 ms después del corte para no comerse «bienvenidos»») con
  «✓ Aplicar sugerencia» (y pasa solo al siguiente) o «✓ Aplicar todas las sugerencias» (un solo Ctrl+Z). En la
  revisión rápida: Enter aplica la sugerencia, O = está bien así.
- **🎬 Clips, más listo** (06/11): al elegir un tema, banderitas cian en la línea de tiempo donde lo dices (✕ las
  quita). «📍 Poner donde lo dices» coloca el clip en esos momentos (dura lo que queda de la frase, salta los logos,
  sin sonido, en una pista libre; un Ctrl+Z). Con varios archivos elegidos se reparten: momento 1 → archivo 1,
  momento 2 → archivo 2… «⏵ Poner en el cabezal» lo pone donde está la línea roja. Clic derecho en una miniatura:
  poner, abrir, mostrar en la carpeta o quitarla (a la Papelera, preguntando). Los momentos se encuentran también si
  la narración está dentro de un clip compuesto ⧉.

- **Miniatura · Material** (06/11): las imágenes que pones desde tus carpetas (📁 Carpetas, el Explorador, «Imagen
  desde archivo») se quedan en «Material» como «📁 nombre», también en otros proyectos. Clic derecho (o Supr):
  «✕ Quitar» (de la lista, o de Medios si venía de ahí; el archivo se queda), «🗑 Eliminar el archivo» (a la Papelera,
  preguntando antes) y en los «🔎 PNG», «🗑 Borrar este PNG».

- **✂ Eliminar silencio, más claro** (06/11, como DaVinci Resolve): a la vista solo Umbral, Antes del inicio,
  Después del final, Mínimo a eliminar, Fundido cruzado y «Se quitarán N silencios · tiempo»; lo demás (detección,
  protección de la voz, clics, IA, palabras, lo aprendido, ajustes guardados…) en «⚙ Más opciones» (recuerda si lo
  dejaste abierto). En la línea de tiempo, lo que se va a quitar se OSCURECE dentro de la pista que se corta, con una
  línea fina en cada borde; las demás pistas solo llevan una marca fina en la regla.

- **🧭 Montaje guiado** (06/11, página junto a «Editar»): los pasos para editar rápido, en orden, cada uno con su
  estado y su botón: 1 🗂 Importar · 2 ✂ Quitar silencios · 3 ⚠ Revisar cortes dudosos («Revisar» / «Aplicar
  todas») · 4 🎬 Clips para lo que dices («N palabras · M con carpeta») · 5 ⚡ Revisión rápida · 6 🖼 Miniatura ·
  7 🚀 Entrega. Se ve a la vez que el panel 🎬 Clips. Es el mismo proyecto que en las demás páginas: lo que hagas
  aquí sigue ahí al pasar a Editar, Miniatura, etc.

- **↪ Mover este proyecto a** (06/11, Archivo, o clic derecho en las pestañas YouTube / Edits / Shorts): si editaste
  en la pestaña equivocada, el proyecto pasa a la otra con su formato (resolución, encuadres, subtítulos) y su
  historial: Ctrl+Z devuelve el formato anterior. Si la otra pestaña tenía un proyecto, pregunta y lo guarda en las
  copias de seguridad.
- **Más ligero: cada función trabaja cuando la usas** (06/11). Para subtitular ya no se gasta nada en lo demás:
  · el aprendizaje de tu voz ya no corre después de cada transcripción: se apunta y se aprende al usar
    «✂ Eliminar silencio» (o Voz → Entrenar);
  · el análisis de clips con IA solo se hace solo en la sesión en la que lo pediste (al volver a abrir, no arranca);
  · copias ligeras: solo las de la calidad que eliges (en «Completa», ninguna; Reproducción → «Tener las copias
    ligeras listas también en «Completa»» si las quieres de antemano);
  · los paneles ocultos (Texto, 🎬 Clips, 🧭 Montaje guiado) no recalculan nada hasta que los abres, y el espectro del
    ecualizador solo se calcula si se ve (y ya no congela la ventana).

- **⚡ Licuar y Estirar fluidos** (06/11, miniatura): con una imagen con contorno, brillo o sombra, cada movimiento
  del ratón rehacía esos efectos (1–3 s por movimiento). Ahora se preparan una vez (en segundo plano al activar la
  herramienta) y al arrastrar solo se deforma la imagen ya hecha: ~20 ms por movimiento (~60 ms con fotos enormes).
  Al soltar, la versión buena se termina sola en segundo plano sin congelar la ventana.

- **Miniatura, más rápida y con más herramientas** (06/11):
  · ⚡ Licuar / Estirar suaves de verdad: ~5 ms por movimiento (antes ~200 ms) y soltar sin congelar (~12 ms).
  · La capa elegida en «Capas» es la que se mueve en el lienzo aunque pinches encima de otra; para elegir otra en el
    lienzo, doble clic (en un texto, además, se abre para escribir).
  · 🖼 Buscar fondo: en «🔎 PNG», modo «🖼 Fondo» (imágenes grandes con la forma de la miniatura); clic derecho →
    «Usar de fondo» la pone detrás de todo cubriendo el lienzo.
  · Barra flotante del texto (aparece encima del texto elegido): color, fuente, A−/A+, negrita, cursiva,
    izquierda/centrado/derecha, contorno (color y grosor), sombra (suave/dura/larga), brillo y 🔥 Mi estilo.
  · 🌫 Desenfocar la capa entera: clic derecho → «Desenfocar» (fuerza en «Desenfoque» del panel).
  · 🌫 Zona borrosa: botón «🌫 Borroso ▾» → Círculo o Cuadrado, se dibuja arrastrando y se estira con las esquinas
    (libre; Mayús = proporcional) y los lados; desenfoca lo que hay debajo («Fuerza» en el panel).
  · 😜 Caras graciosas: 27 gestos en 4 grupos (👀 Ojos: entrecerrados, mirar arriba/abajo/izquierda/derecha, bizco,
    guiño… · 😮 Emociones: sorpresa, miedo, felicidad, risa, tristeza, enojo, asco, duda · 🗿 Cabeza · 👃 Rasgos),
    con Intensidad (Suave / Normal / Exagerado) y «Todas las caras».

- **🖱 La rueda ya no cambia valores sin querer** (06/11, en todo el programa): números, deslizadores, desplegables y pestañas
  solo cambian con la rueda si les das clic y giras sin sacar el ratón de encima; si no, la rueda desplaza el panel
  (aunque la casilla siga con el foco).

- **⚡ Edición más fluida** (06/11, medido con un proyecto grande):
  · Línea de tiempo: arrastrar un clip 2–5 ms por movimiento (antes ~23), recortar 3–5 ms (antes 35–40), mover el
    cabezal por la regla 2 ms (antes 17). Deseleccionar ya no pone un contorno naranja que se comía 1,9 s de CPU.
    El imán es instantáneo; el panel Texto ya no se rehace si solo mueves B-roll.
  · Vista previa: video con subtítulos 59,6 fps (antes 48–55); Short con fondo desenfocado y subtítulos 58,8 fps
    sin tirones (antes 27–45); B-roll pesado 46,7 fps (antes 34–40). Las flechas avanzan fotograma a fotograma y
    muestran el fotograma exacto; arrastrar el cabezal enseña 12–17 de 30 fotogramas (antes 2–5). Se precarga el
    siguiente B-roll (menos tirones en los cortes) y, si ya existen copias ligeras, se usan en «Completa» cuando el
    visor es pequeño (sin crearlas en segundo plano).

- **Editar más rápido, 2.ª tanda** (06/11):
  · ✨ Primera versión automática: el B-roll ya NO repite escenas (0 tramos solapados; antes miles), usa casi todo tu
    material y respeta tus carpetas por tema (72 % de planos del tema correcto, antes 1 %); las imágenes y capturas
    van ENCIMA con fondo desenfocado y sombra (no a pantalla completa); la música se une con fundidos; y al final
    aplica solo las sugerencias de los cortes dudosos (en la prueba, 16 → 0).
  · Arreglado un fallo grave: tras «✂ Eliminar silencio», todos los trozos de la narración quedaban vinculados entre
    sí (un clic los elegía todos y Supr borraba la narración entera). Ahora cada trozo va solo con su sonido, y los
    proyectos antiguos se reparan al abrirlos.
  · Más fluido: rueda de la línea de tiempo 7–11 ms (antes 12–35), borrar un B-roll ~26 ms, color de la vista previa
    en 4 hilos (1080p: 26 → 11 ms).
  · ✂ Shorts desde este video (propone tramos de 45–75 s y crea cada Short aparte, en vertical).
  · 📝 Descripción para YouTube (Ctrl+Mayús+K): párrafo, capítulos, créditos, tu pie fijo y hashtags; al exportar se
    guarda <video>.descripcion.txt. ⚕ Revisión antes de exportar con «Ir» en cada aviso.
  · 🖥 Visor en la segunda pantalla (F11). ✏ Doble clic en un subtítulo del visor = corregirlo. Las correcciones de
    palabras (panel Texto, visor) se deshacen con Ctrl+Z y conservan la puntuación.
  · 🎬 Mi intro y mi outro (por tipo de proyecto, también en la Primera versión). 🔎 Buscar en lo que dijiste
    (Ctrl+Alt+F): «3 de 12», ◀ ▶ y marcas en la línea de tiempo.

- **Editar más rápido, 3.ª tanda** (06/11, tras investigar Resolve 20, Premiere, Descript, Gling, TimeBolt, AutoCut…):
  · 📜 Montaje desde el guion: pega tu guion (una oración por línea) → elige la mejor toma de cada línea, quita las
    demás, marca lo que falta (rojo) y lo improvisado (amarillo, no se quita) y coloca [CLIP: tema] / [IMG: nombre];
    [MÚSICA: …] y [NOTA: …] quedan como marcadores. Un solo Ctrl+Z.
  · 🔖 Marcas de OBS: si al grabar pulsas la tecla «Añadir marcador de capítulo» de OBS (formato MP4 híbrido) cuando
    te equivocas, Edición → «Leer marcas de OBS» las pone en rojo y «Fallos marcados» propone quitar cada frase
    fallida (una a una o todas).
  · ✂ Reordenar con el texto: en el panel Texto, selecciona frases, Ctrl+X, pon el cursor y Ctrl+V: se mueve la voz
    con su B-roll, sin huecos (Ctrl+C copia). Nota: el texto del panel sigue en el orden en que lo grabaste.
  · 🎵 Ajustar la música a la duración (Edición): la canción se alarga o acorta por compases, conservando intro y
    final; también en la Primera versión.
  · Línea de tiempo: la regla se queda fija arriba al desplazarte por las pistas; Alt + rueda desplaza las pistas en
    vertical; un proyecto nuevo empieza con 1 pista de video y 1 de audio (las demás se crean solas al hacer falta).

- **07/11**:
  · 🔑 Palabras clave en Medios: una sección con una carpeta por palabra (Fortnite, GTA 6…). «✨ Crear de lo que
    dices» las crea a partir de tu narración; suelta CARPETAS de tu PC sobre una palabra para enlazarlas (no se
    copian) o archivos sueltos para copiarlos; «📂 Añadir carpeta de mi PC…»; selecciona archivos y «📍 Poner donde
    lo dices». Quitar una palabra manda a la Papelera solo la carpeta de Reclaimer: tus carpetas del PC nunca se
    borran, solo se desvinculan.
  · «Dijiste…» entiende nombres compuestos: «GTA 6» (también «GTA seis», «GTA VI», «G.T.A. 6»), «Zelda Ocarina of
    Time», «Resident Evil 4», «Call of Duty Black Ops 6», «Nintendo Switch 2»… sin pegar números sueltos («jugué
    Fortnite dos horas» sigue siendo «Fortnite»).
  · Importar es ligero: solo se lee la duración y la miniatura; la onda de audio se calcula al meter el clip en la
    línea de tiempo (o cuando una función la necesita) y las copias ligeras solo de lo que está en la línea de
    tiempo. «◈ Analizar a fondo lo seleccionado en Medios» si lo quieres antes.
  · El panel Texto muestra el orden de la línea de tiempo (tras reordenar con Ctrl+X/V). Reclaimer se cierra al
    momento aunque haya un análisis en marcha.

  · Vista previa sin tirones al cambiar de clip (de 35 por minuto a 0 en la prueba): la precarga deja listo el
    fotograma del siguiente plano, V1 tapado ya está en su punto al destaparse y el corte llega a tiempo. Reproducción
    → «Decodificar el video con la tarjeta gráfica» (desactivado = más suave, algo más de CPU; activado en PCs
    modestos; se aplica al reiniciar).
  · Medios: clic derecho en un video → «🔑 Añadir en la palabra clave seleccionada» (las marcas azules de la regla)
    y «🔑 Añadir en todas las «PlayStation» (N)». «⟲ Reiniciar todo» quita todos los medios de todas las
    categorías (sin borrar tus archivos; pregunta qué hacer con los que estén en la línea de tiempo y, si marcas la
    casilla, borra también sus miniaturas y datos guardados). Las guías del visor empiezan en 9:16 en Edits y
    Shorts (16:9 en YouTube) y se recuerdan por pestaña.
  · 🔑 Los clips de las palabras clave van todos en la MISMA pista, uno tras otro: si uno nuevo empieza antes de que
    acabe el anterior, el nuevo lo corta. Nunca se añade su sonido (tampoco al hacer doble clic o «▶ Añadir a la
    timeline» en un archivo de una palabra clave: va en el cabezal, en esa pista y en silencio).
  · ⇆ **Alt + rueda encima de un clip elegido**: el clip (con su sonido vinculado) se desliza hacia atrás o hacia
    delante sin cambiar de tamaño, suave. Se detiene al tocar el clip de al lado, se pega un instante a las palabras
    clave y al cabezal, y el visor enseña el cuadro en vivo. Al dejar de girar (o al soltar Alt, o con un clic) se
    aplica: un solo Ctrl+Z. En otro sitio, Alt + rueda sigue subiendo / bajando las pistas.
