# Datos Zurdos — canal de vídeos cortos

Canal de Instagram/TikTok que desmonta bulos de la ultraderecha y explica políticas de izquierda con datos oficiales. Lema: «Con datos, no con bulos.» Usuario: @datoszurdos (provisional).

## Reglas de contenido
- Cada cifra sale de una fuente oficial o de un verificador reconocido (INE, Seguridad Social, ministerios, Eurostat, OCDE, Maldita.es, Newtral) y se busca en la web antes de usarla. Nunca de memoria.
- La fuente aparece en pantalla en cada escena con datos.
- Si un dato tiene matices que juegan en contra, se dicen o se evita la afirmación. Avísame de ellos al entregar.
- Tono directo, algo irónico, nunca insultante. Se ataca el bulo, no a quien lo comparte. Tuteo.

## Estructura fija de cada vídeo (vertical 1080×1920, 30 fps, 30–60 s)
1. Entrada, 3 s: el logo se monta y aparece una píldora con la SECCIÓN del vídeo. Sonido: `sting.py`.
   - «BULOS vs. DATOS» (píldora roja): desmontar un bulo.
   - Secciones de política (píldora verde azulado): nombre según el vídeo, pregúntamelo si no lo digo.
2. Gancho: el bulo entre comillas + sello «BULO» rojo, o una pregunta directa en vídeos de política.
3. Datos: 3–4 escenas, una idea por escena. Etiqueta arriba en gris, cifra protagonista en amarillo, fuente abajo.
4. Mensaje: frase de cierre con enfoque de izquierdas, la parte clave en rojo + «Compártelo con quien lo necesite».
5. Cierre, 4,6 s: logo, «Con datos, no con bulos.», @datoszurdos, «Síguenos para más». Voz: «Datos Zurdos. Con datos, no con bulos.»
- Marca de agua «DATOS ZURDOS» pequeña arriba en todas las escenas menos entrada y cierre.
- Zonas seguras: nada importante por encima de y=200 ni por debajo de y=1600.

## Identidad
- Colores: fondo #0E0E12, texto #F5F5F5, gris #9696A0, rojo bulo #E63946, amarillo dato #FFD166, verde azulado #2A9D8F, superficie #282830.
- Tipografía: Inter (Black 900 titulares y cifras, Bold 700 subtítulos, Medium 500 cuerpo y fuentes). Las rutas de fuentes en `brand.py` y `video.py` apuntan a Linux: ajústalas a donde esté Inter en este equipo (instálala de Google Fonts si falta).
- Logo: tres barras de mayor a menor de izquierda a derecha (roja, roja, amarilla) sobre una línea blanca; nombre inclinado hacia la izquierda, «DATOS» blanco y «ZURDOS» rojo. Está en `brand.py` y en `assets/`.

## Cómo se hace un vídeo (código en esta carpeta)
- `video.py`: cada escena es una función `f(t)` que dibuja un fotograma con Pillow; se renderiza una escena por proceso a MP4 (`python3 video.py <índice> <carpeta>`) y se unen con el concat demuxer de ffmpeg y `-c copy`. `python3 video.py preview <carpeta>` saca un fotograma de cada escena para revisar antes de renderizar. La sección de la entrada se pasa con la variable de entorno `DZ_SECTION`. Las escenas s1–s6 actuales son las del vídeo 01 (paguitas); para un vídeo nuevo, reescribe esas funciones y la lista `SCENES` manteniendo intro y outro.
- Voz: Ludo AI (MCP `ludo`), `createSpeechPreset` con `language: "Spanish"`, una llamada por escena (máx. 250 caracteres). Antes de generar todo, haz una muestra con 2–3 voces y déjame elegir. Si te paso una grabación mía, usa `createSpeech` para clonar mi voz. Descarga los audios en cuanto estén (las URLs caducan a los 7 días).
- Música: Ludo `createMusic` (instrumental, tensa pero no dramática, tipo lo-fi/electrónica sobria, ~90 BPM, sin letra) o, si no hay créditos, `music.py`.
- Duración de cada escena = duración de su voz + ~0,7 s. La voz entra 0,3 s después de que empiece la escena.
- Mezcla con ffmpeg: voz encima; música con `sidechaincompress=threshold=0.06:ratio=2.5:attack=30:release=500` para que baje un poco al hablar pero se siga oyendo (unos 5 dB por debajo de la voz); final normalizado con `loudnorm=I=-14:TP=-1.5`. Audio AAC 192k, `-movflags +faststart`.
- Comprueba el gasto de créditos con `getAccount` antes de generar y dime cuánto va a costar.
