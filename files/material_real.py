#!/usr/bin/env python3
"""
material_real.py

Busca material REAL para el fondo del reel: trailers y vídeos promocionales del
juego o de la marca de la que habla la noticia, en vez de vídeo de stock
genérico. Si la noticia va de Final Fantasy XVI, el fondo es Final Fantasy XVI.

Escalera de búsqueda (manda la primera que dé resultado):
    1. Canal OFICIAL de la marca en YouTube (PlayStation, Nintendo, Square Enix…)
    2. Ficha del juego en Steam: trailers oficiales, sin clave de API
    3. Medios especializados (IGN, GameSpot…), que replican los mismos trailers
    4. Nada, y quien llama cae al stock libre de siempre (Pexels/Pixabay)

OJO CON EL COPYRIGHT: todo lo que sale de aquí es material del editor, no es
libre como el stock. Se usa como lo usan los medios: cortes de pocos segundos,
la voz por encima y el crédito sobreimpreso ("Imágenes: PlayStation"), que pone
guion_a_video.py leyendo `creditos_guardados()`.
"""

import json
import os
import random
import re
import shutil
import subprocess
import threading
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CACHE = Path("broll_cache")          # se comparte con el stock
CREDITOS_PATH = CACHE / "creditos_material.json"


def _localizar(nombre: str, ruta_local: str) -> str:
    """Igual que en guion_a_video.py, repetido aquí para no acoplar los módulos."""
    candidato = RAIZ_PROYECTO / ruta_local
    if candidato.is_file():
        return str(candidato)
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    raise FileNotFoundError(f"No se encontró '{nombre}' ni en {ruta_local} ni en el PATH")


FFMPEG = _localizar("ffmpeg", "bin/ffmpeg")
FFPROBE = _localizar("ffprobe", "bin/ffprobe")

SEGUNDOS_POR_CORTE = 4.0   # mismo corte que usa el fondo de stock
# Los extremos de un trailer no son el juego: al principio va la calificación
# por edades (ese PEGI 18 sobre negro) y el logo de la marca, y al final la
# fecha de salida, la carátula y el "PLAY HAS NO LIMITS" de turno. Se tira
# ancho: un trailer dura minuto y medio largo y sobra material.
CABECERA_A_SALTAR = 8.0
COLA_A_SALTAR = 12.0

# Solo se le pasan a yt-dlp enlaces de estos dominios. El buscador de la
# interfaz recibe el enlace desde el navegador y yt-dlp entiende cientos de
# webs: sin esta lista, cualquiera con acceso a la interfaz podría hacer que el
# PC descargue de donde quisiera.
DOMINIOS_PERMITIDOS = (
    "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be",
    "video.akamai.steamstatic.com", "cdn.akamai.steamstatic.com",
)

# Canal oficial -> nombre que se muestra en el crédito. La clave se busca como
# subcadena del nombre del canal ya normalizado (sin tildes y en minúsculas).
CANALES_OFICIALES = {
    "playstation": "PlayStation",
    "xbox": "Xbox",
    "nintendo": "Nintendo",
    "square enix": "Square Enix",
    "ubisoft": "Ubisoft",
    "bandai namco": "Bandai Namco",
    "capcom": "Capcom",
    "sega": "SEGA",
    "konami": "Konami",
    "bethesda": "Bethesda",
    "ea ": "Electronic Arts",
    "electronic arts": "Electronic Arts",
    "activision": "Activision",
    "blizzard": "Blizzard",
    "rockstar games": "Rockstar Games",
    "cd projekt": "CD PROJEKT RED",
    "riot games": "Riot Games",
    "epic games": "Epic Games",
    "devolver": "Devolver Digital",
    "annapurna": "Annapurna Interactive",
    "team17": "Team17",
    "focus entertainment": "Focus Entertainment",
    "505 games": "505 Games",
    "kojima productions": "Kojima Productions",
    "fromsoftware": "FromSoftware",
    "atlus": "ATLUS",
    "koei tecmo": "Koei Tecmo",
    "larian": "Larian Studios",
    "paradox": "Paradox Interactive",
    "nacon": "NACON",
    "thq nordic": "THQ Nordic",
    "warner bros. games": "Warner Bros. Games",
    "netflix games": "Netflix Games",
    "valve": "Valve",
}

