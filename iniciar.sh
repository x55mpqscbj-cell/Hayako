#!/bin/bash
# ==========================================================
#  🌿 EcoRuta RD • Script de Inicio Rápido (Santiago, RD)
# ==========================================================

# Asegurar que estamos en el directorio del script
cd "$(dirname "$0")"

echo "=========================================================="
echo "  🌿 EcoRuta RD • Iniciando Servidor en Santiago, RD"
echo "=========================================================="

# 1. Verificar o crear el entorno virtual automáticamente
if [ ! -d "./venv" ] || [ ! -f "./venv/bin/python3" ]; then
    echo "-> Configurando entorno virtual local (venv) por primera vez..."
    python3 -m venv venv
    echo "-> Instalando paquetes necesarios (Flask, SQLAlchemy)..."
    ./venv/bin/pip install --quiet flask flask-sqlalchemy python-dotenv
fi

# 2. Verificar que Flask esté disponible en venv
if ! ./venv/bin/python3 -c "import flask, flask_sqlalchemy" 2>/dev/null; then
    echo "-> Instalando dependencias en el entorno virtual..."
    ./venv/bin/pip install --quiet flask flask-sqlalchemy python-dotenv
fi

echo "-> Entorno virtual listo: ./venv"
echo "-> Servidor iniciando en: http://localhost:5050"
echo "-> Presiona Ctrl + C para detener."
echo "=========================================================="

./venv/bin/python3 app.py
