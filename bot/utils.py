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
    return hashlib.new(algorithm, str(data).encode('utf-8')).hexdigest()

def get_user_history_path(user_id: int) -> str:
    user_hash = hash_data(user_id)
    user_log_dir = os.path.join(LOG_DIR, f"user_{user_hash}")
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)
    return os.path.join(user_log_dir, 'conversation_history.json')

def load_user_history(user_id: int) -> List[Dict[str, str]]:
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
    path = get_user_history_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def archive_user_history(user_id: int) -> None:
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

    # Если пользователь уже есть, не перезаписываем, просто выходим
    for user_data in users_data:
        if user_data["user_id"] == user_id:
            return

    new_user = {
        "user_id": user_id,
        "username": username,
        "gender": None  # по умолчанию неизвестен
    }
    users_data.append(new_user)
    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def set_user_gender(user_id: int, gender: str) -> None:
    # Записываем поле "gender" для пользователя
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
        # Если не нашли, добавим пользователя
        user_data = {
            "user_id": user_id,
            "username": "unknown_user",
            "gender": gender
        }
        users_data.append(user_data)

    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def get_user_gender(user_id: int) -> str:
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
    save_dir = Path(__file__).resolve().parent.parent / 'save'
    if not save_dir.exists():
        save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / 'premium_users.json'

    data = {str(uid): end_date.isoformat() for uid, end_date in premium_users.items()}
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_premium_users() -> Dict[int, datetime]:
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