# Medios: replican los mismos trailers, pero con su marca de agua encima.
CANALES_MEDIOS = {
    "ign": "IGN",
    "gamespot": "GameSpot",
    "eurogamer": "Eurogamer",
    "gamesradar": "GamesRadar",
    "pc gamer": "PC Gamer",
    "game informer": "Game Informer",
    "gametrailers": "GameTrailers",
    "vandal": "Vandal",
    "3djuegos": "3DJuegos",
    "meristation": "MeriStation",
    "areajugones": "Areajugones",
    "polygon": "Polygon",
    "kotaku": "Kotaku",
    "vgc": "VGC",
    "push square": "Push Square",
    "nintendo life": "Nintendo Life",
    "4gamer": "4Gamer",
    "famitsu": "Famitsu",
}

# Un vídeo solo vale si el título habla de material mostrable. Así se descartan
# análisis, podcasts y vídeos de opinión, que son gente hablando a cámara.
PALABRAS_UTILES = (
    "trailer", "tráiler", "trailer oficial", "gameplay", "teaser", "reveal",
    "announcement", "anuncio", "launch", "lanzamiento", "showcase", "demo",
    "state of play", "direct", "cinematic", "opening", "presentación",
    "первый", "プレイ", "トレーラー", "official",
)

# Y estas lo tumban aunque tenga las de arriba.
PALABRAS_VETADAS = (
    "reaction", "reacciona", "review", "análisis", "analisis", "podcast",
    "tier list", "ranking", "top 10", "explained", "explicado", "teoría",
    "theory", "speedrun", "walkthrough completo", "full game", "100%",
    "todos los trailers", "all trailers", "compilation", "recopilación",
)

DURACION_MINIMA = 20.0    # menos que eso no da ni para tres cortes
DURACION_MAXIMA = 900.0   # los directos de dos horas no valen

# Steam llega a publicar como "vídeo" la propia tarjeta de calificación por
# edades: la ficha de Final Fantasy XVI tiene uno que se llama "PEGI EN" y es
# eso y nada más.
PALABRAS_DE_AVISO = ("pegi", "esrb", "usk", "cero", "classification",
                     "age rating", "rating", "aviso legal")


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres de canal con holgura."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def clasificar_canal(canal: str, empresa: str = "") -> tuple[str, str]:
    """
    Decide si un canal es oficial, un medio o un desconocido.

    Devuelve (nivel, nombre_para_el_credito) con nivel en
    "oficial" / "medio" / "desconocido". Además de la lista fija, se considera
    oficial el canal que lleve el nombre de la empresa de la noticia: hay miles
    de estudios y no caben todos en una constante.
    """
    normal = _normalizar(canal)
    if not normal:
        return "desconocido", canal

    empresa_normal = _normalizar(empresa)
    if empresa_normal and len(empresa_normal) >= 4 and empresa_normal in normal:
        return "oficial", canal

    for clave, nombre in CANALES_OFICIALES.items():
        if clave in normal:
            return "oficial", nombre
    for clave, nombre in CANALES_MEDIOS.items():
        if re.search(rf"\b{re.escape(clave)}\b", normal):
            return "medio", nombre
    return "desconocido", canal


def _es_tarjeta_de_aviso(nombre: str) -> bool:
    normal = _normalizar(nombre)
    return any(aviso in normal for aviso in PALABRAS_DE_AVISO)


def _titulo_util(titulo: str) -> bool:
    normal = _normalizar(titulo)
    if any(veto in normal for veto in PALABRAS_VETADAS):
        return False
    return any(palabra in normal for palabra in PALABRAS_UTILES)


