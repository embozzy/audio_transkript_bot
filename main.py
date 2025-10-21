import logging
import os
import asyncio
import threading
import base64
from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters
from pydub import AudioSegment
import google.generativeai as genai

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
ALLOWED_GROUP_ID = os.environ.get('ALLOWED_GROUP_ID')

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
        model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini API успешно настроен.")
    else:
        logger.error("Ключ GEMINI_API_KEY не найден!")
except Exception as e:
    logger.error(f"Ошибка при настройке Gemini API: {e}")

# --- Функции-обработчики команд Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    chat_id = update.message.chat_id
    if ALLOWED_GROUP_ID and str(chat_id) != ALLOWED_GROUP_ID and update.message.chat.type != 'private':
        logger.info(f"Игнорирование команды start из неразрешенного чата: {chat_id}")
        return

    user = update.effective_user
    await update.message.reply_html(
        f"👋 Привет, {user.mention_html()}!\n\n"
        "Я бот для расшифровки. Просто перешлите мне голосовое, аудио или видео-кружочек.",
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых, аудио и видео сообщений."""
    chat_id = update.message.chat_id
    if ALLOWED_GROUP_ID and str(chat_id) != ALLOWED_GROUP_ID and update.message.chat.type != 'private':
        logger.info(f"Игнорирование медиа из неразрешенного чата: {chat_id}")
        return
        
    if not model:
        await update.message.reply_text("🚫 Ошибка: API Gemini не настроен.")
        return

    message = update.message
    media_source = message.voice or message.audio or message.video_note
    if not media_source:
        return

    processing_message = await message.reply_text("🧠 Получил. Начинаю расшифровку...")
    
    file_path_original = None
    file_path_mp3 = None

    try:
        media_file = await media_source.get_file()
        
        file_path_original = f"downloads/{media_source.file_unique_id}"
        file_path_mp3 = f"downloads/{media_source.file_unique_id}.mp3"
        os.makedirs("downloads", exist_ok=True)

        await media_file.download_to_drive(file_path_original)
        logger.info(f"Медиафайл сохранен как {file_path_original}")

        sound = AudioSegment.from_file(file_path_original)
        sound.export(file_path_mp3, format="mp3")
        logger.info(f"Файл конвертирован в {file_path_mp3}")

        # --- НОВЫЙ МЕТОД, КОТОРЫЙ ВЫ НАШЛИ ---
        # 1. Читаем файл в бинарном режиме
        with open(file_path_mp3, "rb") as audio_file:
            # 2. Кодируем его в Base64
            encoded_string = base64.b64encode(audio_file.read()).decode('utf-8')

        # 3. Готовим данные для API
        audio_data_for_gemini = {
            "inline_data": {
                "mime_type": "audio/mpeg",  # MIME-тип для MP3
                "data": encoded_string
            }
        }
        
        prompt = "Расшифруй это аудио сообщение. Игнорируй любую музыку или фоновые звуки, транскрибируй только человеческую речь. Сохрани оригинальный язык и форматирование."
        
        # 4. Отправляем данные напрямую, без upload_file
        response = await model.generate_content_async([prompt, audio_data_for_gemini])

        transcribed_text = response.text if response.text else "[Не удалось распознать текст]"

        await processing_message.edit_text(
            f"📄 **Расшифровка:**\n\n{transcribed_text}"
        )

    except Exception as e:
        logger.error(f"Произошла ошибка при обработке медиа: {e}", exc_info=True)
        await processing_message.edit_text(
            "😕 Упс! Что-то пошло не так. Попробуйте еще раз."
        )
    finally:
        if file_path_original and os.path.exists(file_path_original):
            os.remove(file_path_original)
        if file_path_mp3 and os.path.exists(file_path_mp3):
            os.remove(file_path_mp3)
        logger.info("Временные файлы удалены.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    chat_id = update.message.chat_id
    # Отвечаем на текст только в личных сообщениях
    if update.message.chat.type == 'private':
        await update.message.reply_text(
            "Я понимаю только голосовые, аудио и видео-кружочки. Пожалуйста, отправьте один из этих форматов."
        )
    else:
        logger.info(f"Игнорирование текста из чата {chat_id}, как и было запрошено.")

# --- Функции для веб-сервера-пустышки ---

def run_flask_app():
    """Запускает пустой веб-сервер, чтобы Render был доволен."""
    app = Flask(__name__)
    @app.route('/')
    def index():
        return "Бот работает в режиме polling."
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- Основная функция ---

def main() -> None:
    """Основная функция для запуска бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден! Завершение работы.")
        return

    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Dummy Flask сервер запущен.")
    
    # Запускаем бота. Эта функция блокирует выполнение, пока процесс не будет остановлен.
    logger.info("Запуск бота...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()

