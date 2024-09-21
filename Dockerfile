# Используем официальный базовый образ Python
FROM python:3.9

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем все файлы в контейнер
COPY . .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Указываем команду для запуска приложения
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
