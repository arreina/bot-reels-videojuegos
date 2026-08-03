#!/usr/bin/env python3
"""
servidor.py

Interfaz web del bot de reels, pensada para usar desde el móvil.
Envuelve los dos módulos existentes sin modificarlos:
    noticias_reel.py  -> leer feeds y generar el guion con Claude
    guion_a_video.py  -> voz, subtítulos, B-roll, música y montaje

El PC hace todo el trabajo pesado; el móvil solo pinta la interfaz.

Uso (desde la carpeta files/):
    ../.venv/bin/python3 servidor.py

Luego, desde el móvil en la misma red WiFi, abre la dirección que imprime
al arrancar (ej. http://192.168.1.40:8000) y añádela a la pantalla de inicio.
"""

import json
import math
import os
import random
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import guion_a_video as gv
import noticias_reel as nr

PUERTO = 8000        # http: siempre disponible, para ver y descargar
PUERTO_SEGURO = 8443  # https: necesario para compartir a Instagram desde el móvil
WEB_DIR = Path(__file__).parent / "web"
# Si existe el certificado (lo crea crear_certificado.sh) se sirve por HTTPS.
# Hace falta para que Android permita compartir el vídeo a Instagram o WhatsApp:
# el menú de compartir del navegador solo funciona en conexiones seguras.
CERT_DIR = Path(__file__).resolve().parent.parent / "certificado"
CACHE_FEEDS_SEGUNDOS = 600  # relee los RSS como mucho cada 10 minutos

app = FastAPI(title="Bot de reels")

# Estado en memoria: caché de feeds y trabajos de generación en curso
_cache = {"noticias": [], "momento": 0.0}
_trabajos: dict[str, dict] = {}
_lock = threading.Lock()


class GuionEditado(BaseModel):
    """Guion tal y como queda tras editarlo en el móvil."""
    id: str
    titulo: str = ""
    fuente: str = ""
    url: str = ""
    hook: str
    cuerpo: str
    cierre: str
    hashtags: list[str] = []
    broll: list[str] = []
    musica: str | None = None          # nombre del archivo, o None para aleatoria
    volumen_musica: float = gv.MUSICA_VOLUMEN


