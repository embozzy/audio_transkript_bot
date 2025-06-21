# main.py
import logging
import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pydub import AudioSegment
import google.generativeai as genai

# --- Конфигурация ---
# Берем ключи из переменных окружения, которые настроим на Render
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Настройка логирования для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Инициализация Gemini API ---
try:
    if not GEMINI_API_KEY:
        logger.error("Ключ GEMINI_API_KEY не найден!")
        model = None
    else:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('models/gemini-1.5-flash')
        logger.info("Gemini API успешно настроен.")
except Exception as e:
    logger.error(f"Ошибка при настройке Gemini API: {e}")
    model = None

# --- Функции-обработчики команд ---

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
    # Поддерживаем и голосовые сообщения, и аудиофайлы
    audio_source = message.voice or message.audio

    if not audio_source:
        return

    # Отправляем пользователю сообщение о том, что начали обработку
    processing_message = await message.reply_text("🧠 Получил. Начинаю расшифровку...")

    try:
        # 1. Скачиваем файл
        audio_file = await audio_source.get_file()
        
        # Создаем уникальное имя файла
        file_path_original = f"downloads/{audio_source.file_unique_id}"
        file_path_mp3 = f"downloads/{audio_source.file_unique_id}.mp3"
        os.makedirs("downloads", exist_ok=True) # Создаем папку, если ее нет

        await audio_file.download_to_drive(file_path_original)
        logger.info(f"Аудиофайл сохранен как {file_path_original}")

        # 2. Конвертируем в .mp3
        sound = AudioSegment.from_file(file_path_original)
        sound.export(file_path_mp3, format="mp3")
        logger.info(f"Файл конвертирован в {file_path_mp3}")

        # 3. Отправляем файл в Gemini API для распознавания
        audio_file_for_gemini = genai.upload_file(path=file_path_mp3)
        
        # 4. Делаем запрос на распознавание
        prompt = "Расшифруй это аудио сообщение. Сохрани оригинальный язык и форматирование."
        response = await model.generate_content_async([prompt, audio_file_for_gemini])

        # 5. Отправляем результат пользователю
        transcribed_text = response.text if response.text else "[Не удалось распознать текст]"

        await processing_message.edit_text(
            f"📄 **Расшифровка:**\n\n{transcribed_text}"
        )

    except Exception as e:
        logger.error(f"Произошла ошибка при обработке аудио: {e}")
        await processing_message.edit_text(
            "😕 Упс! Что-то пошло не так во время обработки вашего сообщения. Попробуйте еще раз."
        )
    finally:
        # 6. Удаляем временные файлы
        if os.path.exists(file_path_original):
            os.remove(file_path_original)
        if os.path.exists(file_path_mp3):
            os.remove(file_path_mp3)
        logger.info("Временные файлы удалены.")


def main():
    """Основная функция для запуска бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден! Завершение работы.")
        return
        
    logger.info("Запуск бота...")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    # Бот будет реагировать и на голосовые, и на аудиофайлы
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))

    # Запускаем бота
    application.run_polling()


if __name__ == '__main__':
    main()
