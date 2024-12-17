# bot/handlers.py
import asyncio
import httpx
import json
import nest_asyncio
import os
import random
import textwrap
import time
from datetime import datetime, timedelta
from itertools import cycle
from typing import Any, Dict, List

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
)
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters
)

from logging_config import logger

from config import (
    ADMIN_USER_ID, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_GATEWAY_ID,
    FEEDBACK_FILE, GROQ_API_KEYS, MAX_CHAR_LIMIT,
    SUMMARIZATION_PROMPT, SYSTEM_PROMPT, MANAGER_USER_ID
)
from utils import (
    archive_user_history, hash_data, load_user_history,
    log_message, save_user_history, save_user_info,
    load_premium_users, save_premium_users,
    set_user_gender, get_user_gender
)

# import database

nest_asyncio.apply()

api_key_cycle = cycle(zip(GROQ_API_KEYS, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_GATEWAY_ID))

# Состояния пользователя
user_states: Dict[int, str] = {}  # user_id: state
# Возможные состояния:
# None или отсутствует в словаре - обычный режим
# "waiting_for_feedback" - ждем отзыв

PREMIUM_USERS = load_premium_users()

async def simulate_typing(context, chat_id):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(random.randint(1, 3))

async def summarize_conversation(user_id: int, history: List[Dict[str, str]]) -> str:
    """
    Суммаризирует историю разговора пользователя, отправляя запрос в Groq API.

    :param user_id: ID пользователя.
    :param history: Список сообщений в формате [{"role": "user", "content": "..."}, ...].
    :return: Суммаризированный текст или сообщение об ошибке.
    """
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    try:
        current_key, current_account_id, current_gateway_id = next(api_key_cycle)
        
        base_url = f"https://gateway.ai.cloudflare.com/v1/{current_account_id}/{current_gateway_id}/groq"
        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json"
        }

        data = {
            "messages": [
                {"role": "user", "content": SUMMARIZATION_PROMPT},
                {"role": "system", "content": history_text},
                {"role": "user", "content": 'Пожалуйста, начните пересказ согласно вышеописанным инструкциям.'},
            ],
            # "model": "llama3-8b-8192",
            "model" : "llama-3.3-70b-versatile",
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

async def add_message(user_id: int, role: str, content: List[str]) -> bool:
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

        new_history = [{"role": "system", "content": SYSTEM_PROMPT}]
        gender = get_user_gender(user_id)
        if gender and gender not in ["Не хочу указывать"]:
            new_history.append({"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
        new_history.append({"role": "system", "content": "Вот краткое описание предыдущего диалога: " + summarized_content})
        
        save_user_history(user_id, new_history)
        logger.info(f"Суммаризация для пользователя {user_id} выполнена и история сброшена.")

        if user_id not in PREMIUM_USERS:
            if user_id not in user_states:
                user_states[user_id] = {}
            user_states[user_id]["last_summary"] = datetime.now()
        return True
    return False

async def get_groq_response(user_id: int, prompt_ru: str, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None) -> str:
    """
    Отправляет сообщение в Groq API и получает ответ.

    :param user_id: ID пользователя.
    :param prompt_ru: Текст сообщения пользователя.
    :return: Ответ от бота или сообщение об ошибке.
    """
    summarization_happened = await add_message(user_id, "user", [prompt_ru])
    try:
        current_key, current_account_id, current_gateway_id = next(api_key_cycle)

        base_url = f"https://gateway.ai.cloudflare.com/v1/{current_account_id}/{current_gateway_id}/groq"
        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json"
        }

        # similar_messages = database.db_get_similar(user_id, prompt_ru)
        history = load_user_history(user_id)
        # for message in similar_messages:
            # history.append({"role": "user", "content": message})

        data = {
            "messages": history,
            # "model": "llama3-8b-8192",
            "model" : "llama-3.3-70b-versatile",
            "temperature": 1,
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

        if summarization_happened and user_id not in PREMIUM_USERS and update is not None:
            await update.message.reply_text(
                "Ваш дневной лимит общения с FEELIX исчерпан.\nВы сможете продолжить общение через 24 часа.\n\n"
                "Для безлимитного общения оформите Premium подписку.",
                reply_markup=get_main_menu(user_id)
            )

        return bot_reply

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
        [KeyboardButton("Premium подписка")],
        [KeyboardButton("Оставить отзыв")],
        [KeyboardButton("Очистить историю")]
    ]
    if user_id in ADMIN_USER_ID:
        buttons.append([KeyboardButton("Получить отзывы")])

    if user_id == MANAGER_USER_ID:
        buttons.append([KeyboardButton("Добавить Premium пользователя")])

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает команду /start. Приветствует пользователя, объясняет принципы работы и предлагает
    выбрать пол для настройки общения.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name or "unknown_user"
    save_user_info(user_id, username)

    message = (
        "Привет! Я FEELIX – ваш душевный собеседник, готовый поддержать в любую минуту! ✨\n\n"
        "Я все еще нахожусь на стадии активной разработки, поэтому мои ответы могут быть неидеальными. Спасибо за понимание!\n\n"
        "Продолжая, вы соглашаетесь с "
        "[правилами](https://drive.google.com/file/d/1DGNBSyhqGxPDWLsHVvze3FJFmK08BLUq/view?usp=sharing) и "
        "[политикой](https://drive.google.com/file/d/1Pyec6cq_OCHFngho8CK5QFfq2PsEjwl5/view?usp=sharing)."
    )
    await update.message.reply_text(message, parse_mode="Markdown")

#     message = r"""
# ✨ *Наши принципы* ✨

# 1️⃣ **Полная анонимность и безопасность** 🔒  
# Мы обеспечиваем полную конфиденциальность общения:  
# \- 🔐 Все данные *шифруются* для защиты чатов пользователей\.  
# \- 🚫 Разработчики и никто более не могут установить автора тех или иных сообщений\.

# 2️⃣ **Доступность 24/7** ⏰  
# FEELIX всегда рядом:  
# \- 🤝 FEELIX всегда рядом — вы можете обратиться в *любое время суток*, и наш бот вас поддержит\.

# 3️⃣ **Эмпатия и человечность** ❤️  
# Мы создаем чат\-бота, который:  
# \- 😊 *Понимает ваши эмоции*\;  
# \- 🤗 *Поддерживает вас*\;  
# \- 🫂 Общается так, как это сделал бы *настоящий друг*\.
# """

    # await update.message.reply_text(message, parse_mode="MarkdownV2")

    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id]["choosing_gender"] = True

    await ask_user_gender(update, context)
    log_message(user_id, "user", "/start")
    log_message(user_id, "assistant", message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает команду /help. Предоставляет пользователю список доступных действий.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id

    if user_states.get(user_id, {}).get("choosing_gender", False):
        await ask_user_gender(update, context)
        return

    message = (
        "Доступные действия:\n"
        "1) Premium подписка\n"
        "2) Оставить отзыв\n"
        "3) Сбросить историю\n"
    )

    await update.message.reply_text(message, reply_markup=get_main_menu(user_id))

    log_message(user_id, "user", "/help")
    log_message(user_id, "assistant", message)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает входящий текст от пользователя, включая команды, отзывы и текстовые сообщения.
    Управляет состояниями пользователя и вызывает соответствующие функции.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    user_message = update.message.text.strip()
    save_user_info(user_id, username)

    if user_states.get(user_id, {}).get("choosing_gender", False):
        if user_message in ["Мужской", "Женский", "Не хочу указывать"]:
            await handle_gender_choice_inner(update, context, user_message)
            return
        else:
            await ask_user_gender(update, context)
            return

    if user_states.get(user_id, {}).get("waiting_for_feedback"):
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
        user_states[user_id]["waiting_for_feedback"] = False
        return
    
    if user_message == "Premium подписка":
        await handle_premium_subscription(update, context)
        return
    
    if user_message == "Добавить Premium пользователя" and user_id == MANAGER_USER_ID:
        response = (
            "Введите ID пользователя, которого вы хотите добавить в Premium:\n\n"
            "Пример: /add_premium 12345678"
        )
        await update.message.reply_text(response)
        return

    if user_message == "Оставить отзыв":
        response = "Напишите ваш отзыв одним сообщением:"
        if user_id not in user_states:
            user_states[user_id] = {}
        user_states[user_id]["waiting_for_feedback"] = True
        await update.message.reply_text(response)
        log_message(user_id, "user", user_message)
        log_message(user_id, "assistant", response)
        return

    if user_message == "Очистить историю":
        archive_user_history(user_id)
        response = "История сброшена."
        await update.message.reply_text(response, reply_markup=get_main_menu(user_id))

        log_message(user_id, "user", user_message)
        log_message(user_id, "assistant", response)

        if user_id in user_states and "last_summary" in user_states[user_id]:
            del user_states[user_id]["last_summary"]

        return

    if user_message == "Получить отзывы":
        if user_id in ADMIN_USER_ID:
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

    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")
    log_message(user_id, "user", user_message)

    try:
        await simulate_typing(context, update.effective_chat.id)
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

async def ask_user_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Запрашивает у пользователя его пол для настройки общения.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    buttons = [
        [KeyboardButton("Мужской"), KeyboardButton("Женский"), KeyboardButton("Не хочу указывать")],
    ]
    message = "Укажите ваш пол, чтобы я мог лучше настроиться на общение:"
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))

