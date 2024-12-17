# bot/main.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from config import TOKEN
from handlers import (
    start,
    help_command,
    handle_text_with_limit,
    add_premium_user,
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
    application.add_handler(CommandHandler("add_premium", add_premium_user))

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_with_limit))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("Запуск бота...")
    application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    main()