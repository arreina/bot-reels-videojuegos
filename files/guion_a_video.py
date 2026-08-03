#!/usr/bin/env python3
"""
guion_a_video.py

Módulo 2 del bot de reels: toma un guion JSON (generado por noticias_reel.py)
y produce el vídeo final vertical (9:16) con:
    - Audio narrado con Piper TTS (local, gratis, sin cuenta)
    - Subtítulos grandes tipo "reel" quemados con FFmpeg
    - Fondo simple (color sólido + degradado) — sustituible luego por B-roll propio

Requisitos:
    1. FFmpeg instalado:            sudo apt install ffmpeg   (o brew install ffmpeg)
    2. Piper TTS instalado:         pip install piper-tts --break-system-packages
    3. Un modelo de voz en español descargado, por ejemplo:
       https://github.com/rhasspy/piper/releases -> buscar "es_ES" o "es_MX"
       Necesitas los 2 archivos del modelo: *.onnx y *.onnx.json
       Colócalos en ./voces/ (o ajusta VOZ_MODELO abajo)

Uso:
    python3 guion_a_video.py guiones/<id>.json
    python3 guion_a_video.py guiones/<id>.json --voz voces/es_ES-mymodel.onnx
"""

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent


def cargar_env() -> None:
    """Carga variables desde un .env junto al script o en la raíz del proyecto."""
    for ruta in (Path(__file__).parent / ".env", RAIZ_PROYECTO / ".env"):
        if not ruta.is_file():
            continue
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env()


def _localizar(nombre: str, *rutas_locales: str) -> str:
    """Busca un binario primero en rutas locales del proyecto y luego en PATH."""
    for ruta in rutas_locales:
        candidato = RAIZ_PROYECTO / ruta
        if candidato.is_file():
            return str(candidato)
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    raise FileNotFoundError(
        f"No se encontró '{nombre}'. Instálalo o colócalo en {rutas_locales[0]}"
    )


FFMPEG = _localizar("ffmpeg", "bin/ffmpeg")
FFPROBE = _localizar("ffprobe", "bin/ffprobe")
PIPER = _localizar("piper", ".venv/bin/piper")

VOZ_MODELO_DEFECTO = str(RAIZ_PROYECTO / "voces/es_ES-sharvard-medium.onnx")
SALIDA_DIR = Path("videos")
TMP_DIR = Path("tmp_video")
BROLL_CACHE = Path("broll_cache")
MUSICA_DIR = Path("musica")        # pistas propias, si las hay
MUSICA_CACHE = Path("musica_cache")  # lo descargado del banco libre
PRONUNCIACIONES_PATH = Path("pronunciaciones.json")
MUSICA_VOLUMEN = 0.20  # volumen base de la música bajo la voz (ajustable desde el móvil)

ANCHO, ALTO = 1080, 1920  # formato 9:16 (reel/short)
SEGUNDOS_POR_CORTE = 4.0  # duración de cada corte de B-roll en el fondo

# Términos de respaldo si el guion no trae "broll" (guiones antiguos)
BROLL_TERMINOS_DEFECTO = ["gaming setup neon", "video game controller", "esports"]


def construir_texto(guion: dict) -> str:
    partes = [guion["hook"], guion["cuerpo"], guion["cierre"]]
    return " ".join(p.strip() for p in partes if p.strip())


def aplicar_pronunciaciones(texto: str) -> str:
    """
    Reescribe palabras que el TTS pronuncia mal, según pronunciaciones.json.

    El diccionario es {"palabra": "reescritura fonética"}; solo afecta al audio,
    los subtítulos siguen mostrando el texto original bien escrito. La búsqueda
    ignora mayúsculas y respeta límites de palabra.
    """
    if not PRONUNCIACIONES_PATH.is_file():
        return texto
    reglas = json.loads(PRONUNCIACIONES_PATH.read_text(encoding="utf-8"))
    for original, reescritura in reglas.items():
        texto = re.sub(rf"\b{re.escape(original)}\b", reescritura, texto,
                       flags=re.IGNORECASE)
    return texto


def generar_audio_piper(texto: str, modelo: str, salida_wav: Path) -> None:
    """Llama a Piper vía CLI para convertir texto a audio."""
    # OJO: no usar --sentence-silence con piper 1.6.0: corrompe frases alternas
    # convirtiéndolas en ruido blanco (verificado con espectrograma 2026-08-02).
    proceso = subprocess.run(
        [PIPER, "--model", modelo, "--output_file", str(salida_wav)],
        input=texto,
        text=True,
        capture_output=True,
    )
    if proceso.returncode != 0:
        raise RuntimeError(f"Piper falló: {proceso.stderr}")


