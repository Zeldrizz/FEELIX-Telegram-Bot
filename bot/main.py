# bot/main.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from config import TOKEN
from handlers import (
    start, 
    help_command, 
    refresh, 
    feedback, 
    get_feedbacks, 
    handle_message, 
    error_handler
)
from logging_config import logger

def main():
    if not TOKEN:
        logger.error("Токен бота не установлен. Проверьте файл .env")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("refresh", refresh))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("get_feedbacks", get_feedbacks))

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    application.add_error_handler(error_handler)

    logger.info("Запуск бота...")
    application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    main()