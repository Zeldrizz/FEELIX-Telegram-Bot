# bot/utils.py
import hashlib
import os
import time
import json
from pathlib import Path
from typing import Any, List, Dict
from config import LOG_DIR, SYSTEM_PROMPT
from logging_config import logger

def hash_data(data: Any, algorithm: str = 'sha256') -> str:
    """
    Хэширует данные с использованием указанного алгоритма.
    """
    return hashlib.new(algorithm, str(data).encode('utf-8')).hexdigest()

def get_user_history_path(user_id: int) -> str:
    """
    Возвращает путь к файлу истории диалога пользователя.
    """
    user_hash = hash_data(user_id)
    user_log_dir = os.path.join(LOG_DIR, f"user_{user_hash}")
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)
    return os.path.join(user_log_dir, 'conversation_history.json')

def load_user_history(user_id: int) -> List[Dict[str, str]]:
    """
    Загружает историю диалога пользователя из локального файла.
    """
    path = get_user_history_path(user_id)
    if not os.path.exists(path):
        # Инициализируем историю с system промптом
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_user_history(user_id, history)
        return history
    else:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

def save_user_history(user_id: int, history: List[Dict[str, str]]) -> None:
    """
    Сохраняет историю диалога пользователя в локальный файл.
    """
    path = get_user_history_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def archive_user_history(user_id: int) -> None:
    """
    Архивирует текущую историю диалога пользователя.
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
    save_user_history(user_id, [{"role": "system", "content": SYSTEM_PROMPT}])

def log_message(user_id: int, role: str, message: str) -> None:
    """
    Логирует сообщение пользователя или бота в файл журнала.
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
    Сохраняет информацию о пользователе в файл save/users.json, если такой записи ещё нет.
    Записывает: user_id, username, hash(user_id).
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

    user_hash = hash_data(user_id)
    new_user = {
        "user_id": user_id,
        "username": username,
        "hash": user_hash
    }
    users_data.append(new_user)
    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)