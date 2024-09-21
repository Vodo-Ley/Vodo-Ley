FROM python:3.9

# Установка необходимых зависимостей
RUN pip install python-telegram-bot==0.28.0

# Копируем ваш код в контейнер
COPY . /app

# Установка зависимостей из requirements.txt
RUN pip install -r /app/requirements.txt

# Указываем рабочую директорию
WORKDIR /app

# Команда запуска вашего бота
CMD ["python", "main.py"]
