#!/usr/bin/env python3
"""
voz_xtts.py

Locuta un texto con XTTS v2 clonando una voz de referencia. Es un proceso
APARTE que se ejecuta con el Python de `.venv-voz/`, no con el del bot:

  - XTTS necesita PyTorch y `transformers<5`, y meterlos en el entorno del bot
    añadiría varios GB y arriesgaría romper Piper.
  - Si el modelo revienta o se queda sin memoria, se cae este proceso y no el
    servidor.

Lo llama guion_a_video.generar_audio_xtts(); no está pensado para usarse a mano,
pero funciona igual:

    .venv-voz/bin/python files/voz_xtts.py texto.txt referencia.wav salida.wav

LICENCIA: los pesos de XTTS v2 van con la Coqui Public Model License, que solo
permite uso NO COMERCIAL, y eso incluye lo que genera el modelo: un reel con
esta voz no puede monetizarse. La librería pide aceptarla por consola, así que
aquí se acepta solo si el usuario lo ha activado a propósito con
XTTS_LICENCIA_CPML_ACEPTADA=1 en files/.env (lo comprueba el que nos llama).
"""

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

if len(sys.argv) != 4:
    sys.exit("Uso: voz_xtts.py <texto.txt> <referencia.wav> <salida.wav>")
ruta_texto, ruta_referencia, ruta_salida = (Path(a) for a in sys.argv[1:4])

import torch
import torchaudio
from TTS.api import TTS

# torchaudio >= 2.9 lee audio con torchcodec, que necesita las librerías de
# ffmpeg del sistema (en esta máquina solo hay un binario estático). Se lee la
# muestra de voz con soundfile, que no depende de nada del sistema.
def _cargar(ruta, *_, **__):
    datos, frecuencia = sf.read(str(ruta), dtype="float32", always_2d=True)
    return torch.from_numpy(datos.T.copy()), frecuencia


torchaudio.load = _cargar

texto = ruta_texto.read_text(encoding="utf-8").strip()
if not texto:
    sys.exit("El texto está vacío")
if not ruta_referencia.is_file():
    sys.exit(f"No existe la muestra de voz: {ruta_referencia}")

t0 = time.monotonic()
modelo = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
print(f"modelo cargado en {time.monotonic() - t0:.0f} s", file=sys.stderr, flush=True)

t1 = time.monotonic()
audio = np.array(
    modelo.tts(text=texto, language="es", speaker_wav=str(ruta_referencia)),
    dtype=np.float32,
)
# XTTS devuelve flotantes en [-1, 1] a 24 kHz; se guarda como PCM de 16 bits
sf.write(str(ruta_salida), audio, 24000, subtype="PCM_16")
duracion = len(audio) / 24000
print(f"{duracion:.1f} s de audio en {time.monotonic() - t1:.0f} s", file=sys.stderr, flush=True)