def _yt_dlp():
    """Importa yt-dlp solo cuando hace falta, para no penalizar el arranque."""
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover - depende de la instalación
        raise RuntimeError(
            "Falta yt-dlp. Instálalo en el entorno del proyecto:\n"
            "    .venv/bin/pip install -U yt-dlp"
        ) from e
    return yt_dlp


def buscar_en_youtube(consulta: str, empresa: str = "", limite: int = 12) -> list[dict]:
    """
    Busca en YouTube y devuelve candidatos ya filtrados y clasificados, SIN
    descargar nada (solo los metadatos de la búsqueda, que es una petición).
    """
    yt_dlp = _yt_dlp()
    opciones = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "extract_flat": True, "skip_download": True, "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(f"ytsearch{limite}:{consulta}", download=False)
    except Exception as e:  # yt-dlp lanza de todo: red, extractor roto, etc.
        print(f"  [aviso] YouTube falló para '{consulta}': {e}")
        return []

    candidatos = []
    for entrada in (info or {}).get("entries", []) or []:
        if not entrada or not entrada.get("id"):
            continue
        duracion = entrada.get("duration") or 0
        if not (DURACION_MINIMA <= duracion <= DURACION_MAXIMA):
            continue
        titulo = entrada.get("title") or ""
        if not _titulo_util(titulo):
            continue
        canal = entrada.get("channel") or entrada.get("uploader") or ""
        nivel, credito = clasificar_canal(canal, empresa)
        if nivel == "desconocido":
            continue  # sin saber de quién es, ni se usa ni se puede acreditar
        candidatos.append({
            "id": f"yt_{entrada['id']}",
            "enlace": f"https://www.youtube.com/watch?v={entrada['id']}",
            "imagen": f"https://i.ytimg.com/vi/{entrada['id']}/hqdefault.jpg",
            "termino": consulta,
            "autor": canal,
            "fuente": f"YouTube · {credito}",
            "vertical": False,      # los trailers son apaisados; se recortan
            "tipo": "real",
            "nivel": nivel,
            "credito": credito,
            "titulo": titulo,
            "duracion": float(duracion),
        })
    return candidatos


def buscar_en_steam(juego: str, limite: int = 4) -> list[dict]:
    """
    Trailers oficiales de la ficha del juego en Steam. No necesita clave de API.
    Steam ya no sirve mp4 directo en las fichas nuevas, solo HLS, pero yt-dlp
    se lo traga igual (nuestro ffmpeg estático NO: se rompe con esos m3u8).
    """
    if not juego:
        return []
    try:
        r = requests.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": juego, "l": "spanish", "cc": "ES"}, timeout=20,
        )
        r.raise_for_status()
        articulos = r.json().get("items", [])
    except (requests.RequestException, ValueError) as e:
        print(f"  [aviso] La búsqueda en Steam falló para '{juego}': {e}")
        return []
    if not articulos:
        return []

    # El primer resultado es el juego en sí; los siguientes suelen ser DLC.
    appid = articulos[0]["id"]
    try:
        r = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english"}, timeout=20,
        )
        r.raise_for_status()
        ficha = (r.json().get(str(appid)) or {}).get("data") or {}
    except (requests.RequestException, ValueError) as e:
        print(f"  [aviso] La ficha de Steam {appid} falló: {e}")
        return []

    editores = ficha.get("publishers") or ficha.get("developers") or []
    credito = editores[0] if editores else "Steam"
    candidatos = []
    for video in (ficha.get("movies") or [])[:limite]:
        # mp4 en las fichas antiguas, HLS en las nuevas
        enlace = (video.get("mp4") or {}).get("max") or video.get("hls_h264") or ""
        if not enlace or _es_tarjeta_de_aviso(video.get("name", "")):
            continue
        candidatos.append({
            "id": f"steam_{video['id']}",
            "enlace": enlace.replace("http://", "https://"),
            "imagen": video.get("thumbnail", ""),
            "termino": juego,
            "autor": credito,
            "fuente": f"Steam · {credito}",
            "vertical": False,
            "tipo": "real",
            "nivel": "oficial",
            "credito": credito,
            "titulo": f"{ficha.get('name', juego)} — {video.get('name', 'trailer')}",
            "duracion": 0.0,  # Steam no lo dice; se sabe al descargarlo
        })
    return candidatos


