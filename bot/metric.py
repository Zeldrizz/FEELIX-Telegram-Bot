import os
import json
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# Директория для хранения файлов метрик
METRICS_DIR = os.path.join(BASE_DIR, 'metrics')
if not os.path.exists(METRICS_DIR):
    os.makedirs(METRICS_DIR)

# Файл для хранения текущих опросов: словарь { metric_name: survey_id }
CURRENT_SURVEYS_FILE = os.path.join(METRICS_DIR, "current_surveys.json")


def load_current_surveys() -> dict:
    """
    Загружает текущие опросы для каждой метрики из файла.
    
    :return: Словарь вида { metric_name: survey_id }
    """
    if os.path.exists(CURRENT_SURVEYS_FILE):
        with open(CURRENT_SURVEYS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_current_surveys(current: dict) -> None:
    """
    Сохраняет текущие опросы для каждой метрики в файл.
    
    :param current: Словарь вида { metric_name: survey_id }
    """
    with open(CURRENT_SURVEYS_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


def get_metrics_filepath(metric_name: str) -> str:
    """
    Возвращает путь к файлу метрики для заданного названия.
    
    Файл будет сохранён в директории metrics, которая находится на одном уровне с save.
    
    :param metric_name: Название метрики (например, "metric1").
    :return: Путь к файлу метрики (например, "metrics/metric1.json").
    """
    return os.path.join(METRICS_DIR, f"{metric_name}.json")


def load_metrics(metric_name: str) -> dict:
    """
    Загружает данные метрики из файла. Если файл не существует, возвращает пустой словарь.
    
    :param metric_name: Название метрики.
    :return: Словарь с данными метрики.
    """
    filepath = get_metrics_filepath(metric_name)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_metrics(metric_name: str, data: dict) -> None:
    """
    Сохраняет данные метрики в файл.
    
    :param metric_name: Название метрики.
    :param data: Словарь с данными метрики.
    """
    filepath = get_metrics_filepath(metric_name)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_survey_complete(user_entry: dict) -> bool:
    """
    Проверяет, заполнены ли все вопросы опроса для пользователя.
    
    :param user_entry: Словарь с ответами пользователя.
    :return: True, если все вопросы (q1, q2, q3, q4) отвечены, иначе False.
    """
    required_questions = {"q1", "q2", "q3", "q4"}
    return required_questions.issubset(user_entry.keys())


def cancel_pending_surveys(metric_name: str, user_id: str) -> None:
    """
    Проверяет все ранее запущенные опросы для данной метрики и удаляет запись
    пользователя, если опрос не завершён (не все вопросы отвечены).
    Обновлённые данные сохраняются в JSON-файл.
    
    :param metric_name: Название метрики.
    :param user_id: Идентификатор пользователя в виде строки.
    """
    metrics_data = load_metrics(metric_name)
    changed = False
    for survey_id in list(metrics_data.keys()):
        if user_id in metrics_data[survey_id]:
            if not is_survey_complete(metrics_data[survey_id][user_id]):
                del metrics_data[survey_id][user_id]
                changed = True
    if changed:
        save_metrics(metric_name, metrics_data)


def get_question_and_keyboard(question_number: str, metric_name: str, survey_id: str):
    """
    Возвращает текст вопроса и объект InlineKeyboardMarkup с кнопками для заданного вопроса.
    
    Для первых трёх вопросов кнопки располагаются в одном ряду (5 кнопок),
    для четвертого – в одном ряду (2 кнопки).
    
    :param question_number: Идентификатор вопроса ("q1", "q2", "q3", "q4").
    :param metric_name: Название метрики.
    :param survey_id: Уникальный идентификатор текущего опроса.
    :return: Кортеж (текст вопроса, клавиатура с inline-кнопками).
    """
    if question_number == "q1":
        text = "⭐ Оцените FEELIX от 1 до 5:"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q1|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q2":
        text = "😊 Оцените способность бота поднимать ваше настроение:"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q2|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q3":
        text = "💙 Оцените способность бота улучшать эмоциональное состояние:"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q3|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q4":
        text = "📝 Ваше мнение очень важно для нас! Хотите ли вы оставить отзыв?"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📨 Отправить", callback_data=f"metrics|{metric_name}|{survey_id}|q4|отправить"),
            InlineKeyboardButton("⏭️ Пропустить", callback_data=f"metrics|{metric_name}|{survey_id}|q4|пропустил")
        ]])
    else:
        text = ""
        keyboard = None
    return text, keyboard


# Определение последовательности вопросов: q1 -> q2 -> q3 -> q4.
QUESTION_ORDER = {
    "q1": "q2",
    "q2": "q3",
    "q3": "q4",
    "q4": None
}


