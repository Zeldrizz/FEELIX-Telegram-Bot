# bot/update_system_prompt.py
import os
import json

from config import SYSTEM_PROMPT

def update_system_prompt_in_logs():
    """
    Заменяем SYSTEM_PROMPT во всех conversation_history.json в папке logs/
    """
    logs_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "logs"
    )

    if not os.path.isdir(logs_dir):
        print(f"Неверный путь до папки: {logs_dir}")
        return

    for item in os.listdir(logs_dir):
        subdir_path = os.path.join(logs_dir, item)

        if os.path.isdir(subdir_path) and item.startswith("user_"):
            json_path = os.path.join(subdir_path, "conversation_history.json")
            if not os.path.exists(json_path):
                continue

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    conversation = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Ошибка чтения {json_path}: {e}")
                continue

            if not isinstance(conversation, list) or not conversation:
                continue

            updated = False
            for msg in conversation:
                if msg.get("role") == "system":
                    msg["content"] = SYSTEM_PROMPT.strip()
                    updated = True
                    break

            if updated:
                try:
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(conversation, f, ensure_ascii=False, indent=2)
                    print(f"SYSTEM_PROMPT успешно обновлен в {json_path}")
                except OSError as e:
                    print(f"Ошибка записи SYSTEM_PROMPT в {json_path}: {e}")
            else:
                print(f"В {json_path} нет сообщения с 'role': 'system'")

if __name__ == "__main__":
    update_system_prompt_in_logs()
    print("Скрипт завершился")