def duracion_audio(ruta_wav: Path) -> float:
    """Obtiene la duración del audio en segundos vía ffprobe."""
    resultado = subprocess.run(
        [
            FFPROBE, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(ruta_wav),
        ],
        capture_output=True, text=True,
    )
    return float(resultado.stdout.strip())


def _mejor_archivo_pexels(video: dict) -> dict | None:
    """Elige la rendición mp4 vertical más adecuada (~1920 de alto, sin irse a 4K)."""
    candidatos = [
        f for f in video.get("video_files", [])
        if f.get("link", "").split("?")[0].endswith(".mp4")
        and (f.get("height") or 0) >= 1080
        and (f.get("height") or 0) >= (f.get("width") or 0)  # vertical
    ]
    if not candidatos:
        return None
    return min(candidatos, key=lambda f: abs(f["height"] - ALTO))


def _mejor_archivo_pixabay(hit: dict) -> dict | None:
    """Elige la mejor rendición de un vídeo de Pixabay."""
    versiones = [v for v in hit.get("videos", {}).values()
                 if isinstance(v, dict) and v.get("url") and (v.get("height") or 0) >= 720]
    if not versiones:
        return None
    # prefiere vertical y, dentro de eso, la altura más cercana a la del reel
    return min(versiones, key=lambda v: ((v.get("width", 0) > v.get("height", 0)),
                                         abs(v.get("height", 0) - ALTO)))


def buscar_candidatos_pixabay(terminos: list[str], api_key: str,
                              por_termino: int = 15) -> list[dict]:
    """
    Igual que la búsqueda de Pexels pero en Pixabay, que tiene bastante más
    material de tecnología y videojuegos. Licencia Pixabay: uso comercial
    permitido y sin atribución obligatoria.
    """
    candidatos, vistos = [], set()
    for termino in terminos:
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": api_key, "q": termino, "per_page": por_termino,
                        "safesearch": "true"},
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [aviso] Pixabay falló para '{termino}': {e}")
            continue
        for hit in r.json().get("hits", []):
            archivo = _mejor_archivo_pixabay(hit)
            if not archivo or hit["id"] in vistos:
                continue
            vistos.add(hit["id"])
            candidatos.append({
                "id": f"pixabay_{hit['id']}",
                "enlace": archivo["url"],
                "imagen": archivo.get("thumbnail") or hit.get("pageURL", ""),
                "termino": termino,
                "autor": hit.get("user", ""),
                "fuente": "Pixabay",
                "vertical": archivo.get("height", 0) >= archivo.get("width", 0),
            })
    return candidatos


def buscar_candidatos_pexels(terminos: list[str], api_key: str,
                             por_termino: int = 8) -> list[dict]:
    """
    Busca clips verticales en Pexels (licencia libre: uso comercial permitido,
    sin atribución, se pueden modificar) SIN descargarlos todavía.

    Devuelve un banco de candidatos del que luego se eligen unos pocos; tener
    reservas es lo que permite cambiar un clip suelto sin repetir la búsqueda.
    """
    candidatos, vistos = [], set()
    for termino in terminos:
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": api_key},
                params={"query": termino, "orientation": "portrait", "per_page": por_termino},
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [aviso] Pexels falló para '{termino}': {e}")
            continue
        for video in r.json().get("videos", []):
            archivo = _mejor_archivo_pexels(video)
            if not archivo or video["id"] in vistos:
                continue
            vistos.add(video["id"])
            candidatos.append({
                "id": video["id"],
                "enlace": archivo["link"],
                "imagen": video.get("image", ""),
                "termino": termino,
                "autor": video.get("user", {}).get("name", ""),
                "fuente": "Pexels",
                "vertical": True,
            })
    return candidatos


# Solo se descargan clips de estos dominios (el buscador recibe el enlace
# desde el navegador, así que conviene no fiarse de cualquier URL).
DOMINIOS_PERMITIDOS = ("videos.pexels.com", "player.vimeo.com", "cdn.pixabay.com",
                       "pixabay.com", "vod-progressive.akamaized.net")


def buscar_candidatos(terminos: list[str], por_termino: int = 12) -> list[dict]:
    """Busca en todas las fuentes de vídeo configuradas y junta los resultados."""
    candidatos = []
    if clave := os.environ.get("PEXELS_API_KEY"):
        candidatos += buscar_candidatos_pexels(terminos, clave, por_termino)
    if clave := os.environ.get("PIXABAY_API_KEY"):
        candidatos += buscar_candidatos_pixabay(terminos, clave, por_termino)
    # los verticales primero: los horizontales hay que recortarlos mucho
    candidatos.sort(key=lambda c: not c.get("vertical", True))
    return candidatos