async def handle_gender_choice_inner(update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str) -> None:
    """
    Обрабатывает выбор пользователя о его поле и настраивает общение.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    :param choice: Выбор пользователя ('Мужской', 'Женский', 'Не хочу указывать').
    """
    global SYSTEM_PROMPT
    user_id = update.effective_user.id

    set_user_gender(user_id, choice)

    if choice in ["Мужской", "Женский"]:
        response = f"Спасибо! Я учту, что вы выбрали {choice.lower()} пол."
    else:
        response = "Спасибо! Продолжаем."

    user_states[user_id]["choosing_gender"] = False
    await update.message.reply_text(response, reply_markup=get_main_menu(user_id))

async def handle_premium_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает запрос пользователя на информацию о Premium подписке.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id

    if user_id in PREMIUM_USERS:
        end_date = PREMIUM_USERS[user_id]
        if datetime.now() > end_date:
            del PREMIUM_USERS[user_id]
            save_premium_users(PREMIUM_USERS)
            response = (
                "Ваша Premium подписка закончилась.\n\n"
                "Premium подписка длится 1 месяц и стоит 99 рублей.\n"
                "Вы получаете безлимитный доступ к общению с FEELIX.\n\n"
                "Для оформления свяжитесь с менеджером: @feelix_manager"
            )
        else:
            time_left = end_date - datetime.now()
            response = (
                f"Вы Premium пользователь.\nПодписка действует до {end_date.strftime('%d.%m.%Y %H:%M')}.\n"
                f"Осталось: {time_left.days} дн. и {time_left.seconds // 3600} ч."
            )
    else:
        response = (
            "Premium подписка длится 1 месяц и стоит 99 рублей.\n"
            "Вы получаете безлимитный доступ к общению с FEELIX.\n\n"
            "Для оформления свяжитесь с менеджером: @feelix_manager"
        )
    await update.message.reply_text(response)

