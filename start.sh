#!/bin/bash
# Устанавливаем зависимости
pip install -r requirements.txt

# Запускаем приложение
uvicorn main:app --host 0.0.0.0 --port 8000