def ruta_de_clip(clip_id) -> Path:
    """Ruta en la caché de un clip, venga de la fuente que venga."""
    return BROLL_CACHE / f"clip_{clip_id}.mp4"


def descargar_candidato(candidato: dict) -> Path | None:
    """Descarga un clip del banco a la caché local (o lo reutiliza si ya está)."""
    if urlparse(candidato["enlace"]).hostname not in DOMINIOS_PERMITIDOS:
        print(f"  [aviso] Enlace de origen no permitido: {candidato['enlace'][:60]}")
        return None
    BROLL_CACHE.mkdir(exist_ok=True)
    ruta = ruta_de_clip(candidato["id"])
    if ruta.exists() and ruta.stat().st_size > 0:
        return ruta
    try:
        with requests.get(candidato["enlace"], stream=True, timeout=120) as descarga:
            descarga.raise_for_status()
            with open(ruta, "wb") as fh:
                for trozo in descarga.iter_content(chunk_size=1 << 20):
                    fh.write(trozo)
    except requests.RequestException as e:
        print(f"  [aviso] No se pudo descargar el clip {candidato['id']}: {e}")
        ruta.unlink(missing_ok=True)
        return None
    return ruta


def generar_miniatura(clip: Path) -> Path | None:
    """Extrae un fotograma del clip para poder verlo en la interfaz."""
    destino = BROLL_CACHE / "miniaturas" / f"{clip.stem}.jpg"
    if destino.is_file():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    proceso = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-ss", "1", "-i", str(clip),
         "-frames:v", "1", "-vf", "scale=240:-2", str(destino)],
        capture_output=True, text=True,
    )
    return destino if proceso.returncode == 0 and destino.is_file() else None


def descargar_broll_pexels(terminos: list[str], api_key: str, max_clips: int = 5) -> list[Path]:
    """Compatibilidad con el uso por línea de órdenes: busca y descarga de una vez."""
    rutas = []
    for candidato in buscar_candidatos_pexels(terminos, api_key, por_termino=3):
        if len(rutas) >= max_clips:
            break
        ruta = descargar_candidato(candidato)
        if ruta:
            rutas.append(ruta)
    return rutas


# --- Música: búsqueda en un banco libre en vez de una carpeta local ---------
#
# Se usa Openverse (api.openverse.org), el buscador de la fundación WordPress
# que indexa el catálogo Creative Commons de Jamendo, Wikimedia y Freesound.
# No necesita clave de API. Cada resultado trae ya su licencia y el texto de
# atribución, que es lo que hace falta para poder publicar sin problemas.
LICENCIAS_MUSICA = "by,cc0,pdm"
# OJO con ampliar esa lista: "nc" prohíbe el uso comercial (adiós monetización),
# "nd" prohíbe modificar la obra (y aquí se recorta y se mezcla con la voz) y
# "sa" obligaría a publicar el reel entero bajo la misma licencia libre.

DOMINIOS_MUSICA_PERMITIDOS = ("prod-1.storage.jamendo.com", "prod-2.storage.jamendo.com",
                              "storage.jamendo.com", "upload.wikimedia.org",
                              "incompetech.com", "www.incompetech.com")

# Una pista más corta que el reel se repite en bucle y se nota; una de media
# hora son 30 MB para usar 40 segundos.
MUSICA_DURACION_MINIMA = 60      # segundos
MUSICA_DURACION_MAXIMA = 12 * 60

# Ambientes de respaldo cuando nadie ha elegido pista: da variedad sin que el
# usuario tenga que buscar nada. De una palabra a propósito: las búsquedas de
# varias exigen que aparezcan todas y casi siempre se quedan sin resultados.
MUSICA_TERMINOS_DEFECTO = [
    "upbeat", "energetic", "action", "epic", "driving", "electronic",
    "synth", "aggressive", "grooving", "tech",
]


def _texto_atribucion(candidato: dict) -> str:
    """Crédito en español, listo para pegar en la descripción del vídeo."""
    licencia = candidato.get("licencia", "").upper()
    version = candidato.get("licencia_version", "")
    nombre = f"CC {licencia} {version}".strip() if licencia not in ("CC0", "PDM") else licencia
    return (f'Música: "{candidato["titulo"]}" de {candidato["autor"]} '
            f'({candidato.get("pagina", "")}), con licencia {nombre}.')


