# bot/handlers.py
import os
import time
import textwrap
from itertools import cycle
import httpx
from telegram import Update
from telegram.ext import (
    ContextTypes
)
from config import (
    SYSTEM_PROMPT, 
    MAX_CHAR_LIMIT, 
    SUMMARIZATION_PROMPT, 
    GROQ_API_KEYS, 
    FEEDBACK_FILE, 
    ADMIN_USER_ID,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_GATEWAY_ID
)
from utils import log_message, hash_data
from logging_config import logger
import nest_asyncio

nest_asyncio.apply()

api_key_cycle = cycle([key.strip() for key in GROQ_API_KEYS])

conversation_histories = {}

async def summarize_conversation(user_id, history):
    """
    Суммаризирует историю разговора, отправляя запрос в Groq API.
    
    :param user_id: ID пользователя
    :param history: Список сообщений в формате [{"role": "user", "content": "..."}, ...]
    :return: Суммаризированный текст или сообщение об ошибке.
    """
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    try:
        # Выбираем следующий API-ключ из цикла
        # api_key = next(api_key_cycle)
        api_key = GROQ_API_KEYS[0]
        
        base_url = f"https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/groq"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "messages": [
                {"role": "user", "content": SUMMARIZATION_PROMPT},
                {"role": "system", "content": history_text}
            ],
            "model": "llama3-8b-8192",
            "max_tokens": 12000,
            "temperature": 0.5,
            "top_p": 1.0
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=data,
            )
            response.raise_for_status()
            result = response.json()

        summary = result['choices'][0]['message']['content']
        logger.info(f"Суммаризация для пользователя {user_id} выполнена успешно.")
        return summary
    except httpx.HTTPStatusError as http_err:
        logger.error(f"HTTP ошибка при суммаризации разговора для пользователя {user_id}: {http_err}")
        return "Суммаризация не удалась из-за ошибки сервера."
    except Exception as e:
        logger.error(f"Неизвестная ошибка при суммаризации разговора для пользователя {user_id}: {e}")
        return "Суммаризация не удалась из-за неизвестной ошибки."

async def add_message(user_id, role, content):
    """
    Добавляет сообщение в историю разговора пользователя и выполняет суммаризацию при необходимости.
    
    :param user_id: ID пользователя
    :param role: Роль отправителя ('user', 'assistant', 'system')
    :param content: Текст сообщения
    """
    if user_id not in conversation_histories:
        conversation_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = conversation_histories[user_id]

    if role not in ["user", "assistant", "system"]:
        raise ValueError("Invalid role. Must be 'user', 'assistant', or 'system'.")

    history.append({"role": role, "content": content})
    logger.debug(f"Добавлено сообщение: {role} - {content}")

    total_chars = sum(len(msg["content"]) for msg in history)
    print(total_chars)
    logger.debug(f"Общее количество символов в истории: {total_chars}")

    if total_chars > MAX_CHAR_LIMIT:
        logger.info(f"Лимит символов ({MAX_CHAR_LIMIT}) превышен для пользователя {user_id}. Выполняется суммаризация.")
        summarized_content = await summarize_conversation(user_id, history)
        print(textwrap.fill(summarized_content, width=80))
        conversation_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT + 'Вот краткое описание твоего собеседника, это очень важная информация: ' + summarized_content}]
        logger.info(f"Суммаризация для пользователя {user_id} выполнена и история сброшена.")

async def get_groq_response(user_id, prompt_ru):
    """
    Отправляет сообщение в Groq API и получает ответ.
    
    :param user_id: ID пользователя
    :param prompt_ru: Текст сообщения пользователя
    :return: Ответ от бота или сообщение об ошибке.
    """
    await add_message(user_id, "user", prompt_ru)
    try:
        # Выбираем следующий API-ключ из цикла
        # api_key = next(api_key_cycle)
        api_key = GROQ_API_KEYS[0]

        base_url = f"https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/groq"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "messages": conversation_histories[user_id],
            "model": "llama3-8b-8192",
            "temperature": 0.7,
            "top_p": 0.9
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=data,
            )
            response.raise_for_status()
            result = response.json()

        bot_reply = result['choices'][0]['message']['content']
        await add_message(user_id, "assistant", bot_reply)
        return bot_reply
    except httpx.HTTPStatusError as http_err:
        logger.error(f"HTTP ошибка при получении ответа от Groq API для пользователя {user_id}: {http_err}")
        return "Извините, произошла ошибка при обработке вашего запроса."
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении ответа от Groq API для пользователя {user_id}: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."

