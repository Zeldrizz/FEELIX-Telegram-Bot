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
    ADMIN_USER_ID, FEEDBACK_FILE, MAX_CHAR_LIMIT, DAILY_LIMIT_CHARS,
    SUMMARIZATION_PROMPT, SYSTEM_PROMPT, MANAGER_USER_ID, OPENROUTE, PREMIUM_SUBSCRIPTION_PRICE
)
from utils import (
    archive_user_history, load_user_history,
    log_message, save_user_history, save_user_info,
    load_premium_users, save_premium_users,
    set_user_gender, get_user_gender,
    load_daily_limits, save_daily_limits,
    get_free_trial_status, set_free_trial_status,
    load_daily_usage, save_daily_usage, update_inactivity_timestamp
)

import database

nest_asyncio.apply()

# Состояния пользователя
user_states: Dict[int, Dict[str, Any]] = {}
# Возможные состояния:
# None или отсутствует в словаре - обычный режим
# "waiting_for_feedback" - ждем отзыв
### NEW FEATURE: Добавляем состояния для пробной подписки
# "choosing_free_trial" - пользователь нажал "Пробная подписка"
# "confirming_free_trial" - пользователь выбирает "Да, хочу" или "Вернуться обратно"

PREMIUM_USERS = load_premium_users()
DAILY_LIMITS = load_daily_limits()
MAIN_MENU_COMMANDS = ["Premium подписка", "Очистить историю", "Оставить отзыв", "Получить отзывы", "Добавить Premium пользователя", "Пробная подписка"]
DAILY_USAGE = load_daily_usage()
DAILY_LIMIT = DAILY_LIMIT_CHARS  # суточный лимит для бесплатных

async def simulate_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    """
    Имитирует процесс набора текста ботом, отображая статус "печатает" в чат.

    :param context: Контекст приложения.
    :param chat_id: Идентификатор чата.
    """
    # await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    # await asyncio.sleep(random.randint(1, 3))
    try:
        while not stop_event.is_set():
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass

