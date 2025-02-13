import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    JobQueue,
    CallbackQueryHandler
)
from telegram.error import Forbidden, BadRequest
from config import TOKEN
from handlers import (
    start,
    help_command,
    handle_text,
    add_premium_user,
    error_handler,
    get_api_response,
    update_announcement_command,
    add_message
)
from utils import (
    get_inactive_users,
    update_inactivity_timestamp,
    remove_inactivity_record
)
from logging_config import logger

from random import randint

from metric import start_metrics, give_metrics, metrics_callback_handler, remind_incomplete_survey_cmd

async def job_check_inactive_users(context: CallbackContext):
    """
    Периодическая задача для проверки неактивных пользователей и отправки им «пробуждающих» сообщений.
    """
    inactive_users = get_inactive_users(hours=randint(120, 168))
    if not inactive_users:
        return

    batch_size = 15
    for i in range(0, len(inactive_users), batch_size):
        batch = inactive_users[i:i + batch_size]
        
        for user_id in batch:
            try:
                # Сначала проверяем доступность пользователя:
                await context.bot.get_chat(user_id)

                prompt = [{
                    "role": "system",
                    "content": "Пользователь не писал тебе несколько дней, "
                               "попробуй сам начать разговор от первого лица. "
                               "И закончи свое сообщение добрыми пожеланиями данному пользователю."
                }]

                bot_text = await get_api_response(
                    user_id=user_id,
                    prompt=prompt,
                )

                await add_message(user_id, "assistant", [bot_text])

                await context.bot.send_message(chat_id=user_id, text=bot_text)
                
                update_inactivity_timestamp(user_id)

            except Forbidden as e:
                logger.info(f"Пользователь {user_id} заблокировал бота. Пропускаем...")
                remove_inactivity_record(user_id)
            except BadRequest as e:
                logger.info(f"Не удалось связаться с пользователем {user_id}: {e}")
            except Exception as e:
                logger.error(f"Не удалось отправить «пробуждающее» сообщение пользователю {user_id}: {e}")

        if i + batch_size < len(inactive_users):
            await asyncio.sleep(60)

async def main():
    if not TOKEN:
        logger.error("Токен бота не установлен. Проверьте файл .env")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_premium", add_premium_user))
    application.add_handler(CommandHandler("update_announcement", update_announcement_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    application.add_handler(CommandHandler("remind_incomplete_survey", remind_incomplete_survey_cmd))
    application.add_handler(CommandHandler("start_metrics", start_metrics))
    application.add_handler(CommandHandler("give_metrics", give_metrics))
    application.add_handler(CallbackQueryHandler(metrics_callback_handler, pattern=r"^metrics\|"))

    # Планировщик задач (JobQueue)
    job_queue = application.job_queue
    job_queue.run_repeating(
        callback=job_check_inactive_users,
        interval=3600,  # Проверяем каждые 60 минут
        first=30        # Запускаем через 30 секунд после старта бота
    )

    logger.info("Запуск бота...")
    await application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    asyncio.run(main())