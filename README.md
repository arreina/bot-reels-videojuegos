# Bot de reels de noticias de videojuegos

Pipeline local que convierte noticias de videojuegos en reels verticales (1080x1920)
listos para publicar, con guion en **español de España**, voz sintética, música de
fondo y cortes de vídeo de archivo. Se maneja desde el móvil a través de una
interfaz web servida por el propio PC.

Dos criterios de diseño que atraviesan todo el proyecto:

- **Nada de copyright ajeno.** El fondo son clips de bancos con licencia libre
  (Pexels y Pixabay) y la música es CC BY con la atribución registrada en
  `files/musica/creditos.json`. El guion nunca copia frases textuales de la fuente.
- **Nada de automatización sin supervisión.** Siempre hay un paso humano: eliges
  la noticia, revisas y editas el guion, cambias clips o música y apruebas el
  resultado. Las plataformas penalizan las granjas de reposts.

## Cómo funciona

| Módulo | Fichero | Qué hace |
| --- | --- | --- |
| 1 | `files/noticias_reel.py` | Lee 10 feeds RSS (español, inglés y japonés), quita duplicados, traduce los titulares japoneses y escribe el guion en `guiones/<id>.json`. También se puede escribir una noticia a mano desde el móvil (botón **+**), que se guarda en `noticias_manuales.json` y aparece en el listado como una más. |
| 2 | `files/guion_a_video.py` | Locuta el guion con Piper, monta el fondo con el material que encuentra `material_real.py` (y stock libre para lo que falte), busca música en bancos libres, la mezcla con ducking, quema subtítulos y créditos y monta el mp4 con FFmpeg. |
| 2b | `files/material_real.py` | Busca imágenes REALES de la noticia: trailers oficiales del juego o de la marca en YouTube y en las fichas de Steam, los descarga con yt-dlp y los trocea en cortes de 4 s. |
| 4 | `files/servidor.py` + `files/web/index.html` | Interfaz móvil (FastAPI): listado de noticias con filtros, editor de guion, generación, buscador de clips, buscador de música y volumen, galería de vídeos ya montados y compartir nativo a Instagram/WhatsApp/Telegram. |
| 3 | *pendiente* | Publicación en YouTube Shorts / TikTok con las APIs oficiales, con aprobación manual antes de cada subida e inserción automática de la atribución de la música. |

Los guiones se generan **sin pagar API**: si no defines `ANTHROPIC_API_KEY`, el
bot llama al CLI de Claude Code (`claude -p --model sonnet`), que va contra tu
suscripción.

## Instalación

Requiere Python 3.12, `git` y el CLI de Claude Code instalado y con sesión iniciada.

```bash
# 1. Entorno
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. FFmpeg estático (el proyecto lo busca primero en bin/)
mkdir -p bin && cd /tmp
curl -sSLO https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar -xJf ffmpeg-release-amd64-static.tar.xz
cp ffmpeg-*-static/ffmpeg ffmpeg-*-static/ffprobe -t "$OLDPWD/bin/" && cd -
chmod +x bin/ffmpeg bin/ffprobe

# 3. Voz de Piper (español de España)
mkdir -p voces
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/sharvard/medium
curl -sSL -o voces/es_ES-sharvard-medium.onnx      "$BASE/es_ES-sharvard-medium.onnx"
curl -sSL -o voces/es_ES-sharvard-medium.onnx.json "$BASE/es_ES-sharvard-medium.onnx.json"

# 4. Claves de los bancos de vídeo
cp files/.env.ejemplo files/.env   # y rellena PEXELS_API_KEY / PIXABAY_API_KEY

# 5. (Opcional) Música en local. No hace falta: el bot la busca en bancos
#    libres y la cachea en files/musica_cache/ sobre la marcha.
./descargar_musica.sh
```

### De dónde sale el vídeo de fondo

Si la noticia habla de Final Fantasy XVI, el fondo es Final Fantasy XVI. El
guionista escribe en el guion un bloque `material` con el juego, la empresa y
dos o tres búsquedas en inglés, y `material_real.py` recorre esta escalera:

1. **Canal oficial de la marca en YouTube** (PlayStation, Nintendo, Square
   Enix…). Además de una lista fija de canales, se acepta como oficial
   cualquier canal que lleve el nombre de la empresa de la noticia: hay miles
   de estudios y no caben todos en una constante.
2. **La ficha del juego en Steam**, que no pide clave de API.
3. **Medios especializados** (IGN, GameSpot, Vandal…), que replican los mismos
   trailers con su marca de agua.
4. **Stock libre** (Pexels/Pixabay) para lo que falte, como hasta ahora.

De cada trailer se sacan cortes repartidos a lo largo del vídeo, saltándose los
logos del principio, la pantalla final y los fundidos a negro (se mide el brillo
del fotograma antes de cortar).

**Esto sí tiene copyright**, al revés que el stock. Se usa como lo usan los
medios: cortes de cuatro segundos, la locución por encima y el crédito
sobreimpreso arriba a la derecha ("Imágenes: PlayStation"), que sale
automáticamente del canal del que se bajó cada clip. La interfaz también enseña
el texto completo para la descripción al publicar. Aun así, YouTube puede
meterle un Content ID que desvíe la monetización al editor, e Instagram puede
silenciar el audio; y descargar de YouTube va contra sus condiciones de
servicio, aunque el uso posterior sea informativo. Si no lo quieres,
`guion_a_video.py --solo-stock` vuelve al comportamiento de antes.

