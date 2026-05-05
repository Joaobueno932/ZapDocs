@echo off
title WhatsApp2PDF Web
cd /d "%~dp0"

echo.
echo  Instalando dependencias...
pip install -r requirements.txt -q

echo.
echo  Iniciando servidor...
echo  Acesse: http://localhost:5000
echo.

start "" "http://localhost:5000"
python app.py

pause
