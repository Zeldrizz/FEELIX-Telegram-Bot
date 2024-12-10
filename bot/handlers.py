# bot/handlers.py
import os
import time
import textwrap
from itertools import cycle
import httpx
from typing import Any, Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
# import database
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
from utils import (
    log_message, hash_data, load_user_history,
    save_user_history, archive_user_history, save_user_info
)
from logging_config import logger
import nest_asyncio
import json

nest_asyncio.apply()

api_key_cycle = cycle([key.strip() for key in GROQ_API_KEYS])

# Состояния пользователя
user_states: Dict[int, str] = {}  # user_id: state
# Возможные состояния:
# None или отсутствует в словаре - обычный режим
# "waiting_for_feedback" - ждем отзыв

async def summarize_conversation(user_id: int, history: List[Dict[str, str]]) -> str:
    """
    Суммаризирует историю разговора пользователя, отправляя запрос в Groq API.

    :param user_id: ID пользователя.
    :param history: Список сообщений в формате [{"role": "user", "content": "..."}, ...].
    :return: Суммаризированный текст или сообщение об ошибке.
    """
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    try:
        api_key = GROQ_API_KEYS[0]
        
        base_url = f"https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/groq"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "messages": [
                {"role": "user", "content": SUMMARIZATION_PROMPT},
                {"role": "system", "content": history_text},
                {"role": "user", "content": 'Пожалуйста, начните пересказ согласно вышеописанным инструкциям.'},
            ],
            "model": "llama3-8b-8192",
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

async def add_message(user_id: int, role: str, content: List[str]) -> None:
    """
    Добавляет сообщение в историю разговора пользователя и выполняет суммаризацию при необходимости.

    :param user_id: ID пользователя.
    :param role: Роль отправителя ('user', 'assistant', 'system').
    :param content: Список текстов сообщений.
    """
    history = load_user_history(user_id)
    for message in content:
        history.append({"role": role, "content": message})
    save_user_history(user_id, history)
    logger.debug(f"Добавлено сообщение: {role} - {content}")

    total_chars = sum(len(msg["content"]) for msg in history)
    logger.debug(f"Общее количество символов в истории: {total_chars}")

    if total_chars > MAX_CHAR_LIMIT:
        logger.info(f"Лимит символов ({MAX_CHAR_LIMIT}) превышен для пользователя {user_id}. Выполняется суммаризация.")
        summarized_content = await summarize_conversation(user_id, history)
        summarized_history = [{"role": "system", "content": SYSTEM_PROMPT + ' Вот краткое описание твоего собеседника: ' + summarized_content}]
        save_user_history(user_id, summarized_history)
        logger.info(f"Суммаризация для пользователя {user_id} выполнена и история сброшена.")

