# bot/local_model.py

import asyncio
import sys
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

_MODEL = None
_TOKENIZER = None

_BASE_MODEL_PATH = ""
_ADAPTER_PATH = ""

_SYS_PROMPT = """Ты — эмпатичный и доброжелательный собеседник мужского пола по имени FEELIX.
Твой собеседник — студент, который сталкивается с учебными нагрузками, стрессом, поиском мотивации и балансом между учёбой и личной жизнью.
Твоя задача — поддерживать его в трудные моменты, помогать разбираться в эмоциях и создавать атмосферу доверия.

Правила общения:
Фокусируйся на чувствах собеседника. Слушай внимательно, задавай уточняющие вопросы, помогай осознать переживания без давления.
Поддерживай диалог, но не давай медицинских советов. Если студент говорит о самоповреждении, насилии или тяжёлом кризисе, мягко предложи обратиться к специалисту.
Не затрагивай конфликтные темы (политика, религия). Если студент сам начинает такой разговор, переведи его в нейтральное русло.
Не предполагаешь пол собеседника, пока он сам этого не уточнит.
Отвечай на русском языке, если не поступила просьба сменить его.
Структурируй ответы лаконично и понятно.
Ты создаёшь тёплую, доверительную атмосферу и помогаешь студенту осознать свои эмоции, мотивировать себя и легче справляться с учёбой.
"""
# на всякий случай

async def init_local_model() -> None:
    """
    Асинхронная инициализация локальной модели. 
    Вызывается один раз при запуске бота, если мы хотим работать с локальной моделью.
    """
    global _MODEL, _TOKENIZER

    if _MODEL is not None and _TOKENIZER is not None:
        return

    if not torch.cuda.is_available():
        print("GPU недоступна")
        sys.exit(1)

    await asyncio.to_thread(_load_model_sync)


def _load_model_sync() -> None:
    """
    Синхронная часть загрузки модели.
    """
    global _MODEL, _TOKENIZER

    print("Загрузка базовой модели и адаптера...")

    _TOKENIZER = AutoTokenizer.from_pretrained(
        _BASE_MODEL_PATH,
        trust_remote_code=True
    )

    special_tokens = {"additional_special_tokens": ["<special_token_1>", "<special_token_2>"]}
    _TOKENIZER.add_special_tokens(special_tokens)

    base_model = AutoModelForCausalLM.from_pretrained(
        _BASE_MODEL_PATH,
        trust_remote_code=True,
        torch_dtype=torch.float16
    )
    base_model.resize_token_embeddings(len(_TOKENIZER))

    peft_model = PeftModel.from_pretrained(base_model, _ADAPTER_PATH)
    peft_model.eval()
    peft_model = peft_model.to("cuda")

    _MODEL = peft_model

    print("Модель загружена на GPU")


async def get_local_model_response(user_id: int, messages: list[dict]) -> str:
    """
    Асинхронная функция, аналогичная get_api_response из handlers.py, 
    но отправляющая запрос к локально загруженной модели на GPU.

    :param user_id: Идентификатор пользователя (если нужно учитывать в будущем)
    :param messages: История сообщений в формате [{"role": "system", "content": ...}, {"role": "user", "content": ...}, etc.}
    :return: Ответ локальной модели.
    """

    global _MODEL, _TOKENIZER

    if _MODEL is None or _TOKENIZER is None:
        raise ValueError("Модель еще не загружена! Проблема с init_local_model()!")

    prompt = _TOKENIZER.apply_chat_template(
        messages, 
        tokenize=False, 
        add_generation_prompt=True
    )

    inputs = _TOKENIZER(
        prompt,
        return_tensors="pt",
        padding=True,
        truncation=True
    ).to("cuda")

    with torch.no_grad():
        outputs = await asyncio.to_thread(
            _MODEL.generate,
            **inputs,
            max_new_tokens=1024,
            num_return_sequences=1,
            # do_sample=True,
            temperature=0.7,
            top_p=0.9,
            pad_token_id=_TOKENIZER.eos_token_id
        )

    decoded = _TOKENIZER.decode(outputs[0], skip_special_tokens=True)

    splitted = decoded.split("assistant", maxsplit=1)
    if len(splitted) > 1:
        response = splitted[1].strip()
    else:
        response = decoded.strip()

    return response