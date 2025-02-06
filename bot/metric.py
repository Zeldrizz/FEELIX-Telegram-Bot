import os
import json
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
METRICS_DIR = os.path.join(BASE_DIR, 'metrics')
if not os.path.exists(METRICS_DIR):
    os.makedirs(METRICS_DIR)

# Файл для хранения текущих опросов для метрики1: словарь { metric_name: survey_id }
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

    :param metric_name: Название метрики (например, "metric1" или "metric2").
    :return: Путь к файлу метрики (например, "metrics/metric1.json").
    """
    return os.path.join(METRICS_DIR, f"{metric_name}.json")


def load_metrics(metric_name: str):
    """
    Загружает данные метрики из файла. Для metric1 возвращается словарь,
    для metric2 – список результатов. Если файл не существует, возвращается пустой контейнер.

    :param metric_name: Название метрики.
    :return: Данные метрики.
    """
    filepath = get_metrics_filepath(metric_name)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {} if metric_name.lower() == "metric1" else []


def save_metrics(metric_name: str, data) -> None:
    """
    Сохраняет данные метрики в файл.

    :param metric_name: Название метрики.
    :param data: Данные метрики.
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
    Проверяет все ранее запущенные опросы для данной метрики (метрика1)
    и удаляет запись пользователя, если опрос не завершён (не все вопросы отвечены).
    Обновленные данные сохраняются в JSON-файл.

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
        text = "⭐ Оцените FEELIX от 1 до 5 ⭐"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q1|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q2":
        text = "Оцените способность FEELIX поднимать ваше настроение 😊"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q2|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q3":
        text = "Оцените способность FEELIX улучшать эмоциональное состояние 💙"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(str(i), callback_data=f"metrics|{metric_name}|{survey_id}|q3|{i}")
            for i in range(1, 6)
        ]])
    elif question_number == "q4":
        text = "📝 Ваше мнение очень важно для нас! Хотите ли вы оставить отзыв? 📝"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Отправить 📨", callback_data=f"metrics|{metric_name}|{survey_id}|q4|отправить"),
            InlineKeyboardButton("Пропустить ⏭️", callback_data=f"metrics|{metric_name}|{survey_id}|q4|пропустил")
        ]])
    else:
        text = ""
        keyboard = None
    return text, keyboard


# Последовательность вопросов для metric1 (опрос): q1 -> q2 -> q3 -> q4.
QUESTION_ORDER = {
    "q1": "q2",
    "q2": "q3",
    "q3": "q4",
    "q4": None
}