def _pagina_openverse(termino: str, pagina: int) -> list[dict]:
    """Una página de resultados. OJO: sin clave de API, page_size>20 da 401."""
    for intento in range(2):
        try:
            r = requests.get(
                "https://api.openverse.org/v1/audio/",
                params={"q": termino, "license": LICENCIAS_MUSICA, "category": "music",
                        "page_size": 20, "page": pagina},
                headers={"User-Agent": "bot-reels/1.0"}, timeout=30,
            )
            r.raise_for_status()
            return r.json().get("results", [])
        except requests.RequestException as e:
            if intento == 0:
                time.sleep(1.5)
                continue
            print(f"  [aviso] Openverse falló para '{termino}': {e}")
    return []


def buscar_musica_openverse(termino: str, limite: int = 24) -> list[dict]:
    """Busca pistas con licencia apta para monetizar, SIN descargarlas."""
    candidatos, pagina = [], 1
    while len(candidatos) < limite and pagina <= 3:
        resultados = _pagina_openverse(termino, pagina)
        if not resultados:
            break
        for pista in resultados:
            segundos = (pista.get("duration") or 0) / 1000
            if not pista.get("url"):
                continue
            if not MUSICA_DURACION_MINIMA <= segundos <= MUSICA_DURACION_MAXIMA:
                continue
            candidato = {
                "id": pista["id"],
                "titulo": pista.get("title") or "Sin título",
                "autor": pista.get("creator") or "Desconocido",
                "duracion": round(segundos),
                "enlace": pista["url"],
                "pagina": pista.get("foreign_landing_url", ""),
                "licencia": pista.get("license", ""),
                "licencia_version": pista.get("license_version", ""),
                "generos": pista.get("genres") or [],
                "termino": termino,
                "fuente": pista.get("source", "openverse"),
            }
            candidato["credito"] = _texto_atribucion(candidato)
            candidatos.append(candidato)
        pagina += 1
    return candidatos[:limite]


# Segunda fuente: el catálogo completo de Kevin MacLeod (1.442 piezas, todas
# CC BY 4.0). Publica un JSON con título, descripción, ambiente, instrumentos y
# bpm, así que la búsqueda se hace en local: ni clave, ni límites, ni esperas.
CATALOGO_INCOMPETECH = "https://incompetech.com/music/royalty-free/pieces.json"
MP3_INCOMPETECH = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
CATALOGO_VIGENCIA = 7 * 24 * 3600  # se refresca una vez por semana

# El catálogo está en inglés; esto evita que una búsqueda en español no dé nada.
SINONIMOS_MUSICA = {
    "epico": "epic", "épico": "epic", "accion": "action", "acción": "action",
    "alegre": "upbeat", "animado": "upbeat", "energico": "energetic",
    "enérgico": "energetic", "tenso": "tense", "tension": "tense",
    "tensión": "tense", "misterio": "mystery", "misterioso": "mystery",
    "terror": "horror", "miedo": "horror", "tranquilo": "calm",
    "relajado": "relaxed", "triste": "sad", "electronica": "electronic",
    "electrónica": "electronic", "futurista": "futuristic", "espacio": "space",
    "espacial": "space", "combate": "battle", "batalla": "battle",
    "carrera": "driving", "oscuro": "dark", "divertido": "humorous",
    "gracioso": "humorous", "rapido": "fast", "rápido": "fast",
    "videojuego": "video game", "videojuegos": "video game", "retro": "retro",
}


def _traducir_busqueda(termino: str) -> str:
    return " ".join(SINONIMOS_MUSICA.get(p.lower(), p) for p in termino.split())


def _segundos_hms(texto: str) -> int:
    """'00:03:48' -> 228. Devuelve 0 si el formato no cuadra."""
    try:
        partes = [int(p) for p in texto.split(":")]
    except (ValueError, AttributeError):
        return 0
    segundos = 0
    for parte in partes:
        segundos = segundos * 60 + parte
    return segundos


def _catalogo_incompetech() -> list[dict]:
    """Catálogo completo, cacheado en disco una semana (pesa ~1 MB)."""
    cache = MUSICA_CACHE / "catalogo_incompetech.json"
    if cache.is_file() and time.time() - cache.stat().st_mtime < CATALOGO_VIGENCIA:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        r = requests.get(CATALOGO_INCOMPETECH, timeout=60,
                         headers={"User-Agent": "bot-reels/1.0"})
        r.raise_for_status()
        piezas = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [aviso] No se pudo leer el catálogo de Incompetech: {e}")
        if cache.is_file():  # mejor uno viejo que ninguno
            return json.loads(cache.read_text(encoding="utf-8"))
        return []
    MUSICA_CACHE.mkdir(exist_ok=True)
    cache.write_text(json.dumps(piezas, ensure_ascii=False), encoding="utf-8")
    return piezas


