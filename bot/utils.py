# bot/utils.py
import hashlib
import os
import time
import json
from pathlib import Path
from typing import Any, List, Dict
from config import LOG_DIR, SYSTEM_PROMPT
from logging_config import logger
from datetime import datetime


def hash_data(data: Any, algorithm: str = 'sha256') -> str:
    """
    Возвращает хеш строки, полученной из данных, с использованием указанного алгоритма.

    :param data: Данные для хеширования.
    :param algorithm: Алгоритм хеширования (по умолчанию 'sha256').
    :return: Хеш-строка.
    """
    return hashlib.new(algorithm, str(data).encode('utf-8')).hexdigest()


def get_user_history_path(user_id: int) -> str:
    """
    Получает путь к файлу истории разговоров пользователя.

    Если директория для пользователя не существует, она создаётся.

    :param user_id: Идентификатор пользователя.
    :return: Путь к файлу 'conversation_history.json' для данного пользователя.
    """
    user_hash = hash_data(user_id)
    user_log_dir = os.path.join(LOG_DIR, f"user_{user_hash}")
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)
    return os.path.join(user_log_dir, 'conversation_history.json')


def load_user_history(user_id: int) -> List[Dict[str, str]]:
    """
    Загружает историю разговоров пользователя из файла.

    Если файл истории не существует, инициализирует историю с системным промптом и
    информацией о поле пользователя, если оно задано.

    Также проверяет наличие упоминания пола в истории и добавляет его при необходимости.

    :param user_id: Идентификатор пользователя.
    :return: Список сообщений в истории разговоров.
    """
    path = get_user_history_path(user_id)
    if not os.path.exists(path):
        # Инициализируем историю с system промптом
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Добавим информацию о поле, если оно есть
        gender = get_user_gender(user_id)
        if gender and gender not in ["Не хочу указывать"]:
            history.append({"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
        save_user_history(user_id, history)
        return history
    else:
        with open(path, 'r', encoding='utf-8') as f:
            history = json.load(f)
        # Проверим, есть ли в истории упоминание пола. Если нет, но пол выбран, добавим.
        # Проверяем, уже ли есть сообщение про пол (чтобы не дублировать)
        has_gender_message = any("Ваш собеседник - " in msg["content"] for msg in history if msg["role"] == "system")
        gender = get_user_gender(user_id)
        if gender and gender not in ["Не хочу указывать"] and not has_gender_message:
            # Вставляем сразу после первого system сообщения
            # Предполагается, что первое сообщение system это SYSTEM_PROMPT
            history.insert(1, {"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
            save_user_history(user_id, history)

        return history


def save_user_history(user_id: int, history: List[Dict[str, str]]) -> None:
    """
    Сохраняет историю разговоров пользователя в файл.

    :param user_id: Идентификатор пользователя.
    :param history: Список сообщений для сохранения.
    """
    path = get_user_history_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def archive_user_history(user_id: int) -> None:
    """
    Архивирует текущую историю разговоров пользователя, перемещая её в директорию архива,
    и инициализирует новую пустую историю с системным промптом и информацией о поле.

    :param user_id: Идентификатор пользователя.
    """
    user_hash = hash_data(user_id)
    user_log_dir = os.path.join(LOG_DIR, f"user_{user_hash}")
    if not os.path.exists(user_log_dir):
        return

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    archive_dir = os.path.join(save_dir, f"user_{user_hash}_{timestamp}")
    os.rename(user_log_dir, archive_dir)

    # Создаем новую пустую историю
    new_user_log_dir = os.path.join(LOG_DIR, f"user_{user_hash}")
    os.makedirs(new_user_log_dir)
    # При новой истории тоже учитываем пол, если он есть
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    gender = get_user_gender(user_id)
    if gender and gender not in ["Не хочу указывать"]:
        history.append({"role": "system", "content": f"Ваш собеседник - {gender.lower()}."})
    save_user_history(user_id, history)


def log_message(user_id: int, role: str, message: str) -> None:
    """
    Записывает сообщение пользователя или системы в лог-файл истории разговоров.

    Если файл истории не существует, создаёт его и добавляет начальную строку.

    :param user_id: Идентификатор пользователя.
    :param role: Роль отправителя сообщения ('user' или 'system').
    :param message: Текст сообщения.
    """
    user_log_dir = os.path.join(LOG_DIR, f"user_{hash_data(user_id)}")
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    user_log_file = os.path.join(user_log_dir, 'conversation_history.log')

    if not os.path.exists(user_log_file):
        with open(user_log_file, 'w', encoding='utf-8') as f:
            f.write(f'--- Начало истории чата с {hash_data(user_id)} ---\n')

    with open(user_log_file, 'a', encoding='utf-8') as f:
        timestamp = time.strftime("%d/%m/%y %H:%M", time.localtime())
        f.write(f"{role.upper()} [{hash_data(user_id)}], [{timestamp}]: {message}\n")


def save_user_info(user_id: int, username: str) -> None:
    """
    Сохраняет информацию о пользователе в файл 'users.json'.

    Если пользователь уже существует, не перезаписывает информацию.

    :param user_id: Идентификатор пользователя.
    :param username: Имя пользователя.
    """
    from config import TOKEN  # чтобы не было цикличного импорта

    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not save_dir.exists():
        save_dir.mkdir()

    users_file = save_dir / 'users.json'
    if users_file.exists():
        with open(users_file, 'r', encoding='utf-8') as f:
            users_data = json.load(f)
    else:
        users_data = []

    for user_data in users_data:
        if user_data["user_id"] == user_id:
            return

    new_user = {
        "user_id": user_id,
        "username": username,
        "gender": None,
        "free_trial_used": False
    }
    users_data.append(new_user)
    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)


def set_user_gender(user_id: int, gender: str) -> None:
    """
    Устанавливает пол пользователя и сохраняет его в файле 'users.json'.

    Если пользователь не найден, добавляет его с указанным полом и именем "unknown_user".

    :param user_id: Идентификатор пользователя.
    :param gender: Пол пользователя.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    users_file = save_dir / 'users.json'
    if users_file.exists():
        with open(users_file, 'r', encoding='utf-8') as f:
            users_data = json.load(f)
    else:
        users_data = []

    for user_data in users_data:
        if user_data["user_id"] == user_id:
            user_data["gender"] = gender
            break
    else:
        user_data = {
            "user_id": user_id,
            "username": "unknown_user",
            "gender": gender,
            "free_trial_used": False  # по умолчанию
        }
        users_data.append(user_data)

    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)


def get_user_gender(user_id: int) -> str:
    """
    Получает пол пользователя из файла 'users.json'.

    :param user_id: Идентификатор пользователя.
    :return: Строка с полом пользователя или None, если не задан.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    users_file = save_dir / 'users.json'
    if not users_file.exists():
        return None
    with open(users_file, 'r', encoding='utf-8') as f:
        users_data = json.load(f)

    for user_data in users_data:
        if user_data["user_id"] == user_id:
            return user_data.get("gender", None)
    return None


def save_premium_users(premium_users: Dict[int, datetime]) -> None:
    """
    Сохраняет информацию о премиум-пользователях в файл 'premium_users.json'.

    :param premium_users: Словарь с идентификаторами пользователей и датами окончания премиума.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not save_dir.exists():
        save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / 'premium_users.json'

    data = {str(uid): end_date.isoformat() for uid, end_date in premium_users.items()}
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_premium_users() -> Dict[int, datetime]:
    """
    Загружает информацию о премиум-пользователях из файла 'premium_users.json'.

    :return: Словарь с идентификаторами пользователей и датами окончания премиума.
    """
    from datetime import datetime
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    filepath = save_dir / 'premium_users.json'
    if not filepath.exists():
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    premium_users = {}
    for uid_str, iso_time in data.items():
        try:
            uid = int(uid_str)
            end_date = datetime.fromisoformat(iso_time)
            premium_users[uid] = end_date
        except Exception as e:
            logger.error(f"Ошибка при загрузке премиум-пользователя {uid_str}: {e}")
    return premium_users


def load_daily_limits() -> Dict[int, datetime]:
    """
    Загружает информацию о daily_limit_time для пользователей из файла 'daily_limits.json'.

    Формат файла: { "user_id_str": "iso_datetime_str", ... }

    :return: Словарь с идентификаторами пользователей и соответствующими datetime объектами.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    filepath = save_dir / 'daily_limits.json'
    if not filepath.exists():
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    daily_limits = {}
    for uid_str, iso_time in data.items():
        try:
            uid = int(uid_str)
            dt = datetime.fromisoformat(iso_time)
            daily_limits[uid] = dt
        except Exception as e:
            logger.error(f"Ошибка при загрузке daily_limit для пользователя {uid_str}: {e}")
    return daily_limits


def save_daily_limits(daily_limits: Dict[int, datetime]) -> None:
    """
    Сохраняет информацию о daily_limit_time для пользователей в файл 'daily_limits.json'.

    Формат: { "user_id_str": "iso_datetime_str", ... }

    :param daily_limits: Словарь с идентификаторами пользователей и соответствующими datetime объектами.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not save_dir.exists():
        save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / 'daily_limits.json'
    data = {str(uid): dt.isoformat() for uid, dt in daily_limits.items()}
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_free_trial_status(user_id: int) -> bool:
    """
    Получает статус использования бесплатной пробной подписки пользователем.

    :param user_id: Идентификатор пользователя.
    :return: True, если пользователь уже использовал бесплатную подписку, иначе False.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    users_file = save_dir / 'users.json'
    if not users_file.exists():
        return False
    with open(users_file, 'r', encoding='utf-8') as f:
        users_data = json.load(f)

    for user_data in users_data:
        if user_data["user_id"] == user_id:
            return user_data.get("free_trial_used", False)
    return False


def set_free_trial_status(user_id: int, status: bool) -> None:
    """
    Устанавливает статус использования бесплатной пробной подписки для пользователя.

    :param user_id: Идентификатор пользователя.
    :param status: True, если пользователь использовал пробную подписку, иначе False.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    users_file = save_dir / 'users.json'
    if users_file.exists():
        with open(users_file, 'r', encoding='utf-8') as f:
            users_data = json.load(f)
    else:
        users_data = [{
            "user_id": user_id,
            "username": "unknown_user",
            "gender": None,
            "free_trial_used": status
        }]
        with open(users_file, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        return

    for user_data in users_data:
        if user_data["user_id"] == user_id:
            user_data["free_trial_used"] = status
            break
    else:
        user_data = {
            "user_id": user_id,
            "username": "unknown_user",
            "gender": None,
            "free_trial_used": status
        }
        users_data.append(user_data)

    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def load_daily_usage() -> dict:
    """
    Загружает информацию о суточном использовании символов (как пользователем, так и ботом).
    Пример структуры:
    {
      "123456789": {
         "usage": 1200,
         "reset_time": "2025-01-05T12:00:00"
      },
      ...
    }
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    filepath = save_dir / 'daily_usage.json'
    if not filepath.exists():
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_daily_usage(daily_usage: dict) -> None:
    """
    Сохраняет структуру с расходом символов и временем сброса.
    """
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not save_dir.exists():
        save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / 'daily_usage.json'
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(daily_usage, f, ensure_ascii=False, indent=2)