### De dónde sale la música

El selector busca en dos bancos, ninguno pide clave de API:

- **Incompetech** (Kevin MacLeod): 1.442 piezas, todas CC BY 4.0. Publica su
  catálogo entero en un JSON, así que la búsqueda es local e instantánea y se
  puede filtrar por ambiente, instrumentos o descripción.
- **Openverse**: buscador Creative Commons de la fundación WordPress, que indexa
  el catálogo de Jamendo, Wikimedia y Freesound.

Solo se ofrecen licencias **CC BY, CC0 y dominio público**. Quedan fuera a
propósito las **NC** (prohíben monetizar), las **ND** (prohíben modificar la
obra, y aquí se recorta y se mezcla con la voz) y las **SA** (obligarían a
publicar el reel entero con la misma licencia libre).

## Uso

Desde el móvil (lo habitual):

```bash
./crear_certificado.sh   # una vez, y cada vez que cambie la IP del PC
./arrancar_movil.sh
```

Abre `http://<ip-del-pc>:8000` para navegar y `https://<ip-del-pc>:8443` cuando
quieras **compartir** el vídeo: Android solo habilita el menú de compartir en
contexto seguro, y descargar por HTTP deja el mp4 en Descargas, donde Instagram
Reels no lo ve. Chrome avisará una vez del certificado autofirmado
("Configuración avanzada" → "Continuar").

Por línea de órdenes:

```bash
cd files
../.venv/bin/python3 noticias_reel.py --max 5            # --dry-run para solo listar
../.venv/bin/python3 guion_a_video.py guiones/<id>.json        # música al azar del banco
../.venv/bin/python3 guion_a_video.py guiones/<id>.json --musica "epic"   # o un archivo concreto
```

## Detalles que cuesta redescubrir

- **Piper 1.6.0: no uses `--sentence-silence`.** Convierte frases alternas en ruido
  blanco puro (verificado con espectrograma). El flag está deliberadamente fuera.
- **Salida siempre en `yuv420p`.** El overlay del visualizador de onda es RGBA y
  arrastra el vídeo a `yuv444p` / perfil High 4:4:4, que ningún móvil ni Instagram
  sabe abrir. De ahí `format=yuv420p` en el filtergraph más `-profile:v high
  -level 4.0 -ar 44100 -ac 2 -movflags +faststart`.
- **El prompt hay que repetirlo en el mensaje de usuario.** Pasar las reglas de
  español de España solo por `--append-system-prompt` no basta: el CLI las diluye
  y los guiones salen en español latino.
- **El ducking necesita `threshold=0.1`.** Con un umbral bajo la narración, que es
  continua, estrangula la música 15 dB de principio a fin y la deja inaudible.
- **`alimiter` necesita `level=0`** o re-normaliza la mezcla a 0 dB.
- **El servidor debe correr con `cwd=files/`** porque los dos módulos usan rutas
  relativas. `arrancar_movil.sh` ya hace el `cd`.
- **Openverse tira un 401 con `page_size` mayor que 20** si no llevas clave de
  API. No es un fallo de credenciales aunque lo parezca: es su tope para
  peticiones anónimas. Por eso la búsqueda pagina de 20 en 20.
- **Las búsquedas de música exigen que aparezcan todas las palabras**, en las
  dos fuentes. "upbeat electronic" devuelve cero. Si una búsqueda de varias
  palabras se queda corta, `buscar_musica()` reintenta palabra por palabra.
- **El `yt-dlp` del sistema no sirve.** El de Mint (2024.04.09) solo devuelve
  storyboards de YouTube: hay que usar el del venv y actualizarlo de vez en
  cuando, porque YouTube rompe las versiones viejas.
- **Nuestro ffmpeg estático se rompe (segfault) con los HLS de Steam.** Por eso
  los trailers los baja siempre yt-dlp, incluso los de Steam.
- **Este ffmpeg no trae `drawtext`** aunque esté compilado con freetype. El
  crédito del material va por un segundo filtro `subtitles`, no por drawtext.
- **En `force_style`, `Alignment` usa la numeración vieja de SSA**, no la de
  ASS: 7 es arriba a la derecha y 9 deja el rótulo a media altura y pegado a la
  izquierda, encima de la cara del personaje.
- **Sharvard se come la L de los grupos consonánticos** ("público" → "púbico"):
  `files/pronunciaciones.json` reescribe esas palabras ("pú-blico") solo para el
  TTS, nunca para los subtítulos.

## Licencias

El código es tuyo; el material que descarga, no. Los trailers son propiedad de
su editor y se usan a título de cita informativa, con el crédito en pantalla y
en la descripción (ver "De dónde sale el vídeo de fondo"). Los clips de Pexels y
Pixabay permiten uso comercial sin atribución, pero **casi toda la música es
CC BY y la atribución es obligatoria**: al descargar una pista se guarda su crédito exacto
en `files/musica_cache/creditos.json` (o `files/musica/creditos.json` para las
locales), la interfaz lo enseña bajo el selector y debe acabar en la descripción
del vídeo publicado. El Módulo 3 lo insertará automáticamente al subirlo.