def buscar_musica_incompetech(termino: str, limite: int = 24) -> list[dict]:
    """Busca en el catálogo de Kevin MacLeod por título, ambiente o descripción."""
    palabras = _traducir_busqueda(termino).lower().split()
    if not palabras:
        return []
    puntuadas = []
    for pieza in _catalogo_incompetech():
        # varios títulos del catálogo traen saltos de línea pegados; sin
        # limpiarlos, la URL del mp3 sale rota
        pieza = {k: (v.strip() if isinstance(v, str) else v) for k, v in pieza.items()}
        titulo = (pieza.get("title") or "").lower()
        resto = " ".join(str(pieza.get(c) or "") for c in
                         ("feel", "description", "instruments")).lower()
        # tienen que aparecer todas las palabras, en el título o en los datos
        if not all(p in titulo or p in resto for p in palabras):
            continue
        segundos = _segundos_hms(pieza.get("length", ""))
        if not MUSICA_DURACION_MINIMA <= segundos <= MUSICA_DURACION_MAXIMA:
            continue
        candidato = {
            "id": f"km_{pieza.get('uuid')}",
            "titulo": pieza.get("title") or "Sin título",
            "autor": "Kevin MacLeod",
            "duracion": segundos,
            "enlace": MP3_INCOMPETECH + quote(pieza.get("filename", "")),
            "pagina": "https://incompetech.com/music/royalty-free/",
            "licencia": "by",
            "licencia_version": "4.0",
            "generos": [g.strip() for g in (pieza.get("feel") or "").split(",") if g.strip()],
            "termino": termino,
            "fuente": "incompetech",
        }
        candidato["credito"] = _texto_atribucion(candidato)
        # las coincidencias en el título mandan sobre las de la descripción
        puntuadas.append((sum(p in titulo for p in palabras), candidato))
    puntuadas.sort(key=lambda par: par[0], reverse=True)
    return [c for _, c in puntuadas[:limite]]


def buscar_musica(termino: str, limite: int = 24) -> list[dict]:
    """Busca en todas las fuentes de música libre y junta los resultados."""
    def _buscar(texto: str) -> list[dict]:
        return (buscar_musica_incompetech(texto, limite)
                + buscar_musica_openverse(_traducir_busqueda(texto), limite))

    candidatos = _buscar(termino)
    palabras = termino.split()
    # Las dos fuentes exigen que aparezcan TODAS las palabras, así que una
    # búsqueda de varias suele quedarse en nada: mejor eso que devolver vacío.
    if len(candidatos) < 5 and len(palabras) > 1:
        vistos = {c["id"] for c in candidatos}
        for palabra in palabras:
            for candidato in _buscar(palabra):
                if candidato["id"] not in vistos:
                    vistos.add(candidato["id"])
                    candidatos.append(candidato)
    return candidatos[:limite * 2]


def ruta_de_pista(pista_id: str) -> Path:
    """Ruta en la caché de una pista descargada del banco."""
    seguro = re.sub(r"[^\w.-]", "_", str(pista_id))[:60]
    return MUSICA_CACHE / f"pista_{seguro}.mp3"


def creditos_del_banco() -> dict:
    ruta = MUSICA_CACHE / "creditos.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def _registrar_credito(archivo: str, candidato: dict) -> None:
    """La atribución es obligatoria: se guarda junto a la pista, no en memoria."""
    creditos = creditos_del_banco()
    creditos[archivo] = {
        "titulo": candidato["titulo"],
        "autor": candidato["autor"],
        "licencia": candidato.get("licencia", "").upper(),
        "enlace": candidato.get("pagina", ""),
        "texto": candidato.get("credito") or _texto_atribucion(candidato),
    }
    (MUSICA_CACHE / "creditos.json").write_text(
        json.dumps(creditos, ensure_ascii=False, indent=2), encoding="utf-8")


