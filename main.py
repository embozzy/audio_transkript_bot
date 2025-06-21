# main.py
import logging
import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters

from pydub import AudioSegment
import google.generativeai as genai

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
# ID группы, в которой бот должен работать. Берется из переменных окружения.
ALLOWED_GROUP_ID = os.environ.get('ALLOWED_GROUP_ID')

# Настройка логирования
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

# --- Обработчики команд Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    # Команда /start может быть вызвана в личных сообщениях или в разрешенной группе
    chat_type = update.message.chat.type
    chat_id_str = str(update.message.chat_id)

    if ALLOWED_GROUP_ID and chat_type != 'private' and chat_id_str != ALLOWED_GROUP_ID:
        logger.info(f"Игнорирование команды start из чата {chat_id_str}")
        return
        
    user = update.effective_user
    await update.message.reply_html(
        f"👋 Привет, {user.mention_html()}!\n\n"
        "Я бот для расшифровки голосовых сообщений, аудиофайлов и видео-кружочков. Просто перешлите мне любое из этих медиа, и я превращу его в текст.",
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых, аудио и видео-сообщений."""
    # Проверяем, что сообщение пришло из разрешенной группы
    # Если ALLOWED_GROUP_ID не задан, бот работает везде
    if ALLOWED_GROUP_ID and str(update.message.chat.id) != ALLOWED_GROUP_ID:
        logger.info(f"Игнорирование медиа из чата {update.message.chat.id}")
        return

    if not model:
        await update.message.reply_text("🚫 Ошибка: API Gemini не настроен. Проверьте ваш API ключ на сервере.")
        return

    message = update.message
    # Поддерживаем голосовые, аудио и видео-кружочки
    media_source = message.voice or message.audio or message.video_note
    if not media_source:
        return

    # В группе отвечаем на то сообщение, которое расшифровываем
    processing_message = await message.reply_text("🧠 Получил. Начинаю расшифровку...")

    try:
        media_file = await media_source.get_file()
        
        # Создаем временную директорию
        os.makedirs("downloads", exist_ok=True)
        file_path_original = f"downloads/{media_source.file_unique_id}"
        file_path_mp3 = f"downloads/{media_source.file_unique_id}.mp3"

        await media_file.download_to_drive(file_path_original)
        
        # pydub сам извлечет аудиодорожку из видео
        sound = AudioSegment.from_file(file_path_original)
        sound.export(file_path_mp3, format="mp3")

        audio_file_for_gemini = genai.upload_file(path=file_path_mp3)
        
        prompt = "Расшифруй аудиодорожку из этого файла. Сохрани оригинальный язык и форматирование."
        response = await model.generate_content_async([prompt, audio_file_for_gemini])

        transcribed_text = response.text if response.text else "[Не удалось распознать текст]"

        await processing_message.edit_text(f"📄 **Расшифровка:**\n\n{transcribed_text}")

    except Exception as e:
        logger.error(f"Произошла ошибка при обработке медиа: {e}", exc_info=True)
        await processing_message.edit_text("😕 Упс! Что-то пошло не так. Попробуйте еще раз.")
    finally:
        # Очистка временных файлов
        if os.path.exists(file_path_original):
            os.remove(file_path_original)
        if os.path.exists(file_path_mp3):
            os.remove(file_path_mp3)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    # Проверяем, что сообщение пришло из разрешенной группы
    if ALLOWED_GROUP_ID and str(update.message.chat.id) != ALLOWED_GROUP_ID:
        logger.info(f"Игнорирование текста из чата {update.message.chat.id}")
        return
        
    await update.message.reply_text(
        "Я умею работать только с медиа. Пожалуйста, отправьте мне голосовое сообщение, аудиофайл или видео-кружочек."
    )

# --- Веб-сервер-пустышка для Render ---

def run_flask_app():
    """Запускает пустой веб-сервер, чтобы Render был доволен."""
    app = Flask(__name__)
    @app.route('/')
    def index():
        return "Бот работает в режиме polling."
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- Основная точка входа ---

def main() -> None:
    """Основная функция для запуска бота и веб-сервера."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден! Завершение работы.")
        return

    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Dummy Flask сервер запущен в отдельном потоке.")

    # Создаем приложение бота
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, handle_media))
    # Добавляем обработчик для текста, исключая команды
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


    # Запускаем бота. drop_pending_updates=True сбрасывает "застрявшие" сообщения при старте.
    logger.info("Запуск бота...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
