# main.py
import logging
import os
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters
from pydub import AudioSegment
import google.generativeai as genai

# --- Конфигурация ---
# Берем ключи из переменных окружения, которые настроены на Render
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Настройка логирования для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Инициализация Gemini API ---
model = None
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('models/gemini-1.5-flash')
        logger.info("Gemini API успешно настроен.")
    else:
        logger.error("Ключ GEMINI_API_KEY не найден!")
except Exception as e:
    logger.error(f"Ошибка при настройке Gemini API: {e}")

# --- Функции-обработчики команд Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"👋 Привет, {user.mention_html()}!\n\n"
        "Я бот для расшифровки голосовых сообщений. Просто перешлите мне любое аудио, и я превращу его в текст.",
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых и аудио сообщений."""
    if not model:
        await update.message.reply_text("🚫 Ошибка: API Gemini не настроен. Проверьте ваш API ключ на сервере.")
        return

    message = update.message
    audio_source = message.voice or message.audio
    if not audio_source:
        return

    processing_message = await message.reply_text("🧠 Получил. Начинаю расшифровку...")

    try:
        audio_file = await audio_source.get_file()
        
        file_path_original = f"downloads/{audio_source.file_unique_id}"
        file_path_mp3 = f"downloads/{audio_source.file_unique_id}.mp3"
        os.makedirs("downloads", exist_ok=True)

        await audio_file.download_to_drive(file_path_original)
        logger.info(f"Аудиофайл сохранен как {file_path_original}")

        sound = AudioSegment.from_file(file_path_original)
        sound.export(file_path_mp3, format="mp3")
        logger.info(f"Файл конвертирован в {file_path_mp3}")

        audio_file_for_gemini = genai.upload_file(path=file_path_mp3)
        
        prompt = "Расшифруй это аудио сообщение. Сохрани оригинальный язык и форматирование."
        response = await model.generate_content_async([prompt, audio_file_for_gemini])

        transcribed_text = response.text if response.text else "[Не удалось распознать текст]"

        await processing_message.edit_text(
            f"📄 **Расшифровка:**\n\n{transcribed_text}"
        )

    except Exception as e:
        logger.error(f"Произошла ошибка при обработке аудио: {e}", exc_info=True)
        await processing_message.edit_text(
            "😕 Упс! Что-то пошло не так во время обработки вашего сообщения. Попробуйте еще раз."
        )
    finally:
        if os.path.exists(file_path_original):
            os.remove(file_path_original)
        if os.path.exists(file_path_mp3):
            os.remove(file_path_mp3)
        logger.info("Временные файлы удалены.")

# --- Функции для веб-сервера-пустышки ---

def run_flask_app():
    """Запускает пустой веб-сервер, чтобы Render был доволен."""
    app = Flask(__name__)

    @app.route('/')
    def index():
        return "Бот работает в режиме polling."

    # Render использует переменную PORT для своего роутера
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- Основная функция ---

def main():
    """Основная функция для запуска бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден! Завершение работы.")
        return

    # 1. Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Dummy Flask сервер запущен в отдельном потоке.")
    
    # 2. Запускаем бота в основном потоке
    logger.info("Запуск бота в режиме polling...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))

    application.run_polling()

if __name__ == '__main__':
    main()