# Командные обработчики

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    message = (
        "Здравствуйте! Я Feelix, буду стараться быть для вас самым приятным и душевным собеседником!\n"
        "Я поддержу вас в любой момент времени!\n\n"
        "(P.S. После общения с ботом, пожалуйста оставьте свой отзыв через команду /feedback)"
    )
    await update.message.reply_text(message)

    log_message(user_id, "user", "/start")
    log_message(user_id, "assistant", message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /help.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    message = (
        "Доступные команды:\n"
        "/start - Перезапустить бота\n"
        "/help - Получить справку\n"
        "/refresh - Сбросить историю чата\n"
        "/feedback + ваш текст - оставить свой отзыв о боте\n"
        "/get_feedbacks - Получить все отзывы (только для администраторов)"
    )
    await update.message.reply_text(message)

    log_message(user_id, "user", "/help")
    log_message(user_id, "assistant", message)

async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /refresh. Сбрасывает историю чата.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    conversation_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    message = "История чата сброшена."
    await update.message.reply_text(message)

    log_message(user_id, "user", "/refresh")
    log_message(user_id, "assistant", message)

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /feedback. Сохраняет обратную связь пользователя.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    feedback_text = ' '.join(context.args)

    if not feedback_text:
        await update.message.reply_text("Пожалуйста, отправьте ваш отзыв после команды /feedback.\nНапример: /feedback Отличный бот!")
        log_message(user_id, "user", "/feedback без текста")
        return

    feedback_entry = f"[{time.strftime('%d/%m/%y %H:%M', time.localtime())}] Пользователь {user_id} ({username}): {feedback_text}\n"

    feedback_dir = os.path.dirname(FEEDBACK_FILE)
    if not os.path.exists(feedback_dir):
        os.makedirs(feedback_dir)

    with open(FEEDBACK_FILE, 'a', encoding='utf-8') as f:
        f.write(feedback_entry)

    response = "Спасибо за ваш отзыв!"
    await update.message.reply_text(response)

    log_message(user_id, "user", f"/feedback {feedback_text}")
    log_message(user_id, "assistant", response)

async def get_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /get_feedbacks. Отправляет файл с отзывами (только для администраторов).
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if user_id not in ADMIN_USER_ID:
        response = "У вас нет прав для выполнения этой команды."
        await update.message.reply_text(response)
        log_message(user_id, "user", "/get_feedbacks")
        log_message(user_id, "assistant", response)
        return

    if not os.path.exists(FEEDBACK_FILE):
        response = "Отзывов пока нет."
        await update.message.reply_text(response)
        log_message(user_id, "user", "/get_feedbacks")
        log_message(user_id, "assistant", response)
        return

    try:
        with open(FEEDBACK_FILE, 'rb') as f:
            await update.message.reply_document(document=f)
        response = "Файл с отзывами отправлен."
        log_message(user_id, "user", "/get_feedbacks")
        log_message(user_id, "assistant", response)
    except Exception as e:
        logger.error(f"Ошибка при отправке файла с отзывами: {e}")
        response = "Произошла ошибка при отправке файла."
        await update.message.reply_text(response)
        log_message(user_id, "user", "/get_feedbacks")
        log_message(user_id, "assistant", response)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик обычных сообщений. Отправляет запрос в Groq API и возвращает ответ.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    user_message = update.message.text
    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")

    log_message(user_id, "user", user_message)

    try:
        response = await get_groq_response(user_id, user_message)
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения от пользователя {user_id}: {e}")
        response = "Извините, произошла ошибка. Пожалуйста, попробуйте позже."

    logger.info(f"Ответ бота для пользователя {user_id}: {response}")
    log_message(user_id, "assistant", response)
    await update.message.reply_text(response)

def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Глобальный обработчик ошибок.
    """
    logger.error(msg="Exception while handling an update:", exc_info=context.error)