def descargar_pista(candidato: dict) -> Path | None:
    """Baja la pista elegida a musica_cache/ y registra su atribución."""
    if urlparse(candidato["enlace"]).hostname not in DOMINIOS_MUSICA_PERMITIDOS:
        print(f"  [aviso] Origen de música no permitido: {candidato['enlace'][:60]}")
        return None
    MUSICA_CACHE.mkdir(exist_ok=True)
    ruta = ruta_de_pista(candidato["id"])
    if not (ruta.exists() and ruta.stat().st_size > 0):
        try:
            with requests.get(candidato["enlace"], stream=True, timeout=120,
                              headers={"User-Agent": "bot-reels/1.0"}) as descarga:
                descarga.raise_for_status()
                with open(ruta, "wb") as fh:
                    for trozo in descarga.iter_content(chunk_size=1 << 20):
                        fh.write(trozo)
        except requests.RequestException as e:
            print(f"  [aviso] No se pudo descargar la música: {e}")
            ruta.unlink(missing_ok=True)
            return None
        try:
            duracion_audio(ruta)  # si no es audio de verdad, ffprobe se queja
        except (ValueError, OSError):
            print("  [aviso] Lo descargado no es audio reproducible, se descarta")
            ruta.unlink(missing_ok=True)
            return None
    _registrar_credito(ruta.name, candidato)
    return ruta


def musica_del_banco(termino: str | None = None) -> Path | None:
    """Elige y descarga una pista del banco (ambiente al azar si no se dice cuál)."""
    termino = termino or random.choice(MUSICA_TERMINOS_DEFECTO)
    candidatos = buscar_musica(termino)
    random.shuffle(candidatos)
    for candidato in candidatos[:5]:
        ruta = descargar_pista(candidato)
        if ruta:
            return ruta
    return None


def preparar_clips(rutas: list[Path]) -> list[tuple[str, float]]:
    """Sondea la duración de cada clip y descarta los inservibles (<1 s)."""
    clips = []
    for ruta in rutas:
        try:
            dur = duracion_audio(ruta)  # ffprobe format=duration vale para vídeo
        except (ValueError, OSError):
            continue
        if dur >= 1.0:
            clips.append((str(ruta), dur))
    return clips


def planificar_cortes(clips: list[tuple[str, float]], duracion_total: float) -> list[tuple[str, float]]:
    """Encadena cortes de SEGUNDOS_POR_CORTE ciclando los clips hasta cubrir el audio."""
    cortes = []
    acumulado, i = 0.0, 0
    while acumulado < duracion_total + 0.5:
        ruta, dur_clip = clips[i % len(clips)]
        dur_corte = min(SEGUNDOS_POR_CORTE, dur_clip)
        cortes.append((ruta, dur_corte))
        acumulado += dur_corte
        i += 1
    return cortes