async def add_premium_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Добавляет Premium подписку пользователю (только для менеджера).

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    if user_id != MANAGER_USER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        target_user_id = int(context.args[0])
        end_date = datetime.now() + timedelta(days=30)
        PREMIUM_USERS[target_user_id] = end_date
        end_date = PREMIUM_USERS[target_user_id]
        save_premium_users(PREMIUM_USERS)
        response = (
            f"Пользователь {target_user_id} добавлен как Premium. Подписка действует до {end_date.strftime('%d.%m.%Y %H:%M')}."
        )
        await update.message.reply_text(response)
        try:
            await context.bot.send_message(target_user_id, f"Поздравляем!\nВы стали Premium пользователем FEELIXs!\n\nПодписка действует до {end_date.strftime('%d.%m.%Y %H:%M')}.")
        except Exception:
            logger.warning("Не удалось отправить сообщение пользователю о премиуме.")
    except (IndexError, ValueError):
        response = "Пожалуйста, укажите корректный USER_ID."
        await update.message.reply_text(response)

async def handle_text_with_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает текстовые сообщения от пользователя с учётом лимита сообщений для обычных пользователей.
    Если лимит превышен, предлагает оформить Premium подписку.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id

    if user_states.get(user_id, {}).get("choosing_gender", False):
        user_message = update.message.text.strip()
        if user_message in ["Мужской", "Женский", "Не хочу указывать"]:
            await handle_gender_choice_inner(update, context, user_message)
        else:
            await ask_user_gender(update, context)
        return

    if user_id in PREMIUM_USERS:
        end_date = PREMIUM_USERS[user_id]
        if datetime.now() > end_date:
            del PREMIUM_USERS[user_id]
            save_premium_users(PREMIUM_USERS)

    if user_id in PREMIUM_USERS:
        await handle_text(update, context)
    else:
        last_summary = user_states.get(user_id, {}).get("last_summary", None)
        if last_summary:
            diff = datetime.now() - last_summary
            if diff.total_seconds() < 86400:  # 24 часа не прошло
                remaining = timedelta(seconds=(86400 - diff.total_seconds()))
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                response = (
                    f"Ваш лимит на сегодня исчерпан.\nВы сможете продолжить общение через {hours} ч. и {minutes} мин.\n"
                    "Для безлимитного общения оформите Premium подписку."
                )
                await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
                return
            else:
                if user_id not in user_states:
                    user_states[user_id] = {}

                if "last_summary" in user_states[user_id]:
                    del user_states[user_id]["last_summary"]

                await handle_text(update, context)
        else:
            await handle_text(update, context)