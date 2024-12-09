# bot/main.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from config import TOKEN
from handlers import (
    start,
    help_command,
    handle_text,
    error_handler
)
from logging_config import logger

def main():
    if not TOKEN:
        logger.error("Токен бота не установлен. Проверьте файл .env")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Обработчик простых текстовых сообщений (кнопки, отзывы и т.д.)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("Запуск бота...")
    application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    main()