async def compute_metric2(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    Проходит по всем папкам user_* в папке logs, загружает файлы conversation_history.json,
    выбирает все сообщения с role == "user", за исключением сообщений, равных заданной строке-исключению.
    Суммирует общее количество символов.
    
    Общее число пользователей определяется по записям в файле save/users.json.
    Число пользователей, которые не заблокировали бота, определяется по количеству записей в файле save/inactivity.json.
    Вычисляется средняя длина (total_symbols / total_users).

    :param context: Контекст приложения.
    :return: Словарь с результатами:
             {
                 "timestamp": <читаемое время>,
                 "total_symbols": <общее количество символов>,
                 "total_users": <число записей в users.json>,
                 "not_banned_users": <число пользователей, взятое из inactivity.json>,
                 "average_length": <средняя длина сообщения>
             }
    """
    EXCLUDED_TEXT = ("Пользователь не писал тебе несколько дней, "
                     "попробуй сам начать разговор от первого лица. "
                     "И закончи свое сообщение добрыми пожеланиями данному пользователю.")
    total_symbols = 0

    # Обрабатываем только папку logs
    logs_dir = os.path.join(BASE_DIR, "logs")
    if os.path.exists(logs_dir):
        for d in os.listdir(logs_dir):
            dir_path = os.path.join(logs_dir, d)
            if d.startswith("user_") and os.path.isdir(dir_path):
                conv_file = os.path.join(dir_path, "conversation_history.json")
                if os.path.exists(conv_file):
                    try:
                        with open(conv_file, 'r', encoding='utf-8') as f:
                            conv = json.load(f)
                        for msg in conv:
                            if msg.get("role") == "user" and msg.get("content") != EXCLUDED_TEXT:
                                total_symbols += len(msg.get("content", ""))
                    except Exception:
                        pass

    # Общее число пользователей – количество записей в save/users.json
    users_file = os.path.join(BASE_DIR, "save", "users.json")
    total_users = 0
    if os.path.exists(users_file):
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                user_list = json.load(f)
            total_users = len(user_list)
        except Exception:
            pass

    # Число пользователей, которые не заблокировали бота, берем из файла inactivity.json
    inactivity_file = os.path.join(BASE_DIR, "save", "inactivity.json")
    not_banned_users = 0
    if os.path.exists(inactivity_file):
        try:
            with open(inactivity_file, 'r', encoding='utf-8') as f:
                inactivity_data = json.load(f)
            not_banned_users = len(inactivity_data)
        except Exception:
            pass

    average_length = total_symbols / total_users if total_users > 0 else 0

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_symbols": total_symbols,
        "total_users": total_users,
        "not_banned_users": not_banned_users,
        "average_length": average_length
    }
    return result


async def start_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start_metrics для менеджера.

    Если параметр равен "metric2", производится вычисление метрики по разговорной истории.
    Иначе запускается опрос (метрика1).

    :param update: Объект Update от Telegram.
    :param context: Контекст приложения.
    """
    from config import MANAGER_USER_ID

    if update.effective_user.id != MANAGER_USER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите название метрики. Пример: /start_metrics metric1 или metric2")
        return

    metric_name = context.args[0].lower()

    if metric_name == "metric2":
        result = await compute_metric2(context)
        results = load_metrics("metric2")
        if not isinstance(results, list):
            results = []
        results.append(result)
        save_metrics("metric2", results)
        summary = (
            f"Metric2 is ready:\n"
            f"timestamp: {result['timestamp']}\n"
            f"total_symbols: {result['total_symbols']}\n"
            f"total_users: {result['total_users']}\n"
            f"not_banned_users: {result['not_banned_users']}\n"
            f"average_length: {result['average_length']:.2f}"
        )
        await update.message.reply_text(summary)
        return

    # Для metric1 (опрос)
    survey_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_surveys = load_current_surveys()
    current_surveys[metric_name] = survey_id
    save_current_surveys(current_surveys)

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

    for user_data in users:
        user_id = user_data.get("user_id")
        if not user_id:
            continue
        cancel_pending_surveys(metric_name, str(user_id))
        try:
            text, keyboard = get_question_and_keyboard("q1", metric_name, survey_id)
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
            await asyncio.sleep(0.1)
        except Exception:
            continue


async def metrics_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик callback-запросов от inline-кнопок для опроса (metric1).

    Callback data имеет формат:
      "metrics|<metric_name>|<survey_id>|<question>|<choice>"

    Функция сохраняет ответ пользователя в файле метрики, удаляет сообщение с кнопками и
    отправляет следующий вопрос, если он предусмотрен последовательностью. Если это q4 и выбран
    вариант "отправить", инициируется процесс оставления отзыва. Если опрос не является текущим,
    сообщение просто удаляется.

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

    current_surveys = load_current_surveys()
    current_survey_id = current_surveys.get(metric_name)
    if current_survey_id != survey_id:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    metrics_data = load_metrics(metric_name)
    if survey_id not in metrics_data:
        metrics_data[survey_id] = {}
    if str(user_id) not in metrics_data[survey_id]:
        metrics_data[survey_id][str(user_id)] = {}
    metrics_data[survey_id][str(user_id)][question] = choice
    save_metrics(metric_name, metrics_data)

    try:
        await query.message.delete()
    except Exception:
        pass

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
                await context.bot.send_message(chat_id=user_id, text="🌟 Спасибо за участие! 🌟")
            except Exception:
                pass


async def give_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /give_metrics для менеджера.

    Команда должна вызываться в формате:
      /give_metrics <metric_name>

    Файл с результатами опроса (или вычислений) по указанной метрике отправляется менеджеру.

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

    metric_name = context.args[0].lower()
    filepath = get_metrics_filepath(metric_name)
    if not os.path.exists(filepath):
        await update.message.reply_text(f"Файл метрики '{metric_name}' не найден.")
        return

    try:
        with open(filepath, 'rb') as f:
            await update.message.reply_document(document=f, filename=f"{metric_name}.json")
    except Exception:
        await update.message.reply_text("Произошла ошибка при отправке файла.")