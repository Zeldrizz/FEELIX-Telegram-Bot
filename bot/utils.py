# bot/utils.py
import hashlib
import os
import time
from config import LOG_DIR
from logging_config import logger

def hash_data(data, algorithm='sha256'):
    """
    Хэширует данные с использованием указанного алгоритма.
    
    :param data: Данные для хэширования
    :param algorithm: Алгоритм хэширования (по умолчанию 'sha256')
    :return: Хэшированная строка
    """
    return hashlib.new(algorithm, str(data).encode('utf-8')).hexdigest()

def log_message(user_id, role, message):
    """
    Логирует сообщение пользователя или бота.
    
    :param user_id: ID пользователя
    :param role: Роль отправителя ('user' или 'assistant')
    :param message: Текст сообщения
    """
    user_log_dir = os.path.join(LOG_DIR, f"user_{hash_data(user_id)}")
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    user_log_file = os.path.join(user_log_dir, 'conversation_history.txt')

    if not os.path.exists(user_log_file):
        with open(user_log_file, 'w', encoding='utf-8') as f:
            f.write(f'--- Начало истории чата с {hash_data(user_id)} ---\n')

    with open(user_log_file, 'a', encoding='utf-8') as f:
        timestamp = time.strftime("%d/%m/%y %H:%M", time.localtime())
        f.write(f"{role.upper()} [{hash_data(user_id)}], [{timestamp}]: {message}\n")
