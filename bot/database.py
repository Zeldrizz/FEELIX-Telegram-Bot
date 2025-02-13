#bot/database.py
import time
import asyncio
from pymilvus import MilvusClient
from pymilvus import model
from pymilvus import DataType, FieldSchema, CollectionSchema
import torch
from sentence_transformers import SentenceTransformer

from logging_config import logger

# Constants and configuration
EMBEDDING_DIM = 1024
MAIN_COLLECTION = "main_collection"
CHUNK_COLLECTION = "chunk_collection"

# Initialize torch settings for device-agnostic code.
N_GPU = torch.cuda.device_count()  # Number of available GPUs
DEVICE = torch.device(f'cuda:{N_GPU-1}' if N_GPU > 0 else 'cpu')

# Download the model from Hugging Face model hub.
embedding_model = "BAAI/bge-m3"

encoder = SentenceTransformer(embedding_model, device='cuda' if N_GPU > 0 else 'cpu')
if encoder.get_sentence_embedding_dimension() != EMBEDDING_DIM:
    raise Exception("Database and encoder embedding dimensions do not match")

print(f"Embedding model name: {embedding_model}")
print(f"EMBEDDING_DIM: {EMBEDDING_DIM}")
print(f"MAX_SEQ_LENGTH: {encoder.get_max_seq_length()}")

# Define Milvus collection fields
id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True)
user_id_field = FieldSchema(name="user_id", dtype=DataType.INT64, is_partition_key=True)
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

async def db_handle_messages(user_id: int, content: list, is_chunk: bool = False, role: str = "user"):
    """
    Inserts messages or chunks into the database. If the content starts with a ".", print all entries.
    """
    logger.info(f"Handling {"chunks" if is_chunk else "messages"} for user_id={user_id}, role='{role}',"
                f" content={content[:200]}{"..." if len(content) > 200 else ""}")
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


async def db_get_similar(user_id: int, content: str, is_chunk: bool):
    """
    Searches the database for messages or chunks similar to the given content.
    Returns the top 3 matching messages.
    """
    logger.info(f"Retrieving similar {"chunks" if is_chunk else "messages"} for user_id={user_id}")
    vector = encoder.encode(content, show_progress_bar=False)
    collection_name = CHUNK_COLLECTION if is_chunk else MAIN_COLLECTION
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
            msgs = [i["entity"]["message"] for i in search_res[0]]
            logger.info(f"Found {len(msgs)} similar messages for user_id={user_id}")
            # print(msgs)
            return msgs
        else:
            logger.info(f"No search results found for user_id={user_id}")
            return []
    except Exception as e:
        logger.error(f"Error while searching similar messages for user_id={user_id}: {e}")
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
    except Exception as e:
        logger.error(f"Error while deleting user data for user_id={user_id}: {e}")