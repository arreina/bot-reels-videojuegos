#!/usr/bin/env python3
"""
noticias_reel.py

Módulo 1 del bot de reels: lee RSS de medios de videojuegos, deduplica
noticias ya procesadas y genera un guion de reel (hook/cuerpo/cierre +
hashtags) con la API de Anthropic. Cada guion se guarda en guiones/<id>.json
para que guion_a_video.py lo convierta en vídeo.

Requisitos:
    pip install feedparser anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

Uso:
    python3 noticias_reel.py              # procesa hasta MAX_NOTICIAS nuevas
    python3 noticias_reel.py --max 1      # limita cuántas procesar
    python3 noticias_reel.py --dry-run    # lista noticias nuevas sin llamar a la API
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from anthropic import Anthropic, APIStatusError, APIConnectionError


def cargar_env() -> None:
    """Carga variables desde un .env junto al script o en la raíz del proyecto."""
    for ruta in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
        if not ruta.is_file():
            continue
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env()

# Feeds con su idioma: los que no están en español se traducen para el listado.
# Famitsu queda fuera porque ya no sirve un RSS válido (devuelve HTML).
FEEDS = [
    ("Vandal", "https://vandal.elespanol.com/xml.cgi", "es"),
    ("Eurogamer", "https://www.eurogamer.net/feed", "en"),
    ("PCGamer", "https://www.pcgamer.com/rss/", "en"),
    ("GameSpot", "https://www.gamespot.com/feeds/game-news/", "en"),
    ("Polygon", "https://www.polygon.com/rss/index.xml", "en"),
    ("Kotaku", "https://kotaku.com/rss", "en"),
    ("4Gamer", "https://www.4gamer.net/rss/index.xml", "ja"),
    ("Game*Spark", "https://www.gamespark.jp/rss20/index.rdf", "ja"),
    ("AUTOMATON", "https://automaton-media.com/feed/", "ja"),
    ("Denfaminicogamer", "https://news.denfaminicogamer.jp/feed", "ja"),
]

TRADUCCIONES_PATH = Path("traducciones.json")

MODELO = "claude-sonnet-4-5"
ESTADO_PATH = Path("estado_noticias.json")
GUIONES_DIR = Path("guiones")
MAX_NOTICIAS_DEFECTO = 3

PROMPT_SISTEMA = """Eres guionista de reels cortos (30-45 segundos) sobre noticias de videojuegos, para un canal de ESPAÑA.

REGLA NÚMERO UNO, la más importante de todas: escribe en español de España, jamás en español latinoamericano.
- Trata al público de TÚ o de VOSOTROS. Está PROHIBIDO usar "ustedes", "cuéntenos", "cuéntanos" en forma de ustedes, "hubieran" por "hubierais". Di "contadme", "qué opináis", "¿lo habéis probado?".
- Vocabulario obligatorio de España: "ordenador" (nunca "computadora"), "móvil" (nunca "celular"), "videoconsola" o "consola", "qué versión" (nunca "cuál versión"), "coger" y no "agarrar", "volver" y no "regresar".
- Usa el pretérito perfecto como en España: "ha vuelto", "han anunciado" (no "volvió", "anunciaron") cuando el hecho es reciente.