def _ip_local() -> str:
    """IP de este PC en la red local (para mostrar la URL del móvil)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@app.get("/")
def raiz():
    return FileResponse(WEB_DIR / "index.html")


_traduciendo = threading.Event()


def _lanzar_traduccion(noticias: list[dict]) -> None:
    """Traduce en segundo plano, sin dejar que se solapen dos tandas."""
    if _traduciendo.is_set():
        return

    def tarea():
        _traduciendo.set()
        try:
            nr.traducir_noticias(noticias)
        except Exception:
            traceback.print_exc()
        finally:
            _traduciendo.clear()

    threading.Thread(target=tarea, daemon=True).start()


@app.get("/api/noticias")
def listar_noticias(refrescar: bool = False):
    """Noticias de los feeds, marcando cuáles ya se procesaron."""
    with _lock:
        caducada = time.time() - _cache["momento"] > CACHE_FEEDS_SEGUNDOS
        if refrescar or caducada or not _cache["noticias"]:
            _cache["noticias"] = nr.leer_feeds()
            _cache["momento"] = time.time()
        noticias = _cache["noticias"]

    procesadas = set(nr.cargar_estado()["procesadas"])
    con_guion = {p.stem for p in nr.GUIONES_DIR.glob("*.json")} if nr.GUIONES_DIR.is_dir() else set()
    con_video = {p.stem for p in gv.SALIDA_DIR.glob("*.mp4")} if gv.SALIDA_DIR.is_dir() else set()

    # Las noticias japonesas o inglesas se muestran traducidas; la traducción
    # tarda, así que va en segundo plano y el listado se rellena al recargar.
    traducciones = nr.cargar_traducciones()
    pendientes = nr.pendientes_de_traducir(noticias, traducciones)
    if pendientes:
        _lanzar_traduccion(noticias)

    salida = []
    for n in noticias:
        titulo_es = nr.titulo_traducido(n, traducciones)
        # el resumen japonés no se traduce (sale caro): mejor no enseñarlo
        resumen = "" if n.get("idioma") in nr.IDIOMAS_A_TRADUCIR else n["resumen"]
        salida.append({
            **n,
            "titulo": titulo_es or n["titulo"],
            "resumen": resumen,
            "traducida": bool(titulo_es),
            "procesada": n["id"] in procesadas,
            "tiene_guion": n["id"] in con_guion,
            "tiene_video": n["id"] in con_video,
        })
    return {"noticias": salida, "traduciendo": len(pendientes)}


@app.post("/api/guion/{noticia_id}")
def crear_guion(noticia_id: str):
    """Genera el guion de una noticia con Claude (o devuelve el ya guardado)."""
    guardado = nr.GUIONES_DIR / f"{noticia_id}.json"
    if guardado.is_file():
        return json.loads(guardado.read_text(encoding="utf-8"))

    with _lock:
        noticia = next((n for n in _cache["noticias"] if n["id"] == noticia_id), None)
        if noticia is None:
            # la caché puede estar vacía si el servidor acaba de arrancar
            _cache["noticias"] = nr.leer_feeds()
            _cache["momento"] = time.time()
            noticia = next((n for n in _cache["noticias"] if n["id"] == noticia_id), None)
    if noticia is None:
        raise HTTPException(404, "Esa noticia ya no está en los feeds; refresca la lista")

    try:
        guion = nr.generar_guion_cli(noticia)
    except Exception as e:
        raise HTTPException(502, f"No se pudo generar el guion: {e}")

    datos = {
        "id": noticia["id"],
        "fuente": noticia["fuente"],
        "titulo": noticia["titulo"],
        "url": noticia["url"],
        "generado": datetime.now(timezone.utc).isoformat(),
        "guion": guion,
    }
    nr.GUIONES_DIR.mkdir(exist_ok=True)
    guardado.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos


CLIPS_MINIMOS = 3
CLIPS_MAXIMOS = 15  # tope para no descargar cientos de megas en vídeos largos


def _clips_necesarios(duracion: float) -> int:
    """Un clip distinto por corte, para que no se repitan en vídeos largos."""
    cortes = math.ceil(duracion / gv.SEGUNDOS_POR_CORTE)
    return max(CLIPS_MINIMOS, min(cortes, CLIPS_MAXIMOS))


def _descargar_varios(candidatos: list[dict], cuantos: int) -> list[dict]:
    """Descarga en paralelo hasta reunir 'cuantos' clips, respetando el orden."""
    elegidos, pendientes = [], list(candidatos)
    while pendientes and len(elegidos) < cuantos:
        lote = pendientes[:cuantos - len(elegidos)]
        pendientes = pendientes[len(lote):]
        with ThreadPoolExecutor(max_workers=4) as ejecutor:
            resultados = list(ejecutor.map(gv.descargar_candidato, lote))
        elegidos += [c for c, ruta in zip(lote, resultados) if ruta]
    return elegidos


def _plan_path(base_id: str) -> Path:
    """Archivo con los clips de fondo elegidos para una noticia."""
    return gv.TMP_DIR / f"{base_id}_clips.json"


def _cargar_plan(base_id: str) -> dict:
    ruta = _plan_path(base_id)
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def _guardar_plan(base_id: str, plan: dict) -> None:
    gv.TMP_DIR.mkdir(exist_ok=True)
    _plan_path(base_id).write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def _rutas_de_plan(plan: dict) -> list[Path]:
    return [gv.ruta_de_clip(i) for i in plan.get("usados", [])]


def _repartir_por_termino(candidatos: list[dict]) -> list[dict]:
    """Alterna candidatos de cada búsqueda para que el fondo no sea monotemático."""
    por_termino: dict[str, list[dict]] = {}
    for c in candidatos:
        por_termino.setdefault(c["termino"], []).append(c)
    mezclados, listas = [], list(por_termino.values())
    for i in range(max(len(l) for l in listas)) if listas else []:
        for lista in listas:
            if i < len(lista):
                mezclados.append(lista[i])
    return mezclados


MUSICA_EXTENSIONES = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def _pistas_musica() -> list[Path]:
    """Todo lo que hay a mano: pistas propias y lo ya bajado del banco libre."""
    pistas = []
    for carpeta in (gv.MUSICA_DIR, gv.MUSICA_CACHE):
        if carpeta.is_dir():
            pistas += sorted(p for p in carpeta.iterdir()
                             if p.suffix.lower() in MUSICA_EXTENSIONES)
    return pistas


def _ruta_musica(nombre: str) -> Path | None:
    """Busca una pista por nombre de archivo en las dos carpetas."""
    nombre = Path(nombre).name
    for carpeta in (gv.MUSICA_DIR, gv.MUSICA_CACHE):
        ruta = carpeta / nombre
        if ruta.is_file():
            return ruta
    return None


def _elegir_musica(nombre: str | None = None) -> Path | None:
    """La pista pedida por su nombre; si no se dice cuál, una nueva del banco."""
    if nombre:
        elegida = _ruta_musica(nombre)
        if elegida:
            return elegida
    del_banco = gv.musica_del_banco()
    if del_banco:
        return del_banco
    # sin red o sin resultados, se tira de lo que ya haya descargado
    pistas = _pistas_musica()
    return random.choice(pistas) if pistas else None


def _creditos_musica() -> dict:
    """Atribución exigida por la licencia de cada pista, si está registrada."""
    creditos = {}
    for ruta in (gv.MUSICA_DIR / "creditos.json", gv.MUSICA_CACHE / "creditos.json"):
        if ruta.is_file():
            creditos.update(json.loads(ruta.read_text(encoding="utf-8")))
    return creditos


@app.get("/api/musica")
def listar_musica():
    """Pistas ya descargadas, para el selector del móvil."""
    creditos = _creditos_musica()
    return [{"nombre": p.name, "url": f"/musica/{p.name}",
             "titulo": creditos.get(p.name, {}).get("titulo") or p.stem.replace("pista_", ""),
             "credito": creditos.get(p.name, {}).get("texto")}
            for p in _pistas_musica()]


@app.get("/api/buscar_musica")
def buscar_musica(q: str):
    """Busca canciones en los bancos libres. No descarga: solo enseña opciones."""
    if not q.strip():
        raise HTTPException(400, "Escribe algo que buscar")
    opciones = gv.buscar_musica(q.strip())
    if not opciones:
        raise HTTPException(404, "Ninguna canción libre coincide con esa búsqueda")
    return {"opciones": opciones}


class EleccionMusica(BaseModel):
    candidato: dict


@app.post("/api/musica/descargar")
def descargar_musica(eleccion: EleccionMusica):
    """Baja la pista elegida del banco y devuelve su nombre ya utilizable."""
    candidato = eleccion.candidato
    if not candidato.get("enlace") or not candidato.get("id"):
        raise HTTPException(400, "Candidato incompleto")
    ruta = gv.descargar_pista(candidato)
    if not ruta:
        raise HTTPException(502, "No se pudo descargar esa canción")
    return {"nombre": ruta.name,
            "credito": _creditos_musica().get(ruta.name, {}).get("texto")}


@app.get("/musica/{nombre}")
def servir_musica(nombre: str):
    ruta = _ruta_musica(nombre)
    if not ruta:
        raise HTTPException(404, "Pista no encontrada")
    return FileResponse(ruta)


class AjusteMusica(BaseModel):
    musica: str | None = None
    volumen_musica: float = gv.MUSICA_VOLUMEN


@app.post("/api/musica/{base_id}")
def cambiar_musica(base_id: str, ajuste: AjusteMusica):
    """Cambia pista y volumen de un vídeo ya generado (luego hay que remontar)."""
    plan = _cargar_plan(base_id)
    if not plan:
        raise HTTPException(404, "Ese vídeo no tiene datos guardados")
    pista = _elegir_musica(ajuste.musica) if ajuste.musica else None
    plan["musica"] = str(pista) if pista else None
    plan["volumen_musica"] = max(0.0, min(ajuste.volumen_musica, 1.0))
    _guardar_plan(base_id, plan)
    return {"musica": pista.name if pista else None,
            "volumen_musica": plan["volumen_musica"]}


def _montar(base_id: str, trabajo_id: str) -> None:
    """Monta el vídeo con el plan de clips actual. La voz ya debe existir."""
    audio_wav = gv.TMP_DIR / f"{base_id}.wav"
    srt_path = gv.TMP_DIR / f"{base_id}.srt"
    salida_mp4 = gv.SALIDA_DIR / f"{base_id}.mp4"
    plan = _cargar_plan(base_id)

    dur = gv.duracion_audio(audio_wav)
    clips = gv.preparar_clips(_rutas_de_plan(plan)) or None
    musica = Path(plan["musica"]) if plan.get("musica") else None

    gv.SALIDA_DIR.mkdir(exist_ok=True)
    gv.montar_video(audio_wav, srt_path, salida_mp4, dur, clips=clips, musica=musica,
                    volumen_musica=plan.get("volumen_musica", gv.MUSICA_VOLUMEN))
    _trabajos[trabajo_id].update(
        estado="listo", paso="Vídeo listo", porcentaje=100,
        # el sufijo obliga al navegador a recargar el vídeo en vez de usar el viejo
        video=f"/videos/{salida_mp4.name}?v={int(time.time())}", duracion=round(dur, 1),
    )


def _producir_video(trabajo_id: str, datos: dict) -> None:
    """Ejecuta el pipeline del Módulo 2 en segundo plano, informando del paso."""
    def paso(texto: str, pct: int) -> None:
        _trabajos[trabajo_id].update(paso=texto, porcentaje=pct)

    try:
        guion = datos["guion"]
        base_id = datos["id"]
        gv.TMP_DIR.mkdir(exist_ok=True)
        audio_wav = gv.TMP_DIR / f"{base_id}.wav"
        srt_path = gv.TMP_DIR / f"{base_id}.srt"

        paso("Generando la voz...", 15)
        texto = gv.construir_texto(guion)
        gv.generar_audio_piper(gv.aplicar_pronunciaciones(texto),
                               gv.VOZ_MODELO_DEFECTO, audio_wav)

        paso("Preparando subtítulos...", 30)
        dur = gv.duracion_audio(audio_wav)
        gv.generar_srt(guion, dur, srt_path)

        cuantos = _clips_necesarios(dur)
        paso(f"Buscando {cuantos} vídeos de fondo...", 45)
        terminos = guion.get("broll") or gv.BROLL_TERMINOS_DEFECTO
        pista = _elegir_musica(datos.get("musica"))
        plan = {"terminos": terminos, "candidatos": [], "usados": [],
                "musica": str(pista) if pista else None,
                "volumen_musica": datos.get("volumen_musica", gv.MUSICA_VOLUMEN)}
        plan["candidatos"] = gv.buscar_candidatos(terminos)
        elegidos = _descargar_varios(_repartir_por_termino(plan["candidatos"]), cuantos)
        plan["usados"] = [c["id"] for c in elegidos]
        _guardar_plan(base_id, plan)

        paso("Montando el vídeo...", 60)
        _montar(base_id, trabajo_id)

        # marca la noticia como procesada para que no reaparezca como nueva
        estado = nr.cargar_estado()
        if base_id not in estado["procesadas"]:
            estado["procesadas"] = sorted(set(estado["procesadas"]) | {base_id})
            nr.guardar_estado(estado)
    except Exception as e:
        traceback.print_exc()
        _trabajos[trabajo_id].update(estado="error", paso=f"Error: {e}", porcentaje=100)


def _remontar_video(trabajo_id: str, base_id: str) -> None:
    """Rehace solo el montaje tras cambiar clips: reutiliza voz y subtítulos."""
    try:
        _trabajos[trabajo_id].update(paso="Montando el vídeo...", porcentaje=40)
        _montar(base_id, trabajo_id)
    except Exception as e:
        traceback.print_exc()
        _trabajos[trabajo_id].update(estado="error", paso=f"Error: {e}", porcentaje=100)


@app.get("/api/clips/{base_id}")
def listar_clips(base_id: str):
    """Clips de fondo en uso, con miniatura, y si quedan alternativas."""
    plan = _cargar_plan(base_id)
    if not plan:
        raise HTTPException(404, "Ese vídeo no tiene clips guardados")
    por_id = {c["id"]: c for c in plan.get("candidatos", [])}
    clips = []
    for usado in plan.get("usados", []):
        ruta = gv.ruta_de_clip(usado)
        mini = gv.generar_miniatura(ruta) if ruta.is_file() else None
        info = por_id.get(usado, {})
        clips.append({
            "id": usado,
            "termino": info.get("termino", ""),
            "autor": info.get("autor", ""),
            "miniatura": f"/miniaturas/{mini.name}" if mini else None,
        })
    disponibles = len(por_id) - len(plan.get("usados", []))
    nombre_musica = Path(plan["musica"]).name if plan.get("musica") else None
    credito = _creditos_musica().get(nombre_musica, {})
    return {
        "clips": clips,
        "alternativas": max(disponibles, 0),
        "musica": nombre_musica,
        "titulo_musica": credito.get("titulo"),
        "volumen_musica": plan.get("volumen_musica", gv.MUSICA_VOLUMEN),
        # texto que habrá que poner en la descripción al publicar
        "credito_musica": credito.get("texto"),
    }


@app.get("/api/buscar_clips")
def buscar_clips(q: str):
    """Busca vídeos de fondo en todas las fuentes y devuelve las miniaturas.

    No descarga nada: sirve para que el usuario vea las opciones y elija.
    """
    if not q.strip():
        raise HTTPException(400, "Escribe algo que buscar")
    candidatos = gv.buscar_candidatos([q.strip()], por_termino=24)
    if not candidatos and not (os.environ.get("PEXELS_API_KEY") or
                               os.environ.get("PIXABAY_API_KEY")):
        raise HTTPException(400, "No hay ninguna clave de banco de vídeos configurada")
    return {"opciones": [c for c in candidatos if c.get("imagen")]}


class Eleccion(BaseModel):
    candidato: dict


@app.post("/api/clips/{base_id}/elegir/{indice}")
def elegir_clip(base_id: str, indice: int, eleccion: Eleccion):
    """Pone el clip elegido en la posición indicada, dejando los demás igual."""
    plan = _cargar_plan(base_id)
    if not plan or indice >= len(plan.get("usados", [])):
        raise HTTPException(404, "Clip no encontrado")

    candidato = eleccion.candidato
    if not candidato.get("enlace") or "id" not in candidato:
        raise HTTPException(400, "Candidato incompleto")
    if not gv.descargar_candidato(candidato):
        raise HTTPException(502, "No se pudo descargar ese vídeo")

    plan["usados"][indice] = candidato["id"]
    # se recuerda para poder mostrar su tema y autor en la lista
    if not any(c["id"] == candidato["id"] for c in plan.get("candidatos", [])):
        plan.setdefault("candidatos", []).append(candidato)
    _guardar_plan(base_id, plan)
    return listar_clips(base_id)


@app.post("/api/remontar/{base_id}")
def remontar(base_id: str):
    """Rehace el vídeo con los clips cambiados (sin volver a generar la voz)."""
    if not (gv.TMP_DIR / f"{base_id}.wav").is_file():
        raise HTTPException(404, "No hay voz generada para esa noticia")
    trabajo_id = uuid.uuid4().hex[:8]
    _trabajos[trabajo_id] = {"estado": "trabajando", "paso": "Empezando...", "porcentaje": 10}
    threading.Thread(target=_remontar_video, args=(trabajo_id, base_id), daemon=True).start()
    return {"trabajo": trabajo_id}


@app.get("/miniaturas/{nombre}")
def servir_miniatura(nombre: str):
    ruta = gv.BROLL_CACHE / "miniaturas" / Path(nombre).name
    if not ruta.is_file():
        raise HTTPException(404, "Miniatura no encontrada")
    return FileResponse(ruta, media_type="image/jpeg")


@app.post("/api/video")
def crear_video(g: GuionEditado):
    """Arranca la generación del vídeo con el guion ya editado por el usuario."""
    datos = {
        "id": g.id, "fuente": g.fuente, "titulo": g.titulo, "url": g.url,
        "generado": datetime.now(timezone.utc).isoformat(),
        "guion": {"hook": g.hook, "cuerpo": g.cuerpo, "cierre": g.cierre,
                  "hashtags": g.hashtags, "broll": g.broll},
        "musica": g.musica,
        "volumen_musica": max(0.0, min(g.volumen_musica, 1.0)),
    }
    # guarda el guion editado: lo que se publique será exactamente esto
    nr.GUIONES_DIR.mkdir(exist_ok=True)
    (nr.GUIONES_DIR / f"{g.id}.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    trabajo_id = uuid.uuid4().hex[:8]
    _trabajos[trabajo_id] = {"estado": "trabajando", "paso": "Empezando...", "porcentaje": 5}
    threading.Thread(target=_producir_video, args=(trabajo_id, datos), daemon=True).start()
    return {"trabajo": trabajo_id}


@app.get("/api/video/{trabajo_id}")
def estado_video(trabajo_id: str):
    if trabajo_id not in _trabajos:
        raise HTTPException(404, "Trabajo desconocido")
    return _trabajos[trabajo_id]


@app.get("/videos/{nombre}")
def servir_video(nombre: str):
    ruta = gv.SALIDA_DIR / Path(nombre).name  # .name evita salirse de la carpeta
    if not ruta.is_file():
        raise HTTPException(404, "Vídeo no encontrado")
    return FileResponse(ruta, media_type="video/mp4", filename=ruta.name)


def _arrancar(puerto: int, **ssl) -> None:
    uvicorn.run(app, host="0.0.0.0", port=puerto, log_level="warning", **ssl)


if __name__ == "__main__":
    ip = _ip_local()
    cert, clave = CERT_DIR / "cert.pem", CERT_DIR / "clave.pem"
    hay_cert = cert.is_file() and clave.is_file()

    print(f"\n  ABRE ESTO EN EL MÓVIL (misma red WiFi):\n"
          f"      http://{ip}:{PUERTO}\n", flush=True)
    if hay_cert:
        # Los dos puertos a la vez: si el aviso del certificado da problemas,
        # por http siempre se puede entrar aunque no se pueda compartir.
        print(f"  Y para poder COMPARTIR a Instagram, esta otra:\n"
              f"      https://{ip}:{PUERTO_SEGURO}\n"
              f"  (Chrome dirá que no es privada: 'Configuración avanzada' → "
              f"'Continuar a {ip} (no seguro)')\n", flush=True)
        threading.Thread(
            target=_arrancar, args=(PUERTO_SEGURO,),
            kwargs={"ssl_certfile": str(cert), "ssl_keyfile": str(clave)},
            daemon=True,
        ).start()
    else:
        print("  Para compartir a Instagram hace falta HTTPS:\n"
              "  ejecuta ./crear_certificado.sh y reinicia este servidor.\n", flush=True)

    print("  Usa 'Añadir a pantalla de inicio' para tenerlo como una app.\n", flush=True)
    _arrancar(PUERTO)