async def get_groq_response(user_id: int, prompt_ru: str) -> str:
    """
    Отправляет сообщение в Groq API и получает ответ.

    :param user_id: ID пользователя.
    :param prompt_ru: Текст сообщения пользователя.
    :return: Ответ от бота или сообщение об ошибке.
    """
    await add_message(user_id, "user", [prompt_ru])
    try:
        api_key = GROQ_API_KEYS[0]

        base_url = f"https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/groq"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        history = load_user_history(user_id)
        data = {
            "messages": history,
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
        await add_message(user_id, "assistant", [bot_reply])
        return bot_reply
    except httpx.HTTPStatusError as http_err:
        logger.error(f"HTTP ошибка при получении ответа от Groq API для пользователя {user_id}: {http_err}")
        return "Извините, произошла ошибка при обработке вашего запроса."
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении ответа от Groq API для пользователя {user_id}: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """
    Создаёт основное меню с кнопками для пользователя.

    :param user_id: ID пользователя.
    :return: Объект ReplyKeyboardMarkup с кнопками.
    """
    buttons = [
        [KeyboardButton("Оставить отзыв")],
        [KeyboardButton("Сбросить историю")]
    ]
    if user_id in ADMIN_USER_ID:
        buttons.append([KeyboardButton("Получить отзывы")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start. Приветствует пользователя и показывает главное меню.

    :param update: Объект Update.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name or "unknown_user"
    save_user_info(user_id, username)

    message = (
        "Привет! Я Feelix – ваш душевный собеседник, готовый поддержать в любую минуту! ✨\n\n"
        "Я все еще нахожусь на стадии активной разработки, поэтому мои ответы могут быть неидеальными. Спасибо за понимание и помощь в моем совершенствовании! 💡\n\n"
        "Продолжая, вы соглашаетесь с "
        "[правилами](https://drive.google.com/file/d/1jcEspFp9-vrwDtXPhsQq2ho-KA9LSmbl/view?usp=sharing) и "
        "[политикой](https://drive.google.com/file/d/1XLRiiLoLLTMSmHWyY9_L0oM4apQHmLDD/view?usp=sharing)."
    )
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_menu(user_id))
    log_message(user_id, "user", "/start")
    log_message(user_id, "assistant", message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /help. Предоставляет информацию о доступных действиях.

    :param update: Объект Update.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    message = (
        "Доступные действия через кнопки:\n"
        "1) Оставить отзыв\n"
        "2) Сбросить историю\n"
    )
    await update.message.reply_text(message, reply_markup=get_main_menu(user_id))
    log_message(user_id, "user", "/help")
    log_message(user_id, "assistant", message)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик всех текстовых сообщений. Обрабатывает команды через кнопки и обычные сообщения для LLM.

    :param update: Объект Update.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    user_message = update.message.text.strip()
    save_user_info(user_id, username)

    # Проверим состояние: если пользователь должен оставить отзыв
    if user_states.get(user_id) == "waiting_for_feedback":
        # Считаем текущее сообщение отзывом
        feedback_text = user_message
        feedback_dir = os.path.dirname(FEEDBACK_FILE)
        if not os.path.exists(feedback_dir):
            os.makedirs(feedback_dir)

        with open(FEEDBACK_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%d/%m/%y %H:%M', time.localtime())}] Пользователь {user_id} ({username}): {feedback_text}\n")

        response = "Спасибо за ваш отзыв!"
        await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
        log_message(user_id, "user", feedback_text)
        log_message(user_id, "assistant", response)
        user_states[user_id] = None
        return

    # Обработка кнопок "Оставить отзыв", "Сбросить историю", "Получить отзывы"
    if user_message == "Оставить отзыв":
        # Попросим пользователя написать отзыв отдельным сообщением
        response = "Напишите ваш отзыв одним сообщением:"
        user_states[user_id] = "waiting_for_feedback"
        await update.message.reply_text(response)
        log_message(user_id, "user", user_message)
        log_message(user_id, "assistant", response)
        return

    if user_message == "Сбросить историю":
        # Архивируем старую историю и создаем новую
        archive_user_history(user_id)
        response = "История сброшена."
        await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
        log_message(user_id, "user", user_message)
        log_message(user_id, "assistant", response)
        return

    if user_message == "Получить отзывы":
        if user_id in ADMIN_USER_ID:
            # Отправить файл с отзывами
            if not os.path.exists(FEEDBACK_FILE):
                response = "Отзывов пока нет."
                await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
                log_message(user_id, "user", user_message)
                log_message(user_id, "assistant", response)
                return
            try:
                with open(FEEDBACK_FILE, 'rb') as f:
                    await update.message.reply_document(document=f)
                response = "Файл с отзывами отправлен."
                log_message(user_id, "user", user_message)
                log_message(user_id, "assistant", response)
            except Exception as e:
                logger.error(f"Ошибка при отправке файла с отзывами: {e}")
                response = "Произошла ошибка при отправке файла."
                await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
                log_message(user_id, "user", user_message)
                log_message(user_id, "assistant", response)
        else:
            response = "У вас нет прав для выполнения этой команды."
            await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
            log_message(user_id, "user", user_message)
            log_message(user_id, "assistant", response)
        return

    # Если не одна из команд: это обычное сообщение для LLM
    # database.db_handle_messages(user_id, "user", [user_message])
    # print("top 3 most similar:", database.db_get_similar(user_id, user_message))

    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")
    log_message(user_id, "user", user_message)

    try:
        response = await get_groq_response(user_id, user_message)
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения от пользователя {user_id}: {e}")
        response = "Извините, произошла ошибка. Пожалуйста, попробуйте позже."

    logger.info(f"Ответ бота для пользователя {user_id}: {response}")
    log_message(user_id, "assistant", response)
    await update.message.reply_text(response, reply_markup=get_main_menu(user_id))

def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Глобальный обработчик ошибок. Логирует ошибки при обработке обновлений.

    :param update: Объект Update или None.
    :param context: Контекст приложения.
    """
    logger.error(msg="Exception while handling an update:", exc_info=context.error)