Otras reglas ESTRICTAS:
- El guion va SIEMPRE en español, aunque la noticia original esté en inglés o en japonés: tradúcela y adáptala, no la copies ni la dejes a medias. Solo se mantienen en su idioma original los nombres propios de juegos, estudios y personajes; si un título japonés tiene nombre oficial en occidente, usa ese.
- Traduce también los términos del sector: en vez de "gameplay" di "jugabilidad", en vez de "release" di "lanzamiento", en vez de "patch" di "parche", en vez de "early access" di "acceso anticipado".
- NUNCA copies frases textuales de la fuente: reescribe todo con tus propias palabras (la fuente tiene copyright).
- No inventes datos que no estén en la noticia. Si un dato no está claro, omítelo.
- Tono: entusiasta pero informativo, como un creador de contenido gamer. Sin clickbait engañoso.
- El texto se leerá en voz alta con TTS: evita siglas raras, símbolos, paréntesis y URLs. Escribe los números como palabras cuando suene más natural.
- hook: 1 frase corta y potente que enganche en los 2 primeros segundos.
- cuerpo: 2-4 frases con lo esencial de la noticia.
- cierre: 1 frase de remate, con una llamada a la acción suave (ej. invitar a opinar en comentarios).
- hashtags: 4-6, mezclando genéricos (#videojuegos #gaming) y específicos del juego/tema, sin espacios.
- broll: 3-5 términos de búsqueda EN INGLÉS para encontrar vídeos de stock genéricos que acompañen la noticia (ej. "video game controller", "esports arena", "game developer office"). Deben ser conceptos genéricos: NUNCA nombres de juegos, personajes ni marcas (ese material tiene copyright y no existe como stock libre).

Responde SOLO con un objeto JSON válido, sin markdown ni texto extra, con esta forma exacta:
{"hook": "...", "cuerpo": "...", "cierre": "...", "hashtags": ["#...", "#..."], "broll": ["...", "..."]}"""


def cargar_estado() -> dict:
    if ESTADO_PATH.exists():
        return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    return {"procesadas": []}


def guardar_estado(estado: dict) -> None:
    ESTADO_PATH.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def id_noticia(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def fecha_entrada(entrada) -> str | None:
    """Fecha de publicación en ISO (UTC), o None si el feed no la trae."""
    for campo in ("published_parsed", "updated_parsed"):
        marca = entrada.get(campo)
        if marca:
            return datetime(*marca[:6], tzinfo=timezone.utc).isoformat()
    return None


def leer_feeds() -> list[dict]:
    """Devuelve las noticias de todos los feeds, en orden de prioridad."""
    noticias = []
    for fuente, url_feed, idioma in FEEDS:
        feed = feedparser.parse(url_feed)
        if feed.bozo and not feed.entries:
            print(f"[aviso] No se pudo leer el feed de {fuente}: {feed.bozo_exception}")
            continue
        for entrada in feed.entries:
            enlace = entrada.get("link", "")
            if not enlace:
                continue
            noticias.append({
                "id": id_noticia(enlace),
                "fuente": fuente,
                "titulo": limpiar_html(entrada.get("title", "")),
                "resumen": limpiar_html(entrada.get("summary", entrada.get("description", ""))),
                "url": enlace,
                "fecha": fecha_entrada(entrada),
                "idioma": idioma,
            })
    # las más recientes primero, sin importar de qué medio vengan
    noticias.sort(key=lambda n: n["fecha"] or "", reverse=True)
    return noticias


def extraer_json(texto: str):
    """Parsea la respuesta del modelo tolerando cercos de código accidentales."""
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    # puede ser un objeto o un array: se queda con el que aparezca antes
    aperturas = [(texto.find(a), a, c) for a, c in (("{", "}"), ("[", "]"))
                 if texto.find(a) != -1]
    if not aperturas:
        raise ValueError(f"La respuesta no contiene JSON: {texto[:200]}")
    inicio, _, cierre = min(aperturas)
    fin = texto.rfind(cierre)
    if fin == -1:
        raise ValueError(f"JSON sin cerrar en la respuesta: {texto[:200]}")
    return json.loads(texto[inicio:fin + 1])


def _pedir_a_claude(peticion: str, timeout: int = 300):
    """Lanza el CLI de Claude Code (usa la suscripción, no la API) y parsea el JSON.

    Requiere haber iniciado sesión una vez con `claude` en esta máquina.
    """
    # Si este script se lanza desde dentro de una sesión de Claude Code,
    # estas variables confunden al CLI anidado: se limpian para la llamada.
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    proceso = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--output-format", "text"],
        input=peticion, capture_output=True, text=True, env=entorno, timeout=timeout,
    )
    if proceso.returncode != 0:
        raise ValueError(f"claude CLI falló: {proceso.stderr.strip()[:300]}")
    return extraer_json(proceso.stdout)


def _validar_guion(guion: dict) -> dict:
    for clave in ("hook", "cuerpo", "cierre", "hashtags"):
        if clave not in guion:
            raise ValueError(f"Guion incompleto, falta '{clave}': {guion}")
    return guion


def _contenido_noticia(noticia: dict) -> str:
    return (
        f"Fuente: {noticia['fuente']}\n"
        f"Titular: {noticia['titulo']}\n"
        f"Resumen: {noticia['resumen']}"
    )


def generar_guion(client: Anthropic, noticia: dict) -> dict:
    respuesta = client.messages.create(
        model=MODELO,
        max_tokens=1024,
        system=PROMPT_SISTEMA,
        messages=[{"role": "user", "content": _contenido_noticia(noticia)}],
    )
    texto = next(b.text for b in respuesta.content if b.type == "text")
    return _validar_guion(extraer_json(texto))


def generar_guion_cli(noticia: dict) -> dict:
    """Genera el guion con el CLI de Claude Code (usa la suscripción, no la API).

    Requiere haber iniciado sesión una vez con `claude` en esta máquina.
    """
    # Si este script se lanza desde dentro de una sesión de Claude Code,
    # estas variables confunden al CLI anidado: se limpian para la llamada.
    # Las instrucciones van en el mensaje de usuario, no solo en el system
    # prompt: al pasar por el CLI, un --append-system-prompt queda diluido
    # entre las instrucciones propias de Claude Code y se ignoran reglas.
    peticion = f"{PROMPT_SISTEMA}\n\n---\n\nNoticia a convertir en guion:\n\n{_contenido_noticia(noticia)}"
    return _validar_guion(_pedir_a_claude(peticion, timeout=180))


# Idiomas que se traducen para el listado. El inglés se deja como está: se
# entiende de un vistazo y traducirlo dispararía el tiempo (unos 5 s por
# titular, y los feeds traen cientos).
IDIOMAS_A_TRADUCIR = {"ja"}

PROMPT_TRADUCCION = """Traduce al español de España estos titulares de noticias de videojuegos.

Reglas:
- Usa el nombre oficial en occidente de juegos, estudios, consolas y personajes; si no existe, deja el original.
- Traduce el resto por completo, con naturalidad periodística, sin calcos del japonés.
- No resumas ni añadas nada: es una traducción, no una reescritura.
- Devuelve exactamente un elemento por cada uno recibido, con el mismo id.

Responde SOLO con un array JSON válido, sin markdown, con esta forma exacta:
[{"id": "...", "titulo": "..."}]"""


def cargar_traducciones() -> dict:
    if TRADUCCIONES_PATH.exists():
        return json.loads(TRADUCCIONES_PATH.read_text(encoding="utf-8"))
    return {}


def guardar_traducciones(traducciones: dict) -> None:
    TRADUCCIONES_PATH.write_text(
        json.dumps(traducciones, ensure_ascii=False, indent=2), encoding="utf-8")


def pendientes_de_traducir(noticias: list[dict], traducciones: dict) -> list[dict]:
    """Noticias en un idioma que se traduce y que aún no están en la caché."""
    return [n for n in noticias
            if n.get("idioma", "es") in IDIOMAS_A_TRADUCIR and n["id"] not in traducciones]


def traducir_noticias(noticias: list[dict], tamano_lote: int = 20,
                      limite: int = 40) -> dict:
    """
    Traduce al español los titulares que aún no estén traducidos.

    Solo traduce hasta 'limite' por tanda: cada titular cuesta unos 5 segundos
    de CLI y los feeds traen cientos, así que no tiene sentido traducir lo que
    nadie va a mirar. Como la lista llega ordenada por fecha, se traducen las
    más recientes y el resto en tandas sucesivas, cacheadas en traducciones.json.
    """
    traducciones = cargar_traducciones()
    pendientes = pendientes_de_traducir(noticias, traducciones)[:limite]
    if not pendientes:
        return traducciones

    for inicio in range(0, len(pendientes), tamano_lote):
        lote = pendientes[inicio:inicio + tamano_lote]
        entrada = json.dumps([{"id": n["id"], "titulo": n["titulo"]} for n in lote],
                             ensure_ascii=False)
        try:
            traducidas = _pedir_a_claude(f"{PROMPT_TRADUCCION}\n\n---\n\n{entrada}")
        except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(f"[aviso] No se pudo traducir un lote: {e}")
            continue
        for item in traducidas:
            if isinstance(item, dict) and item.get("id") and item.get("titulo"):
                traducciones[item["id"]] = item["titulo"]
        guardar_traducciones(traducciones)
        print(f"[info] Traducidos {len(lote)} titulares")
    return traducciones


def titulo_traducido(noticia: dict, traducciones: dict) -> str | None:
    """Título en español de una noticia, si está traducida."""
    valor = traducciones.get(noticia["id"])
    if isinstance(valor, dict):      # formato antiguo, con título y resumen
        return valor.get("titulo") or None
    return valor or None


def main():
    parser = argparse.ArgumentParser(description="Genera guiones de reel desde RSS de videojuegos")
    parser.add_argument("--max", type=int, default=MAX_NOTICIAS_DEFECTO,
                        help="Máximo de noticias nuevas a procesar")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo lista las noticias nuevas, sin llamar a la API")
    args = parser.parse_args()

    estado = cargar_estado()
    procesadas = set(estado["procesadas"])

    noticias = leer_feeds()
    nuevas = [n for n in noticias if n["id"] not in procesadas]
    print(f"[info] {len(noticias)} noticias en los feeds, {len(nuevas)} nuevas")

    if args.dry_run:
        for n in nuevas[:args.max]:
            print(f"  - [{n['fuente']}] {n['titulo']}")
        return

    if not nuevas:
        print("[info] Nada nuevo que procesar.")
        return

    # Backend: API de pago si hay clave; si no, el CLI de Claude Code
    # (incluido en la suscripción de Claude, sin coste extra por llamada).
    if os.environ.get("ANTHROPIC_API_KEY"):
        client = Anthropic()
        usar_cli = False
        print("[info] Usando la API de Anthropic (ANTHROPIC_API_KEY)")
    elif shutil.which("claude"):
        client = None
        usar_cli = True
        print("[info] Sin ANTHROPIC_API_KEY: usando el CLI de Claude Code (suscripción)")
    else:
        print("[error] No hay ANTHROPIC_API_KEY ni CLI de Claude Code. Opciones:\n"
              "  - Crea un .env junto a este script con: ANTHROPIC_API_KEY=sk-ant-...\n"
              "  - O instala Claude Code e inicia sesión: https://claude.com/claude-code")
        raise SystemExit(1)

    GUIONES_DIR.mkdir(exist_ok=True)

    generados = 0
    for noticia in nuevas[:args.max]:
        print(f"[{noticia['id']}] Generando guion: [{noticia['fuente']}] {noticia['titulo']}")
        try:
            if usar_cli:
                guion = generar_guion_cli(noticia)
            else:
                guion = generar_guion(client, noticia)
        except (APIStatusError, APIConnectionError, subprocess.TimeoutExpired) as e:
            print(f"  [error] Fallo de API, se reintentará en la próxima ejecución: {e}")
            continue
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  [error] Respuesta no parseable, se salta: {e}")
            continue

        salida = GUIONES_DIR / f"{noticia['id']}.json"
        salida.write_text(json.dumps({
            "id": noticia["id"],
            "fuente": noticia["fuente"],
            "titulo": noticia["titulo"],
            "url": noticia["url"],
            "generado": datetime.now(timezone.utc).isoformat(),
            "guion": guion,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        procesadas.add(noticia["id"])
        estado["procesadas"] = sorted(procesadas)
        guardar_estado(estado)
        generados += 1
        print(f"  [ok] Guion guardado en {salida}")

    print(f"[fin] {generados} guiones generados.")


if __name__ == "__main__":
    main()
