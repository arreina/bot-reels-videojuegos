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
| 1 | `files/noticias_reel.py` | Lee 10 feeds RSS (español, inglés y japonés), quita duplicados, traduce los titulares japoneses y escribe el guion en `guiones/<id>.json`. |
| 2 | `files/guion_a_video.py` | Locuta el guion con Piper, busca B-roll acorde a la noticia, mezcla música con ducking, quema subtítulos y monta el mp4 con FFmpeg. |
| 4 | `files/servidor.py` + `files/web/index.html` | Interfaz móvil (FastAPI): listado de noticias, editor de guion, generación, selector de clips, selector de música y volumen, y compartir nativo a Instagram/WhatsApp/Telegram. |
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

# 4. Música de fondo (CC BY, ~117 MB)
./descargar_musica.sh

# 5. Claves de los bancos de vídeo
cp files/.env.ejemplo files/.env   # y rellena PEXELS_API_KEY / PIXABAY_API_KEY
```

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
../.venv/bin/python3 guion_a_video.py guiones/<id>.json  # --voz --musica --sin-musica --broll-dir --sin-broll
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
- **Sharvard se come la L de los grupos consonánticos** ("público" → "púbico"):
  `files/pronunciaciones.json` reescribe esas palabras ("pú-blico") solo para el
  TTS, nunca para los subtítulos.

## Licencias

El código es tuyo; el material que descarga, no. Los clips de Pexels y Pixabay
permiten uso comercial sin atribución, pero **la música de Kevin MacLeod es CC BY
4.0 y la atribución es obligatoria**: el texto exacto de cada pista está en
`files/musica/creditos.json` y debe acabar en la descripción del vídeo publicado.