def buscar_material(material: dict, limite_por_busqueda: int = 12) -> list[dict]:
    """
    Recorre la escalera entera y devuelve el banco de candidatos ORDENADO:
    primero lo oficial, después Steam, después los medios.

    `material` es el bloque que escribe el guionista:
        {"juego": "Final Fantasy XVI", "empresa": "Square Enix",
         "busquedas": ["Final Fantasy XVI trailer", "Final Fantasy XVI gameplay"]}
    """
    juego = (material.get("juego") or "").strip()
    empresa = (material.get("empresa") or "").strip()
    busquedas = [b for b in (material.get("busquedas") or []) if b and b.strip()]
    if not busquedas and juego:
        busquedas = [f"{juego} trailer"]

    oficiales, medios, vistos = [], [], set()
    for consulta in busquedas:
        for candidato in buscar_en_youtube(consulta, empresa, limite_por_busqueda):
            if candidato["id"] in vistos:
                continue
            vistos.add(candidato["id"])
            (oficiales if candidato["nivel"] == "oficial" else medios).append(candidato)

    desde_steam = []
    if juego:
        desde_steam = [c for c in buscar_en_steam(juego) if c["id"] not in vistos]

    return oficiales + desde_steam + medios


# ---------------------------------------------------------------------------
# Descarga y troceado
# ---------------------------------------------------------------------------

def _ruta_descarga(candidato: dict) -> Path:
    return CACHE / f"fuente_{candidato['id']}"


def luminancia(ruta: Path, momento: float) -> float:
    """
    Brillo medio (0-255) de un fotograma suelto. Sirve para no cortar justo en
    un fundido a negro, que en los trailers hay muchos y dejan 4 segundos de
    pantalla vacía en el reel.
    """
    proceso = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{momento:.3f}", "-t", "0.1", "-i", str(ruta),
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    valores = re.findall(r"YAVG=([\d.]+)", proceso.stdout)
    return float(valores[0]) if valores else 255.0  # si no se puede medir, que pase


def duracion(ruta: Path) -> float:
    salida = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
        capture_output=True, text=True,
    )
    try:
        return float(salida.stdout.strip())
    except ValueError:
        return 0.0


def descargar(candidato: dict) -> Path | None:
    """
    Baja el vídeo entero (solo la pista de imagen: el audio del trailer no se
    usa, debajo va la locución) a la caché. Si ya está, lo reutiliza.
    """
    enlace = candidato.get("enlace", "")
    if urlparse(enlace).hostname not in DOMINIOS_PERMITIDOS:
        print(f"  [aviso] Enlace de material no permitido: {enlace[:70]}")
        return None

    CACHE.mkdir(exist_ok=True)
    base = _ruta_descarga(candidato)
    for existente in CACHE.glob(f"{base.name}.*"):
        if existente.stat().st_size > 0:
            return existente

    yt_dlp = _yt_dlp()
    opciones = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "socket_timeout": 30, "retries": 2,
        # Solo imagen y como mucho 1080p: es el fondo de un vertical, no hace
        # falta más. Se prefiere H.264 porque decodifica más rápido que AV1.
        "format": ("bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/"
                   "b[height<=1080]/bv*/b"),
        "outtmpl": f"{base}.%(ext)s",
        # yt-dlp entiende cientos de webs; aquí solo se quieren estas dos.
        "allowed_extractors": ["youtube", "generic"],
    }
    # Los trailers de juegos para adultos están tras la verificación de edad de
    # YouTube y sin sesión no se pueden bajar (se salta al siguiente candidato,
    # que es lo normal). Con YT_COOKIES_NAVEGADOR=chrome en .env se usan las
    # cookies del navegador y también entran esos.
    navegador = os.environ.get("YT_COOKIES_NAVEGADOR", "").strip()
    if navegador:
        opciones["cookiesfrombrowser"] = (navegador,)
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            ydl.download([enlace])
    except Exception as e:
        print(f"  [aviso] No se pudo descargar {candidato.get('titulo', enlace)[:60]}: {e}")
        for resto in CACHE.glob(f"{base.name}.*"):
            resto.unlink(missing_ok=True)
        return None

    descargados = [p for p in CACHE.glob(f"{base.name}.*") if p.stat().st_size > 0]
    return descargados[0] if descargados else None


