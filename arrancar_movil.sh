#!/usr/bin/env bash
# Arranca la interfaz web del bot de reels para usarla desde el móvil.
# El servidor debe correr desde files/ porque los scripts usan rutas relativas.
cd "$(dirname "$0")/files" || exit 1
exec ../.venv/bin/python3 servidor.py
