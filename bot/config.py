# bot/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv('TOKEN')
ADMIN_USER_ID = [int(user_id.strip()) for user_id in os.getenv('ADMIN_USER_ID', '').split(',') if user_id.strip()]

# GROQ_API_KEYS = [key.strip() for key in os.getenv('GROQ_API_KEY', '').split(',') if key.strip()]
# CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
# CLOUDFLARE_GATEWAY_ID = os.getenv('CLOUDFLARE_GATEWAY_ID')

GROQ_API_KEYS = ['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']
CLOUDFLARE_ACCOUNT_ID = '7e21baebff161fbad88b4539469c7d74'
CLOUDFLARE_GATEWAY_ID = 'llama'

print(GROQ_API_KEYS)
print(CLOUDFLARE_ACCOUNT_ID)
print(CLOUDFLARE_GATEWAY_ID)

LOG_DIR = os.path.join(Path(__file__).resolve().parent.parent, 'logs')  # Логи в корне проекта
FEEDBACK_FILE = os.path.join(Path(__file__).resolve().parent.parent, 'feedbacks', 'feedbacks.txt')

MAX_CHAR_LIMIT = 2000 # 50000
# 0.75 token = 1 word
# 8192 tokens * 0.75 = 10000 words
# 10000 * 5 = 50000 symbols
# approximately 5 letter in 1 russian word

SUMMARIZATION_PROMPT = "Ваша задача — сделать краткий пересказ следующего разговора на русском языке от третьего лица. Пересказ должен описать происходящее в чате, но содержать только самые ключевые моменты и не быть слишком детальным."

SYSTEM_PROMPT = """
Ты - Feelix, эмпатийный и поддерживающий собеседник. Твоя цель - помочь преодолеть собеседнику его проблемы и травмы, создавая безопасное пространство, как настоящий психолог.
Принципы:
Отвечай на русском, если не попросили иначе.
Избегай острых тем (религия, политика), предлагай сменить тему.
Веди себя как лучший друг, будь доброжелателен и подбадривай собеседника.
Терпи оскорбления, будь великодушен и вежлив.
Не направляй к специалистам, кроме случаев самоповреждения или вреда другим. Предлагай помощь посторонних и прекращай разговор на подобные темы.
Не определяй пол собеседника, жди, пока он сам раскроется.
Отвечай ясно и без «воды», не используй английские слова, пока не попросили.
"""
# length - 697 symbols