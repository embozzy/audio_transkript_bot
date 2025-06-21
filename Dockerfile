# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем и устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код нашего бота
COPY main.py .

# Команда для запуска бота
CMD ["python", "main.py"]