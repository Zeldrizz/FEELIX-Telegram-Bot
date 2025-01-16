# bot/main.py
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    JobQueue,
)
from config import TOKEN
from handlers import (
    start,
    help_command,
    handle_text,
    add_premium_user,
    error_handler,
    get_groq_response
)
from utils import (
    get_inactive_users,
    update_inactivity_timestamp,
)
from logging_config import logger

async def job_check_inactive_users(context: CallbackContext):
    """
    Периодическая задача для проверки неактивных пользователей и отправки им «пробуждающих» сообщений.

    Функция проверяет, какие пользователи не взаимодействовали с ботом в течение 
    48 и более часов, и отправляет им сообщение, инициируя диалог. Сообщения 
    отправляются пакетами для оптимизации работы.

    :param context: Объект CallbackContext, предоставляющий контекст для выполнения задачи
    """
    inactive_users = get_inactive_users(hours=48)
    if not inactive_users:
        return

    batch_size = 15
    for i in range(0, len(inactive_users), batch_size):
        batch = inactive_users[i:i+batch_size]
        
        for user_id in batch:
            try:
                prompt = "Пользователь не писал тебе несколько дней, попробуй сам начать разговор от первого лица. И закончи свое сообщение добрыми пожеланиями данному пользователю."

                bot_text = await get_groq_response(
                    user_id=user_id,
                    prompt_ru=prompt,
                )

                await context.bot.send_message(chat_id=user_id, text=bot_text)

                update_inactivity_timestamp(user_id)

            except Exception as e:
                logger.error(f"Не удалось отправить «пробуждающее» сообщение {user_id}: {e}")

        if i + batch_size < len(inactive_users):
            await asyncio.sleep(60)

def main():
    if not TOKEN:
        logger.error("Токен бота не установлен. Проверьте файл .env")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_premium", add_premium_user))

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    job_queue = application.job_queue
    job_queue.run_repeating(
        callback=job_check_inactive_users,
        interval=3600, # каждый час чекаем кого надо пробудить
        first=30 # запуск спустя 30 секунд после старта бота
    )

    logger.info("Запуск бота...")
    application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    main()