async def summarize_conversation(user_id: int, history: List[Dict[str, str]]) -> str:
    """
    Суммаризирует историю разговора пользователя, отправляя запрос в OpenRoute API.

    :param user_id: ID пользователя.
    :param history: Список сообщений в формате [{"role": "user", "content": "..."}, ...].
    :return: Суммаризированный текст или сообщение об ошибке.
    """
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

    try:
        # Настройки для OpenRouter API
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTE}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "meta-llama/llama-3.3-70b-instruct",
            "messages": [
                {"role": "user", "content": SUMMARIZATION_PROMPT},
                {"role": "system", "content": history_text},
                {"role": "user", "content": 'Пожалуйста, начните пересказ согласно вышеописанным инструкциям.'},
            ],
            "temperature": 0.5,
            "top_p": 1.0,
            # "provider": {
                # "order": ["NovitaAI", "Hyperbolic"],
                # "allow_fallbacks": True - does not work. typescript feature
            # }
        }

        # Отправка запроса
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()  # Проверяем статус ответа
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
    Добавляет сообщение в историю разговора пользователя.
    Для бесплатных пользователей:
    - Если общее число символов превысило 10 000, делаем суммаризацию,
      сбрасываем историю и даем "бан" на 24 часа.
    Для всех пользователей:
    - Если общее число символов превысило MAX_CHAR_LIMIT (50 000), делаем суммаризацию.
    Возвращает True, если была выполнена суммаризация.
    """
    history = load_user_history(user_id)
    for message in content:
        history.append({"role": role, "content": message})
    save_user_history(user_id, history)
    logger.debug(f"Добавлено сообщение: {role} - {content}")

    total_chars = sum(len(msg["content"]) for msg in history)
    logger.debug(f"Общее количество символов в истории: {total_chars}")

    summarization_happened = False

    # Если пользователь не премиум и превысили 10 000 символов:
    if user_id not in PREMIUM_USERS and total_chars > DAILY_LIMIT_CHARS:
        logger.info(f"Превышен DAILY_LIMIT_CHARS для пользователя {user_id}. Суммаризация и установка дневного лимита...")
        summarized_content = await summarize_conversation(user_id, history)

        new_history = [{"role": "system", "content": SYSTEM_PROMPT}]
        gender = get_user_gender(user_id)
        if gender and gender not in ["Не хочу указывать"]:
            new_history.append({"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
        new_history.append({"role": "system", "content": "Вот краткое описание предыдущего диалога: " + summarized_content})

        save_user_history(user_id, new_history)
        logger.info(f"Суммаризация для пользователя {user_id} выполнена и история сброшена.")

        # Устанавливаем ежедневный лимит на 24 часа
        DAILY_LIMITS[user_id] = datetime.now()
        save_daily_limits(DAILY_LIMITS)

        summarization_happened = True
        return summarization_happened

    # Логика с MAX_CHAR_LIMIT остаётся для всех пользователей (аварийный случай):
    if total_chars > MAX_CHAR_LIMIT:
        logger.info(f"Превышен MAX_CHAR_LIMIT для пользователя {user_id}. Суммаризация...")
        summarized_content = await summarize_conversation(user_id, history)

        new_history = [{"role": "system", "content": SYSTEM_PROMPT}]
        gender = get_user_gender(user_id)
        if gender and gender not in ["Не хочу указывать"]:
            new_history.append({"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
        new_history.append({"role": "system", "content": "Вот краткое описание предыдущего диалога: " + summarized_content})

        save_user_history(user_id, new_history)
        logger.info(f"Суммаризация для пользователя {user_id} выполнена и история сброшена.")
        summarization_happened = True

    return summarization_happened

async def get_openroute_response(user_id: int, prompt_ru: str, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None) -> str:
    """
    Отправляет сообщение в OpenRouter API и получает ответ.

    :param user_id: ID пользователя.
    :param prompt_ru: Текст сообщения пользователя.
    :return: Ответ от бота или сообщение об ошибке.
    """
    summarization_happened = await add_message(user_id, "user", [prompt_ru])
    try:
        # Загрузка истории пользователя
        history = load_user_history(user_id)


        history.append({
            "role": "system",
            "content": "Также вот сообщения пользователя, самые близкие по смыслу к текущему сообщению. "
                    "Проверь, имеют ли они отношение к обсуждаемой теме и если нужно учти их при ответе."
        })
        similar_messages = await database.db_get_similar(user_id, prompt_ru)
        for message in similar_messages:
            history.append({
                "role": "system",
                "content": f"Ранее пользователь писал: {message}"
            })

        # Настройки для OpenRouter API
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTE}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "meta-llama/llama-3.3-70b-instruct",
            "messages": history,
            "temperature": 1,
            "top_p": 0.9,
            # "provider": {
                # "order": ["NovitaAI", "Hyperbolic"],
                # "allow_fallbacks": True - does not work. typescript feature
            # }
        }

        # Отправка запроса
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()  # Проверяем статус ответа
            result = response.json()

        # Получение ответа бота
        bot_reply = result["choices"][0]["message"]["content"]

        return bot_reply

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP ошибка при получении ответа от OpenRouter API для пользователя {user_id}: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении ответа от OpenRouter API для пользователя {user_id}: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """
    Создаёт основное меню с кнопками для пользователя.

    :param user_id: ID пользователя.
    :return: Объект ReplyKeyboardMarkup с кнопками.
    """
    buttons = []

    free_trial_used = get_free_trial_status(user_id)
    if not free_trial_used:
        buttons.append([KeyboardButton("Пробная подписка")])

    buttons.append([KeyboardButton("Premium подписка")])
    buttons.append([KeyboardButton("Оставить отзыв")])
    buttons.append([KeyboardButton("Очистить историю")])

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
        "Не забудьте подписаться на наш [канал](https://t.me/feelix_bot_channel)!\n\n"
        "Продолжая, вы соглашаетесь с "
        "[правилами](https://drive.google.com/file/d/1DGNBSyhqGxPDWLsHVvze3FJFmK08BLUq/view?usp=sharing) и "
        "[политикой](https://drive.google.com/file/d/1Pyec6cq_OCHFngho8CK5QFfq2PsEjwl5/view?usp=sharing)."
    )
    await update.message.reply_text(message, parse_mode="Markdown")

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
        "4) Пробная подписка (если еще не была использована)\n"
    )

    await update.message.reply_text(message, reply_markup=get_main_menu(user_id))

    log_message(user_id, "user", "/help")
    log_message(user_id, "assistant", message)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает входящие текстовые сообщения от пользователя.
    В зависимости от состояния пользователя и содержимого сообщения выполняет соответствующие действия.

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    username = update.effective_user.username or update.effective_user.full_name

    update_inactivity_timestamp(user_id)

    gender = get_user_gender(user_id)
    if not gender:
        # Пол не выбран => принуждаем выбирать
        if user_id not in user_states:
            user_states[user_id] = {}
        user_states[user_id]["choosing_gender"] = True
        
        await ask_user_gender(update, context)

    # 2) Если пользователь уже в состоянии выбора пола, 
    #    проверяем, не нажал ли он одну из кнопок «Мужской», «Женский» или «Не хочу указывать».
    if user_states.get(user_id, {}).get("choosing_gender", False):
        if user_message in ["Мужской", "Женский", "Не хочу указывать"]:
            await handle_gender_choice_inner(update, context, user_message)
            save_user_info(user_id, username)
            return
        else:
            # Просим повторно ввести
            await ask_user_gender(update, context)
            return
        
    if user_states.get(user_id, {}).get("choosing_free_trial", False):
        # Пользователь выбирает между "Да, хочу!" и "Вернуться обратно"
        if user_message == "Да, хочу!":
            # Даем премиум на месяц
            end_date = datetime.now() + timedelta(days=30)
            PREMIUM_USERS[user_id] = end_date
            save_premium_users(PREMIUM_USERS)
            # Отмечаем, что пользователь использовал пробную подписку
            set_free_trial_status(user_id, True)
            response = (
                "Отлично! Ваша пробная подписка активирована на 1 месяц!\n"
                f"Теперь вы Premium пользователь до {end_date.strftime('%d.%m.%Y %H:%M')}.\n"
                "Наслаждайтесь безлимитным доступом к FEELIX! 🚀"
            )
            user_states[user_id]["choosing_free_trial"] = False
            await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
            log_message(user_id, "user", user_message)
            log_message(user_id, "assistant", response)
            return
        elif user_message == "Вернуться обратно":
            response = "Хорошо, возвращаемся в главное меню."
            user_states[user_id]["choosing_free_trial"] = False
            await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
            log_message(user_id, "user", user_message)
            log_message(user_id, "assistant", response)
            return
        else:
            # Если введено что-то другое, просто повторим кнопки
            await present_free_trial_choice(update, context)
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

    if user_message in MAIN_MENU_COMMANDS:
        # Просто вызываем process_user_message без проверки лимита
        await process_user_message(user_id, user_message, update, context)
        return

    # Если премиум - никаких ограничений
    if user_id in PREMIUM_USERS:
        # Премиум пользователь общается без ограничений
        await process_user_message(user_id, user_message, update, context)
        return

    current_time = datetime.now()
    usage_info = DAILY_USAGE.get(str(user_id))
    if not usage_info:
        # Если данных нет, инициализируем
        usage_info = {
            "usage": 0,
            "reset_time": (current_time + timedelta(hours=24)).isoformat()
        }
        DAILY_USAGE[str(user_id)] = usage_info
        save_daily_usage(DAILY_USAGE)

    usage = usage_info["usage"]
    reset_time_str = usage_info["reset_time"]
    reset_time = datetime.fromisoformat(reset_time_str)

    # Если 24 часа уже прошли, сбросим лимит
    if current_time > reset_time:
        usage = 0
        reset_time = current_time + timedelta(hours=24)
        usage_info["usage"] = usage
        usage_info["reset_time"] = reset_time.isoformat()
        DAILY_USAGE[str(user_id)] = usage_info
        save_daily_usage(DAILY_USAGE)

    # 1) Сначала проверим сообщение пользователя
    msg_len = len(user_message)
    if usage + msg_len > DAILY_LIMIT:
        # Превышаем лимит даже без ответа бота
        diff = reset_time - current_time
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        response = (
            f"Ваш суточный лимит общения с FEELIX исчерпан :(\n"
            f"Сможете продолжить общение через {hours} ч. {minutes} мин.\n\n"
            "Для безлимитного общения оформите Premium подписку или используйте пробную подписку."
        )
        await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
        return

    # Если пока что проходим, то сперва прибавим сообщение пользователя:
    usage += msg_len
    usage_info["usage"] = usage
    DAILY_USAGE[str(user_id)] = usage_info
    save_daily_usage(DAILY_USAGE)

    # 2) Генерируем ответ бота
    bot_reply = await process_user_message(user_id, user_message, update, context)

    if bot_reply is not None:
        update_inactivity_timestamp(user_id)

    # 3) Прибавляем длину ответа к usage
    if bot_reply is not None:
        reply_len = len(bot_reply)
        usage += reply_len
        if usage > DAILY_LIMIT:
            # Если после ответа бота мы превысили суточный лимит —
            # пользователь просто уже не сможет отправить следующее сообщение
            # до reset_time. Сам ответ уже выдан.
            usage = DAILY_LIMIT  # "забиваем" usage в значение, не выходящее за пределы
        usage_info["usage"] = usage
        DAILY_USAGE[str(user_id)] = usage_info
        save_daily_usage(DAILY_USAGE)

async def process_user_message(user_id: int, user_message: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Обрабатывает команды главного меню или обычный текстовый ввод пользователя.

    :param user_id: Идентификатор пользователя.
    :param user_message: Текст сообщения пользователя.
    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    username = update.effective_user.username or update.effective_user.full_name
    save_user_info(user_id, username)

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
        await database.db_clear_user_history(user_id)
        response = "История сброшена."
        await update.message.reply_text(response, reply_markup=get_main_menu(user_id))

        log_message(user_id, "user", user_message)
        log_message(user_id, "assistant", response)

        if "daily_limit_time" in user_states.get(user_id, {}):
            del user_states[user_id]["daily_limit_time"]

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
    
    if user_message == "Пробная подписка":
        free_trial_used = get_free_trial_status(user_id)
        if free_trial_used or user_id in PREMIUM_USERS:
            # На случай, если пользователь уже стал премиум или использовал пробную.
            response = "Вы уже являетесь Premium пользователем FEELIX."
            await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
            return
        await present_free_trial_choice(update, context)
        return

    log_message(user_id, "user", user_message)
    chat_id = update.effective_chat.id

    # 2) Create an asyncio.Event to stop the typing loop when done
    stop_event = asyncio.Event()
    # 3) Start the typing loop in the background
    typing_task = context.application.create_task(
        simulate_typing(context, chat_id, stop_event)
    )

    await database.db_handle_messages(user_id, "user", [user_message])

    try:
        response = await get_openroute_response(user_id, user_message, update, context)
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        response = "Извините, произошла ошибка. Пожалуйста, попробуйте позже."
    finally:
        stop_event.set()
        await typing_task

    log_message(user_id, "assistant", response)
    await add_message(user_id, "assistant", [response])
    await update.message.reply_text(response, reply_markup=get_main_menu(user_id))
    return response

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
    user_id = update.effective_user.id

    set_user_gender(user_id, choice)

    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id]["choosing_gender"] = False

    if choice in ["Мужской", "Женский"]:
        response = f"Спасибо! Я учту, что вы выбрали {choice.lower()} пол."
    else:
        response = "Спасибо! Продолжаем."

    # Завершаем состояние выбора пола
    user_states[user_id]["choosing_gender"] = False

    # Ответ пользователю
    await update.message.reply_text(response, reply_markup=get_main_menu(user_id))

    bot_reply = await get_openroute_response(user_id, "Привет", update, context)
    await update.message.reply_text(bot_reply)

async def handle_premium_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает запрос пользователя на информацию о Premium подписке.
    Предоставляет информацию о текущем статусе подписки или инструкциях по её оформлению.

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
                f"✨ Premium подписка длится 1 месяц и стоит {PREMIUM_SUBSCRIPTION_PRICE} рублей.\n"
                "🚀 Безлимитный доступ к FEELIX!\n\n"
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
            f"✨ Premium подписка длится 1 месяц и стоит {PREMIUM_SUBSCRIPTION_PRICE} рублей.\n"
            "🚀 Безлимитный доступ к общению с FEELIX.\n"
            "💬 Нет ограничений в количестве сообщений!\n\n"
            "Для оформления свяжитесь с менеджером: @feelix_manager"
        )
    await update.message.reply_text(response)

async def add_premium_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает команду добавления пользователя в список Premium.
    Только менеджер может выполнять эту команду.

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
        save_premium_users(PREMIUM_USERS)
        response = (
            f"Пользователь {target_user_id} добавлен как Premium. Подписка действует до {end_date.strftime('%d.%m.%Y %H:%M')}."
        )
        await update.message.reply_text(response)
        try:
            premium_message = (
                "🎉 Поздравляем! Вы стали Premium пользователем FEELIX! 🎉\n\n"
                "Теперь вас ничто не ограничивает! 🚀\n"
                "Вы можете свободно общаться с FEELIX в любое время, без ограничений!\n\n"
                f"Подписка действует до {end_date.strftime('%d.%m.%Y %H:%M')}.\n"
            )
            await context.bot.send_message(target_user_id, premium_message)
        except Exception:
            logger.warning("Не удалось отправить сообщение пользователю о премиуме.")
    except (IndexError, ValueError):
        response = "Пожалуйста, укажите корректный USER_ID."
        await update.message.reply_text(response)

async def present_free_trial_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Отображает пользователю информацию о пробной подписке и предлагает выбор:
    "Да хочу" или "Вернуться обратно".

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    user_id = update.effective_user.id
    message = (
        "✨ Пробная подписка на 1 месяц!\n"
        "🚀 Вы сможете общаться без ограничений целый месяц!\n"
        "Это абсолютно бесплатно и предоставляется только один раз.\n\n"
        "Хотите попробовать?"
    )
    buttons = [
        [KeyboardButton("Да, хочу!"), KeyboardButton("Вернуться обратно")]
    ]
    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id]["choosing_free_trial"] = True
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))