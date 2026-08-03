#!/usr/bin/env bash
# Descarga las pistas de música de fondo desde incompetech.com.
# Los mp3 no van en el repositorio (pesan ~117 MB), pero files/musica/creditos.json
# guarda la lista y el texto de atribución obligatorio de cada una.
#
# OJO: incompetech devuelve HTTP 200 con una página HTML cuando el título no
# existe, así que hay que comprobar con `file` que lo descargado es audio.
set -e
cd "$(dirname "$0")/files/musica"

python3 -c 'import json; print("\n".join(json.load(open("creditos.json"))))' |
while IFS= read -r archivo; do
  [ -s "$archivo" ] && continue
  # "Kevin MacLeod - Blip Stream.mp3" -> "Blip Stream"
  titulo="${archivo#Kevin MacLeod - }"
  titulo="${titulo%.mp3}"
  echo "Descargando ${titulo}..."
  curl -sSL --max-time 120 -o "$archivo" \
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$titulo").mp3"
  if ! file -b "$archivo" | grep -qi audio; then
    echo "  ERROR: no es audio (¿título cambiado en incompetech?), se descarta"
    rm -f "$archivo"
  fi
done

echo "Listo. Recuerda que todas son CC BY 4.0: la atribución de creditos.json"
echo "es OBLIGATORIA en la descripción de cada vídeo publicado."
