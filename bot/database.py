#bot/database.py
import time
import asyncio
from pymilvus import MilvusClient
from pymilvus import DataType, FieldSchema, CollectionSchema
import torch
from sentence_transformers import SentenceTransformer
import sqlite3

from logging_config import logger
from pathlib import Path
import json
from datetime import datetime

#Настройка векторной базы данных
EMBEDDING_DIM = 1024
MAIN_COLLECTION = "main_collection"
CHUNK_COLLECTION = "chunk_collection"

# Initialize torch settings for device-agnostic code.
N_GPU = torch.cuda.device_count()  # Number of available GPUs
DEVICE = torch.device(f'cuda:{N_GPU-1}' if N_GPU > 0 else 'cpu')

embedding_model = "BAAI/bge-m3"

encoder = SentenceTransformer(embedding_model, device='cuda' if N_GPU > 0 else 'cpu')
if encoder.get_sentence_embedding_dimension() != EMBEDDING_DIM:
    raise Exception("Database and encoder embedding dimensions do not match")

print(f"Embedding model name: {embedding_model}")
print(f"EMBEDDING_DIM: {EMBEDDING_DIM}")
print(f"MAX_SEQ_LENGTH: {encoder.get_max_seq_length()}")

id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True)
user_id_field = FieldSchema(name="user_id", dtype=DataType.INT64)
time_field = FieldSchema(name="time", dtype=DataType.INT64)
vector_field = FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
message_field = FieldSchema(name="message", dtype=DataType.VARCHAR, max_length=65535)
role_field = FieldSchema(name="role", dtype=DataType.VARCHAR, max_length=256)

# Предназначена хранить отдельные сообщения
single_message_scheme = CollectionSchema(
    fields=[id_field, user_id_field, time_field, vector_field, message_field, role_field],
    auto_id=True,
    enable_dynamic_field=False,
    description="Main collection schema"
)

# Предназначена хранить отдельные сообщения
chunk_scheme = CollectionSchema(
    fields=[id_field, user_id_field, time_field, vector_field, message_field],
    auto_id=True,
    enable_dynamic_field=False,
    description="Main collection schema"
)

# Тут вообще нужно поменять имя дбшки, т.к. в одном файле несколько коллекций, но и на сервере придётся менять
logger.info(f"Initializing MilvusClient with local path: database/{MAIN_COLLECTION}.db")
client = MilvusClient(f"database/{MAIN_COLLECTION}.db")

index_params = client.prepare_index_params()
index_params.add_index(
    field_name=vector_field.name,
    metric_type="IP",
    index_type="HNSW",
    index_name="vector_index"
)

# Создаём коллекцию для единичных сообщений
if not client.has_collection(collection_name=MAIN_COLLECTION):
    logger.info(f"Collection '{MAIN_COLLECTION}' not found. Creating it...")
    client.create_collection(
        collection_name=MAIN_COLLECTION,
        schema=single_message_scheme,
        consistency_level="Strong",
        vector_field_name=vector_field.name,
        index_params=index_params
    )
    logger.info(f"Collection '{MAIN_COLLECTION}' created successfully.")
else:
    logger.info(f"Collection '{MAIN_COLLECTION}' found.")

# Создаём коллекцию для чанков
if not client.has_collection(collection_name=CHUNK_COLLECTION):
    logger.info(f"Collection '{CHUNK_COLLECTION}' not found. Creating it...")
    client.create_collection(
        collection_name=CHUNK_COLLECTION,
        schema=chunk_scheme,
        consistency_level="Strong",
        vector_field_name=vector_field.name,
        index_params=index_params
    )
    logger.info(f"Collection '{CHUNK_COLLECTION}' created successfully.")
else:
    logger.info(f"Collection '{CHUNK_COLLECTION}' found.")


PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent

# База текущих (незавершённых) чанков сообщений юзеров
conn = sqlite3.connect(PROJECT_ROOT_PATH / 'save' / 'sqlite3_database.db')
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS current_chunks (
    user_id INT PRIMARY KEY,
    chunk_json TEXT,
    updated_at TEXT
)
""")

# База описания юзеров. Описание сожержит важную информацию о пользователе.
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_descriptions (
    user_id INT PRIMARY KEY,
    description TEXT
)
""")