def generar_srt(guion: dict, duracion_total: float, salida_srt: Path) -> None:
    """
    Genera subtítulos muy simples: reparte hook/cuerpo/cierre en el tiempo
    proporcionalmente a su longitud de texto. Para timing preciso palabra
    por palabra habría que usar alineación forzada (ej. whisper-timestamped),
    pero esto es suficiente para un primer pipeline funcional.
    """
    bloques = [guion["hook"], guion["cuerpo"], guion["cierre"]]

    # Trocea cada bloque en fragmentos de máximo 2 líneas en pantalla:
    # un bloque largo como una sola cue desbordaría el alto del vídeo.
    fragmentos = []
    for bloque in bloques:
        lineas_bloque = textwrap.wrap(bloque, width=24)
        for i in range(0, len(lineas_bloque), 2):
            fragmentos.append("\n".join(lineas_bloque[i:i + 2]))

    total_chars = sum(len(f) for f in fragmentos) or 1

    def fmt_tiempo(seg: float) -> str:
        h = int(seg // 3600)
        m = int((seg % 3600) // 60)
        s = seg % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

    lineas = []
    t_actual = 0.0
    for i, fragmento in enumerate(fragmentos, start=1):
        dur = duracion_total * (len(fragmento) / total_chars)
        inicio, fin = t_actual, t_actual + dur
        lineas.append(f"{i}\n{fmt_tiempo(inicio)} --> {fmt_tiempo(fin)}\n{fragmento}\n")
        t_actual = fin

    salida_srt.write_text("\n".join(lineas), encoding="utf-8")


def montar_video(audio_wav: Path, srt: Path, salida_mp4: Path, duracion: float,
                 clips: list[tuple[str, float]] | None = None,
                 musica: Path | None = None,
                 volumen_musica: float = MUSICA_VOLUMEN) -> None:
    """
    Monta el vídeo final:
      - Fondo: cortes de B-roll de stock libre (Pexels o clips propios) si hay
        clips disponibles; si no, gradiente animado procedural (sin copyright).
      - Música de fondo en bucle con "ducking" (baja cuando habla la voz).
      - Visualizador de audio (ondas reactivas a la voz) superpuesto.
      - Viñeta sutil para dar profundidad.
      - Subtítulos con caja semitransparente, estilo reel.
    """
    filtro_subs = (
        f"subtitles={srt}:force_style="
        "'FontName=Arial,FontSize=11,Bold=1,PrimaryColour=&HFFFFFF&,"
        "OutlineColour=&H000000&,BackColour=&H80000000&,BorderStyle=4,"
        "Outline=1,Shadow=0,Alignment=2,MarginV=50,MarginL=40,MarginR=40'"
    )

    cmd = [FFMPEG, "-y"]

    if clips:
        cortes = planificar_cortes(clips, duracion)
        for ruta, _ in cortes:
            cmd += ["-i", ruta]
        idx_audio = len(cortes)
        partes = []
        for j, (_, dur_corte) in enumerate(cortes):
            # normaliza cada corte: recorte a 9:16, mismo fps y formato
            partes.append(
                f"[{j}:v]trim=duration={dur_corte:.3f},setpts=PTS-STARTPTS,"
                f"scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
                f"crop={ANCHO}:{ALTO},setsar=1,fps=25,format=yuv420p[s{j}];"
            )
        entradas_concat = "".join(f"[s{j}]" for j in range(len(cortes)))
        partes.append(f"{entradas_concat}concat=n={len(cortes)}:v=1:a=0[bgcat];")
        # oscurece un poco el B-roll para que los subtítulos respiren
        partes.append("[bgcat]eq=brightness=-0.06:saturation=1.05,vignette=PI/5[bg];")
        fondo = "".join(partes)
    else:
        fuente_gradiente = (
            f"gradients=s={ANCHO}x{ALTO}:duration={duracion}:speed=0.02:"
            f"c0=0x1a1a2e:c1=0x5e2ca5:c2=0x0f3460:c3=0x16213e:"
            f"x0=100:y0=100:x1={ANCHO}:y1={ALTO}"
        )
        cmd += ["-f", "lavfi", "-i", fuente_gradiente]
        idx_audio = 1
        fondo = "[0:v]vignette=PI/4[bg];"

    cmd += ["-i", str(audio_wav)]

    if musica:
        idx_musica = idx_audio + 1
        # la música entra en bucle por si es más corta que la locución
        cmd += ["-stream_loop", "-1", "-i", str(musica)]
        entrada_wave = "[vozwave]"
        audio_graph = (
            f"[{idx_audio}:a]asplit=3[vozwave][vozsc][vozpre];"
            f"[vozpre]volume=0.88[vozmix];"  # deja margen para sumar la música
            f"[{idx_musica}:a]volume={volumen_musica},afade=t=in:d=1,"
            f"afade=t=out:st={max(duracion - 1.5, 0):.3f}:d=1.5[mus0];"
            # ducking: baja la música unos 4 dB mientras habla la voz.
            # OJO con el umbral: con 0.02 la voz lo supera siempre y la música
            # quedaba estrangulada 15 dB de principio a fin, es decir, inaudible.
            f"[mus0][vozsc]sidechaincompress=threshold=0.1:ratio=4:"
            f"attack=50:release=400[musduck];"
            # limitador: evita que voz+música saturen al sumarse
            f"[vozmix][musduck]amix=inputs=2:duration=first:normalize=0,"
            f"alimiter=limit=0.79:attack=5:release=80:level=0[aout];"  # techo ~-2 dB (margen para el códec AAC)
        )
        mapa_audio = "[aout]"
    else:
        entrada_wave = f"[{idx_audio}:a]"
        audio_graph = ""
        mapa_audio = f"{idx_audio}:a"

    filtergraph = (
        f"{fondo}"
        f"{audio_graph}"
        # visualizador de audio: ondas finas, color acento, semi-transparente
        f"{entrada_wave}showwaves=s={ANCHO}x400:mode=cline:colors=0x9d4edd|0xe0aaff:"
        f"rate=25,format=rgba,colorchannelmixer=aa=0.55[wave];"
        # superpone el visualizador en la zona central-baja
        f"[bg][wave]overlay=x=0:y=(H-h)/2+250:format=auto,"
        # yuv420p es OBLIGATORIO: el overlay con transparencia deja el vídeo en
        # yuv444p (perfil High 4:4:4) y ningún móvil ni Instagram sabe abrirlo.
        f"{filtro_subs},format=yuv420p[outv]"
    )

    # Ajustes exigidos por Instagram, TikTok y YouTube Shorts: H.264 perfil alto
    # en 4:2:0, audio AAC estéreo a 44,1 kHz y el índice al principio del archivo
    # (faststart) para que la app pueda leerlo sin descargarlo entero.
    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[outv]", "-map", mapa_audio,
        "-t", str(duracion),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(salida_mp4),
    ]
    proceso = subprocess.run(cmd, capture_output=True, text=True)
    if proceso.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {proceso.stderr}")


def main():
    parser = argparse.ArgumentParser(description="Convierte un guion JSON en vídeo reel con Piper + FFmpeg")
    parser.add_argument("guion_json", help="Ruta al JSON de guion generado por noticias_reel.py")
    parser.add_argument("--voz", default=VOZ_MODELO_DEFECTO, help="Ruta al modelo .onnx de Piper")
    parser.add_argument("--broll-dir", help="Carpeta con clips propios para el fondo (en vez de Pexels)")
    parser.add_argument("--sin-broll", action="store_true",
                        help="Fuerza el fondo de gradiente procedural")
    parser.add_argument("--musica", help="Archivo de música concreto, o términos a buscar "
                                         "en el banco libre (por defecto: ambiente al azar)")
    parser.add_argument("--musica-local", action="store_true",
                        help="No busca en el banco: usa una pista al azar de musica/")
    parser.add_argument("--sin-musica", action="store_true", help="Sin música de fondo")
    args = parser.parse_args()

    ruta_guion = Path(args.guion_json)
    datos = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion = datos["guion"]

    SALIDA_DIR.mkdir(exist_ok=True)
    TMP_DIR.mkdir(exist_ok=True)

    base_id = ruta_guion.stem
    audio_wav = TMP_DIR / f"{base_id}.wav"
    srt_path = TMP_DIR / f"{base_id}.srt"
    salida_mp4 = SALIDA_DIR / f"{base_id}.mp4"

    texto = construir_texto(guion)
    texto_hablado = aplicar_pronunciaciones(texto)
    print(f"[1/4] Generando audio con Piper ({len(texto)} caracteres)...")
    generar_audio_piper(texto_hablado, args.voz, audio_wav)

    print("[2/4] Generando subtítulos...")
    dur = duracion_audio(audio_wav)
    generar_srt(guion, dur, srt_path)

    print("[3/4] Preparando fondo de B-roll...")
    clips = None
    if not args.sin_broll:
        if args.broll_dir:
            rutas = sorted(
                p for p in Path(args.broll_dir).iterdir()
                if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
            )
        elif os.environ.get("PEXELS_API_KEY"):
            terminos = guion.get("broll") or BROLL_TERMINOS_DEFECTO
            # un clip por corte: si no, en vídeos largos se repiten
            cuantos = max(3, min(math.ceil(dur / SEGUNDOS_POR_CORTE), 15))
            print(f"  Buscando {cuantos} clips en Pexels: {', '.join(terminos)}")
            rutas = descargar_broll_pexels(terminos, os.environ["PEXELS_API_KEY"], max_clips=cuantos)
        else:
            rutas = []
            print("  [aviso] Sin PEXELS_API_KEY ni --broll-dir: se usará el fondo de gradiente.")
        clips = preparar_clips(rutas) or None
        if rutas and not clips:
            print("  [aviso] Ningún clip utilizable: se usará el fondo de gradiente.")

    musica = None
    if not args.sin_musica:
        if args.musica and Path(args.musica).is_file():
            musica = Path(args.musica)
        elif not args.musica_local:
            termino = args.musica  # si no es un archivo, se toma como búsqueda
            print(f"  Buscando música en el banco libre: {termino or 'ambiente al azar'}")
            musica = musica_del_banco(termino)
        if musica is None and MUSICA_DIR.is_dir():
            pistas = sorted(
                p for p in MUSICA_DIR.iterdir()
                if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
            )
            if pistas:
                musica = random.choice(pistas)
        if musica:
            print(f"  Música de fondo: {musica.name}")
            credito = creditos_del_banco().get(musica.name, {}).get("texto")
            if credito:
                print(f"  Atribución obligatoria al publicar: {credito}")
        else:
            print("  [aviso] Sin música: ni el banco ni musica/ dieron ninguna pista.")

    print(f"[4/4] Montando vídeo final con FFmpeg ({'B-roll' if clips else 'gradiente'})...")
    montar_video(audio_wav, srt_path, salida_mp4, dur, clips=clips, musica=musica)

    print(f"[ok] Vídeo generado: {salida_mp4}")


if __name__ == "__main__":
    main()
