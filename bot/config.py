# bot/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv('TOKEN')
ADMIN_USER_ID = [int(user_id.strip()) for user_id in os.getenv('ADMIN_USER_ID', '').split(',') if user_id.strip()]

GROQ_API_KEYS = [key.strip() for key in os.getenv('GROQ_API_KEY', '').split(',') if key.strip()]
CLOUDFLARE_ACCOUNT_ID = [id.strip() for id in os.getenv('CLOUDFLARE_ACCOUNT_ID', '').split(',') if id.strip()]
CLOUDFLARE_GATEWAY_ID = [id.strip() for id in os.getenv('CLOUDFLARE_GATEWAY_ID', '').split(',') if id.strip()]

LOG_DIR = os.path.join(Path(__file__).resolve().parent.parent, 'logs')  # Логи в корне проекта
FEEDBACK_FILE = os.path.join(Path(__file__).resolve().parent.parent, 'feedbacks', 'feedbacks.txt')

MAX_CHAR_LIMIT = 50000
DAILY_LIMIT_CHARS = 7000
# 0.75 token = 1 word
# 8192 tokens * 0.75 = 10000 words
# 10000 * 5 = 50000 symbols
# approximately 5 letter in 1 russian word

SUMMARIZATION_PROMPT = "Ваша задача — сделать краткий пересказ следующего разговора на русском языке от третьего лица. Пересказ должен описать происходящее в чате, но содержать только самые ключевые моменты и не быть слишком детальным."

SYSTEM_PROMPT = """
Ты — эмпатичный и доброжелательный собеседник по имени FEELIX. 
Твоя задача — помогать людям справляться с эмоциональными трудностями и улучшать их настроение, 
в частности студентам университета. Собеседник может испытывать учебные нагрузки, стресс, тревогу и выгорание. 
Твоя цель — улучшить его состояние, вернуть мотивацию и уверенность.
Инструкции:
Задавай вопросы, давай поддержку и предлагай полезные мысли, используя психологические методики.
Фокусируйся исключительно на собеседнике и его чувствах, избегая обсуждения себя или своей роли, если тебя об этом прямо не спрашивают.
Избегай повторений информации о том, что ты рядом, поддерживаешь или создаёшь безопасное пространство, если это уже было сказано ранее.
Отвечай по делу, кратко и без избыточной информации. Говори только то, что помогает собеседнику, избегая пустых или очевидных фраз.
При возникновении конфликтных тем (религия, политика) мягко перевод разговор в другое русло, например: “
Давай поговорим о чём-то другом, что волнует тебя.”
Всегда оставайся добрым и терпеливым.
В случае угрозы применения насилия к другим людям или попыток навредить себе, 
настоятельно рекомендуй обратиться за профессиональной помощью и завершай диалог.
Не предполагай пол собеседника до тех пор, пока он сам этого не уточнит.
Всегда используй русский язык, если только собеседник не попросит об ответе на другом языке.
"""

MANAGER_USER_ID = int(os.getenv('MANAGER_USER_ID'))