conn.commit()



async def db_handle_messages(user_id: int, content: list, is_chunk: bool = False, role: str = "user"):
    """
    Inserts messages or chunks into the database. If the content starts with a ".", print all entries.
    """
    logger.info(f"Handling {"chunks" if is_chunk else "messages"} for user_id={user_id}, role='{role}'")
    vectors = encoder.encode(content, show_progress_bar=False)
    data = []
    if is_chunk:
        data = [
            {
                user_id_field.name: user_id,
                time_field.name: int(time.time()),
                vector_field.name: vectors[0],
                message_field.name: content[0],
            }
        ]
    else:
        data = [
            {
                user_id_field.name: user_id,
                time_field.name: int(time.time()),
                vector_field.name: vectors[i],
                message_field.name: content[i],
                role_field.name: role
            }
            for i in range(len(vectors))
        ]
    collection_name = CHUNK_COLLECTION if is_chunk else MAIN_COLLECTION
    try:
        res = await asyncio.to_thread(
            client.insert,
            collection_name=collection_name,
            data=data
        )
        inserted_count = res["insert_count"] if "insert_count" in res else "unknown"
        logger.info(f"Inserted {inserted_count} messages into '{collection_name}' for user_id={user_id}")
    except Exception as e:
        logger.error(f"Error inserting data into '{collection_name}': {e}")

    if content and content[0] == ".":
        await db_print_all()

    # Для дебага
    # print(f"Число: {client.has_partition(MAIN_COLLECTION, user_id)}")
    # print(f"Строка: {client.has_partition(MAIN_COLLECTION, str(user_id))}")


async def db_get_similar(user_id: int, content: str, chunk: bool):
    """
    Searches the database for messages or chunks similar to the given content.
    Returns the top 3 results.
    """
    logger.info(f"Retrieving similar {"chunks" if chunk else "messages"} for user_id={user_id}")
    vector = encoder.encode(content, show_progress_bar=False)
    collection_name = CHUNK_COLLECTION if chunk else MAIN_COLLECTION
    try:
        # Wrap the blocking search call in asyncio.to_thread
        search_res = await asyncio.to_thread(
            client.search,
            collection_name=collection_name,
            data=[vector],
            limit=3,
            output_fields=[message_field.name],
            search_params={"metric_type": "IP"}
        )
        if search_res and search_res[0]:
            msgs = [json.loads(i["entity"]["message"]) for i in search_res[0]]
            logger.info(f"Found {len(msgs)} similar {"chunks" if chunk else "messages"} for user_id={user_id}")
            # print(msgs)
            return msgs
        else:
            logger.info(f"No search results found for user_id={user_id}")
            return []
    except Exception as e:
        logger.error(f"Error while searching similar {"chunks" if chunk else "messages"} for user_id={user_id}: {e}")
        return []


async def db_print_all():
    """
    Prints up to 500 entries from the collection.
    """
    logger.info(f"Printing up to 500 entries from the collection '{MAIN_COLLECTION}'")
    try:
        # Wrap the blocking query call in asyncio.to_thread
        res = await asyncio.to_thread(
            client.query,
            collection_name=MAIN_COLLECTION,
            output_fields=[message_field.name],
            limit=500
        )
        print("Full database printed:")
        for i in res:
            print(i["message"])
    except Exception as e:
        logger.error(f"Error while querying all entries in '{MAIN_COLLECTION}': {e}")

async def db_clear_user_history(user_id: int):
    """
    Clears the message history for a given user.
    """
    filter_expression = f"user_id == {user_id}"
    try:
        # Wrap the blocking delete call in asyncio.to_thread
        await asyncio.to_thread(
            client.delete,
            collection_name=MAIN_COLLECTION,
            filter=filter_expression
        )
        logger.info(f"Deleted user data from collection '{MAIN_COLLECTION}' for user_id={user_id}")
        await asyncio.to_thread(
            client.delete,
            collection_name=CHUNK_COLLECTION,
            filter=filter_expression
        )
        logger.info(f"Deleted user data from collection '{CHUNK_COLLECTION}' for user_id={user_id}")
        clear_current_chunk(user_id)
        clear_description(user_id)
    except Exception as e:
        logger.error(f"Error while deleting user data for user_id={user_id}: {e}")


