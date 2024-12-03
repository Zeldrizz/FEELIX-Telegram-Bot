# bot/logging_config.py
import logging
import os
from config import LOG_DIR

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(os.path.join(LOG_DIR, 'bot.log'))
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)