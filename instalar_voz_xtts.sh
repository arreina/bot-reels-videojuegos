#!/usr/bin/env bash
# Instala XTTS v2 (voz clonada) en un entorno APARTE, .venv-voz/.
#
# Va aparte porque necesita PyTorch y transformers<5, y meterlos en el entorno
# del bot añadiría varios GB y arriesgaría romper Piper. El bot lo llama como
# un proceso externo (files/voz_xtts.py).
#
# LICENCIA: los pesos de XTTS v2 van con la Coqui Public Model License, que solo
# permite uso NO COMERCIAL (también para el audio que genera): un reel con esta
# voz no se puede monetizar. Coqui cerró en 2024, así que ya no hay a quién
# comprarle una licencia comercial. Para activarlo en el bot hay que poner
# XTTS_LICENCIA_CPML_ACEPTADA=1 en files/.env, a propósito.
#
# Ocupa ~3 GB de entorno y ~1,9 GB de pesos (se bajan en el primer uso).
#
# Cada paso responde a un fallo real que salió al montarlo; no los reordenes ni
# los quites sin probar:
set -euo pipefail
cd "$(dirname "$0")"

# 1. entorno aislado (el venv del bot no trae pip, de ahí virtualenv)
.venv/bin/pip install -q virtualenv
.venv/bin/virtualenv -q .venv-voz
PIP=".venv-voz/bin/pip"
CPU="--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"

# 2. la librería. coqui-tts es el fork que mantiene la comunidad desde el cierre
#    de Coqui. NO trae PyTorch: sin el paso siguiente falla al importar.
$PIP install -q coqui-tts soundfile $CPU

# 3. PyTorch de CPU (la gráfica AMD RX 580 no sirve ni para CUDA ni para ROCm)
$PIP install -q torch torchaudio $CPU

# 4. coqui-tts admite transformers 5 en su metadata pero NO funciona con él
#    (falta isin_mps_friendly): hay que bajar a la serie 4.
$PIP install -q "transformers<5"

# 5. desde PyTorch 2.9 la lectura de audio pasa por torchcodec
$PIP install -q torchcodec $CPU

.venv-voz/bin/python -c "from TTS.api import TTS; print('XTTS listo: la librería importa bien')"
echo
echo "Falta tu muestra de voz: unos 15 s leyendo con naturalidad, mono, en voz_muestra/referencia.wav"
echo "y, si aceptas la licencia (solo uso no comercial), XTTS_LICENCIA_CPML_ACEPTADA=1 en files/.env"