async def update_chunk(user_id: int, message_text: str, role: str):
    # TODO: мб сделать так, чтобы последнее сообщение в чанке оставалось на следующий чанк, даже если оно большое
    overlap_ratio = 0.2
    max_chunk_size_in_symbols = 1000

    # Загружаем текущий чанк для пользователя
    chunk = get_current_chunk(user_id)
    print(chunk)

    new_message = {
        "role": role,
        "text": message_text,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M")
    }
    chunk.append(new_message)

    # Чанки должны быть небольшие, так что можно каждый раз считать размер
    chunk_size = 0
    for message in chunk:
        chunk_size += len(message["text"])

    # Если длина чанка больше максимальной, завершаем текущий чанк
    if chunk_size >= max_chunk_size_in_symbols:
        # Сохраняем текущий чанк
        await db_handle_messages(user_id, [json.dumps(chunk, ensure_ascii=False)], is_chunk=True)
        await update_description(user_id, chunk)

        # Находим место с которого делать overlap
        tail_len = 0
        tail_sum_size = 0
        while tail_len < len(chunk):
            tail_sum_size += len(chunk[-(tail_len + 1)]["text"])
            if tail_sum_size / chunk_size > overlap_ratio:
                break
            tail_len += 1
        if tail_len == 0:
            chunk = []
        else:
            chunk = chunk[-tail_len:]
    cursor.execute("""
        INSERT INTO current_chunks (user_id, chunk_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        chunk_json = excluded.chunk_json,
        updated_at = excluded.updated_at;
    """, (user_id, json.dumps(chunk), datetime.now().strftime("%Y-%m-%dT%H:%M")))
    conn.commit()

def clear_current_chunk(user_id: int):
    cursor.execute("""
    UPDATE current_chunks
    SET chunk_json = NULL, updated_at = ?
    WHERE user_id = ?
    """, (datetime.now().strftime("%Y-%m-%dT%H:%M"), user_id))
    conn.commit()

def get_current_chunk(user_id: int) -> list:
    cursor.execute("SELECT chunk_json FROM current_chunks WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    chunk = []
    if row:
        try:
            chunk_str = row[0]
            if chunk_str:
                chunk = json.loads(chunk_str)
        except Exception as e:
            logger.error(f"Error while decoding chunk for user {user_id}: {e}. Returning empty chunk.")
    return chunk

async def update_description(user_id: int, chunk: list):
    return
    prompt = [{
        "role": "system",
        "content": """Ты анализируешь часть диалога с пользователем, содержащуюся в chat_history, 
        и извлекаешь из него только важные факты о нём (увлечения, жизненные события, эмоциональные проблемы
        и т. д.). Например: Любит играть в волейбол. Отец умер от инфаркта. Испытывает тревожность 
        при общении с людьми. Если в диалоге нет ничего важного, ответь строго: NOTHING IMPORTANT""",
        "chat_history": chunk
    }]
    print(prompt)
    from bot.handlers import get_api_response
    response = await get_api_response(user_id, prompt)
    # print(response)
    if response == "NOTHING IMPORTANT":
        return

    cursor.execute("""
        INSERT INTO user_descriptions (user_id, description)
        VALUES (?, ?)
        ON CONFLICT (user_id) DO UPDATE SET
        description = COALESCE(description, '') || '\n' || excluded.description
    """, (user_id, response))
    conn.commit()
    #debug
    cursor.execute("SELECT description FROM user_descriptions WHERE user_id = ?", (user_id,))
    print(cursor.fetchone()[0])  # Выведет обновлённый description

def clear_description(user_id: int):
    cursor.execute("""
        UPDATE user_descriptions
        SET description = ''
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()