async def start_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start_metrics для менеджера.
    
    Команда должна вызываться в формате:
      /start_metrics <metric_name>
    
    После запуска метрики создаётся уникальный идентификатор опроса (survey_id) в читаемом виде,
    данные сохраняются в JSON-файл, и первичный вопрос (q1) с интерактивными кнопками отправляется
    всем пользователями, зарегистрированным в файле save/users.json. При этом текущий опрос для данной
    метрики обновляется, а предыдущий считается отменённым.
    
    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    from config import MANAGER_USER_ID

    if update.effective_user.id != MANAGER_USER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите название метрики. Пример: /start_metrics metric1")
        return

    metric_name = context.args[0]
    survey_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Обновляем текущий опрос для данной метрики
    current_surveys = load_current_surveys()
    current_surveys[metric_name] = survey_id
    save_current_surveys(current_surveys)

    # Создаем новую итерацию опроса
    metrics_data = load_metrics(metric_name)
    metrics_data[survey_id] = {}  # Здесь будут записываться ответы пользователей
    save_metrics(metric_name, metrics_data)

    await update.message.reply_text(f"Метрика '{metric_name}' запущена (survey_id={survey_id}).")

    users_file = os.path.join(BASE_DIR, 'save', 'users.json')
    if os.path.exists(users_file):
        with open(users_file, 'r', encoding='utf-8') as f:
            users = json.load(f)
    else:
        users = []

    # Для каждого пользователя отменяем незавершённые опросы и отправляем первый вопрос нового опроса
    for user_data in users:
        user_id = user_data.get("user_id")
        if not user_id:
            continue
        cancel_pending_surveys(metric_name, str(user_id))
        try:
            text, keyboard = get_question_and_keyboard("q1", metric_name, survey_id)
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
            await asyncio.sleep(0.1)  # небольшая задержка для соблюдения лимитов API Telegram
        except Exception:
            continue


async def metrics_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик callback-запросов от inline-кнопок в рамках опроса метрики.
    
    Callback data должна иметь формат:
      "metrics|<metric_name>|<survey_id>|<question>|<choice>"
    
    Функция сохраняет ответ пользователя в файле метрики, удаляет сообщение с кнопками и
    отправляет следующий вопрос, если он предусмотрен последовательностью. Если это вопрос q4
    и выбран вариант "отправить", инициируется процесс оставления отзыва.
    Если опрос не является текущим для данной метрики, сообщение с кнопками просто удаляется.
    
    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    parts = query.data.split("|")
    if len(parts) != 5:
        return

    _, metric_name, survey_id, question, choice = parts
    user_id = query.from_user.id

    # Проверяем, что этот survey соответствует текущему опросу для данной метрики
    current_surveys = load_current_surveys()
    current_survey_id = current_surveys.get(metric_name)
    if current_survey_id != survey_id:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Создаем запись пользователя, если её еще нет, и сохраняем ответ
    metrics_data = load_metrics(metric_name)

    if survey_id not in metrics_data:
        metrics_data[survey_id] = {}

    if str(user_id) not in metrics_data[survey_id]:
        metrics_data[survey_id][str(user_id)] = {}

    metrics_data[survey_id][str(user_id)][question] = choice
    save_metrics(metric_name, metrics_data)

    # Удаляем сообщение с кнопками
    try:
        await query.message.delete()
    except Exception:
        pass

    # Если это вопрос q4 и выбран вариант "отправить", инициируем процесс оставления отзыва
    if question == "q4" and choice == "отправить":
        try:
            from handlers import user_states
            if user_id not in user_states:
                user_states[user_id] = {}
            user_states[user_id]["waiting_for_feedback"] = True
        except Exception:
            pass
        try:
            await context.bot.send_message(chat_id=user_id, text="Напишите ваш отзыв одним сообщением:")
        except Exception:
            pass
    else:
        next_question = QUESTION_ORDER.get(question)
        if next_question:
            text, keyboard = get_question_and_keyboard(next_question, metric_name, survey_id)
            try:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
                await asyncio.sleep(0.1)
            except Exception:
                pass
        else:
            try:
                await context.bot.send_message(chat_id=user_id, text="Спасибо за участие!")
            except Exception:
                pass


async def give_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /give_metrics для менеджера.
    
    Команда должна вызываться в формате:
      /give_metrics <metric_name>
    
    Файл с результатами опроса по указанной метрике отправляется менеджеру.
    
    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    from config import MANAGER_USER_ID

    if update.effective_user.id != MANAGER_USER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите название метрики. Пример: /give_metrics metric1")
        return

    metric_name = context.args[0]
    filepath = get_metrics_filepath(metric_name)
    if not os.path.exists(filepath):
        await update.message.reply_text(f"Файл метрики '{metric_name}' не найден.")
        return

    try:
        with open(filepath, 'rb') as f:
            await update.message.reply_document(document=f, filename=f"{metric_name}.json")
    except Exception:
        await update.message.reply_text("Произошла ошибка при отправке файла.")