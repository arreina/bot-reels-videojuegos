#!/usr/bin/env bash
# Crea el certificado HTTPS que necesita el móvil para poder COMPARTIR el vídeo
# directamente a Instagram, WhatsApp o Telegram (Android solo habilita el menú
# de compartir en conexiones seguras).
#
# Vuelve a ejecutarlo si cambia la IP local del PC.
set -e
cd "$(dirname "$0")"
mkdir -p certificado
IP=$(hostname -I | awk '{print $1}')

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout certificado/clave.pem -out certificado/cert.pem \
  -subj "/CN=Bot de reels" \
  -addext "subjectAltName=IP:${IP},IP:127.0.0.1,DNS:localhost" 2>/dev/null

echo "Certificado creado para la IP ${IP}"
echo "Arranca el servidor con ./arrancar_movil.sh y abre https://${IP}:8000 en el móvil."
echo "Chrome avisará de que el sitio no es seguro: pulsa 'Configuración avanzada' y 'Continuar'."