# Umbrales medidos sobre un trailer lleno de tarjetas (Final Fantasy XVI):
# los cortes con tarjeta dan un 26% de fotogramas por debajo de 25 de brillo y
# además salen congelados; los cortes buenos se quedan en un 0-6% y ninguno
# congela. OJO: la tarjeta de texto sobre negro NO es negro puro, marca 19 de
# brillo, así que un umbral de 18 la dejaba pasar por los pelos.
LUMINANCIA_MINIMA = 25.0
FRACCION_OSCURA_MAXIMA = 0.15
UMBRAL_CONGELADO = 0.01    # sensibilidad de freezedetect (ruido por debajo)


def analizar_tramo(fuente: Path, inicio: float, segundos: float) -> tuple[float, bool]:
    """
    Mira el corte ENTERO de una pasada y devuelve (fracción de fotogramas
    oscuros, si hay imagen congelada).

    Hay que mirarlo entero y no un fotograma suelto: las tarjetas que se
    cuelan (el PEGI sobre negro, el logo del estudio, "FOR LONG ENOUGH", la
    fecha de salida) ocupan el principio o el final del corte, así que
    midiendo solo el centro pasan desapercibidas. Medido sobre un trailer con
    tarjetas: los cortes con tarjeta dan 7-28% de fotogramas oscuros y los
    buenos, 0%.
    """
    proceso = subprocess.run(
        [FFMPEG, "-v", "info", "-ss", f"{inicio:.3f}", "-t", f"{segundos:.3f}",
         "-i", str(fuente),
         # a 192 px de ancho sobra para esto y va mucho más rápido.
         # freezedetect caza además la tarjeta fija que no sea oscura.
         "-vf", (f"scale=192:-2,freezedetect=n={UMBRAL_CONGELADO}:d={segundos / 5:.2f},"
                 "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"),
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    brillos = [float(v) for v in re.findall(r"YAVG=([\d.]+)", proceso.stdout)]
    if not brillos:
        return 0.0, False  # si no se puede medir, que pase
    oscuros = sum(1 for b in brillos if b < LUMINANCIA_MINIMA) / len(brillos)
    return oscuros, "freeze_start" in proceso.stderr


def tramo_aprovechable(fuente: Path, inicio: float, segundos: float) -> bool:
    """¿Este corte es juego de verdad, y no una tarjeta ni un fundido a negro?"""
    oscuros, congelado = analizar_tramo(fuente, inicio, segundos)
    return oscuros <= FRACCION_OSCURA_MAXIMA and not congelado


def _buscar_momento(fuente: Path, ideal: float, margen: float,
                    segundos: float) -> float | None:
    """
    Corrige el punto de corte para que no caiga en una tarjeta ni en un
    fundido. Prueba el sitio ideal y, si no vale, se desplaza dentro del hueco
    que le toca a ese corte. Devuelve None si no hay nada aprovechable.
    """
    saltos = [0.0, margen * 0.25, margen * 0.5, -margen * 0.25]
    for salto in saltos:
        momento = max(ideal + salto, 0.0)
        if tramo_aprovechable(fuente, momento, segundos):
            return momento
    return None


def ruta_de_corte(corte_id: str) -> Path:
    """Misma convención que gv.ruta_de_clip, para que el plan no note la diferencia."""
    return CACHE / f"clip_{corte_id}.mp4"


def _candidato_corte(trailer: dict, inicio: float, segundos: float) -> dict:
    """
    Un corte concreto de un trailer, con la misma forma que un candidato de
    stock para que el plan, el selector y el remontaje lo traten igual. Lleva
    además de dónde sale (`enlace` + `inicio`), que es lo que permite volver a
    generarlo si se vacía la caché.

    OJO con el id: lleva el MOMENTO en centésimas, no el número de corte. Con
    el número, al afinar los filtros de tarjetas el archivo cacheado del corte
    nº 3 se reutilizaba aunque ahora el corte nº 3 saliera de otro segundo del
    trailer, y las mejoras no se veían nunca. Con el momento, cambiar de
    segundo cambia de archivo.
    """
    return {
        "id": f"{trailer['id']}_{int(round(inicio * 100))}",
        "enlace": trailer["enlace"],
        "imagen": trailer.get("imagen", ""),
        "termino": trailer.get("termino", ""),
        "autor": trailer.get("autor", ""),
        "fuente": trailer.get("fuente", ""),
        "vertical": False,
        "tipo": "real",
        "credito": trailer.get("credito", ""),
        "titulo": trailer.get("titulo", ""),
        "inicio": round(inicio, 3),
        "segundos": segundos,
    }


def _cortar(fuente: Path, destino: Path, inicio: float, segundos: float) -> bool:
    if destino.is_file() and destino.stat().st_size > 0:
        return True
    proceso = subprocess.run(
        [FFMPEG, "-y", "-v", "error",
         "-ss", f"{inicio:.3f}", "-t", f"{segundos:.3f}", "-i", str(fuente),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", str(destino)],
        capture_output=True, text=True,
    )
    if proceso.returncode != 0 or not destino.is_file():
        print(f"  [aviso] No se pudo cortar en {inicio:.1f}s: {proceso.stderr[:200]}")
        destino.unlink(missing_ok=True)
        return False
    return True


def trocear(fuente: Path, cuantos: int, trailer: dict,
            segundos: float = SEGUNDOS_POR_CORTE) -> list[dict]:
    """
    Parte un trailer largo en varios cortes repartidos a lo largo del vídeo,
    saltándose los logos del principio y la pantalla final.

    Devuelve menos de `cuantos` si el trailer no da para más sin repetirse: el
    que llama completa con otro trailer o con stock.
    """
    total = duracion(fuente)
    if total <= 0:
        return []
    inicio = min(CABECERA_A_SALTAR, total * 0.05)
    fin = max(total - COLA_A_SALTAR, inicio + segundos)
    util = max(fin - inicio, 0.0)
    caben = int(util // segundos)
    if caben < 1:
        return []
    cuantos = min(cuantos, caben)

    # repartidos por todo el trailer, no los primeros N seguidos
    paso = util / cuantos
    CACHE.mkdir(exist_ok=True)
    cortes = []
    for i in range(cuantos):
        desde = _buscar_momento(fuente, inicio + paso * i, paso, segundos)
        if desde is None:
            continue  # ese tramo del trailer es todo fundidos: se salta
        corte = _candidato_corte(trailer, desde, segundos)
        if not _cortar(fuente, ruta_de_corte(corte["id"]), desde, segundos):
            continue
        registrar_credito(ruta_de_corte(corte["id"]), corte)
        cortes.append(corte)
    return cortes


_descargas_en_curso: dict[str, threading.Lock] = {}
_cerrojo_general = threading.Lock()


def _cerrojo_de(clave: str) -> threading.Lock:
    """Un candado por trailer: el plan materializa varios cortes en paralelo y
    todos querrían bajar el mismo archivo a la vez."""
    with _cerrojo_general:
        return _descargas_en_curso.setdefault(clave, threading.Lock())


def materializar(corte: dict) -> Path | None:
    """
    Deja en la caché el archivo de un corte: baja el trailer de origen si hace
    falta y recorta el trozo. Es lo que llama guion_a_video.descargar_candidato
    cuando el candidato es material real.
    """
    destino = ruta_de_corte(corte["id"])
    if destino.is_file() and destino.stat().st_size > 0:
        return destino

    # el id de un corte es "<id del trailer>_<n>"
    id_trailer = corte["id"].rsplit("_", 1)[0]
    with _cerrojo_de(id_trailer):
        if destino.is_file() and destino.stat().st_size > 0:
            return destino  # lo ha dejado otro hilo mientras esperábamos
        fuente = descargar({"id": id_trailer, "enlace": corte["enlace"],
                            "titulo": corte.get("titulo", "")})
        if not fuente:
            return None
        inicio = float(corte.get("inicio", 0.0))
        segundos = float(corte.get("segundos", SEGUNDOS_POR_CORTE))
        if not _cortar(fuente, destino, inicio, segundos):
            return None
    registrar_credito(destino, corte)
    return destino


def corte_suelto(trailer: dict, evitar: list[float] | None = None,
                 segundos: float = SEGUNDOS_POR_CORTE) -> dict | None:
    """
    Un único corte de un trailer, para cuando se elige a mano desde el móvil.
    Cada vez devuelve un momento distinto, así que volver a tocar el mismo
    trailer da otro trozo en vez de repetir el mismo.
    """
    fuente = descargar(trailer)
    if not fuente:
        return None
    total = duracion(fuente)
    if total <= 0:
        return None
    inicio = min(CABECERA_A_SALTAR, total * 0.05)
    fin = max(total - COLA_A_SALTAR, inicio + segundos)
    caben = max(int((fin - inicio) // segundos), 1)
    evitar = evitar or []

    indices = list(range(caben))
    random.shuffle(indices)
    for i in indices:
        desde = inicio + i * segundos
        if any(abs(desde - y) < segundos for y in evitar):
            continue
        if not tramo_aprovechable(fuente, desde, segundos):
            continue
        corte = _candidato_corte(trailer, desde, segundos)
        if _cortar(fuente, ruta_de_corte(corte["id"]), desde, segundos):
            registrar_credito(ruta_de_corte(corte["id"]), corte)
            return corte
    return None


# ---------------------------------------------------------------------------
# Créditos: qué clip es de quién
# ---------------------------------------------------------------------------

def creditos_guardados() -> dict:
    """{nombre_de_archivo: {credito, fuente, titulo, enlace}} de lo descargado."""
    if CREDITOS_PATH.is_file():
        try:
            return json.loads(CREDITOS_PATH.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def registrar_credito(clip: Path, candidato: dict) -> None:
    """Anota de quién es este corte para poder sobreimprimir el crédito luego."""
    creditos = creditos_guardados()
    creditos[clip.name] = {
        "credito": candidato.get("credito", ""),
        "fuente": candidato.get("fuente", ""),
        "titulo": candidato.get("titulo", ""),
        "enlace": candidato.get("enlace", ""),
    }
    CREDITOS_PATH.parent.mkdir(exist_ok=True)
    CREDITOS_PATH.write_text(
        json.dumps(creditos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def credito_de(clip: Path | str) -> str:
    """Nombre que hay que sobreimprimir mientras se ve este clip ('' si es stock)."""
    nombre = Path(clip).name
    return (creditos_guardados().get(nombre) or {}).get("credito", "")


def conseguir_clips(material: dict, cuantos: int,
                    segundos: float = SEGUNDOS_POR_CORTE) -> list[dict]:
    """
    De la noticia a los cortes listos para el fondo: busca, descarga los
    trailers que hagan falta y los trocea hasta reunir `cuantos` cortes.

    Devuelve candidatos con la misma forma que los de stock, así que el plan
    del vídeo y el selector del móvil los tratan igual.
    """
    trailers = buscar_material(material)
    if not trailers:
        return []

    cortes: list[dict] = []
    for trailer in trailers:
        if len(cortes) >= cuantos:
            break
        fuente = descargar(trailer)
        if not fuente:
            continue
        nuevos = trocear(fuente, cuantos - len(cortes), trailer, segundos)
        cortes += nuevos
        if nuevos:
            print(f"  · {len(nuevos)} cortes de «{trailer['titulo'][:55]}» "
                  f"({trailer['fuente']})")
    return cortes
