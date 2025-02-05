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

# Initialize torch settings for device-agnostic code.
N_GPU = torch.cuda.device_count()  # Number of available GPUs
DEVICE = torch.device(f'cuda:{N_GPU-1}' if N_GPU > 0 else 'cpu')

# Download the model from Hugging Face model hub.
embedding_model = "BAAI/bge-m3"
encoder = SentenceTransformer(embedding_model, device=DEVICE)
if encoder.get_sentence_embedding_dimension() != EMBEDDING_DIM:
    raise Exception("Database and encoder embedding dimensions do not match")

print(f"Embedding model name: {embedding_model}")
print(f"EMBEDDING_DIM: {EMBEDDING_DIM}")
print(f"MAX_SEQ_LENGTH: {encoder.get_max_seq_length()}")

# Define Milvus collection fields
id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True)
user_id_field = FieldSchema(name="user_id", dtype=DataType.INT64)
time_field = FieldSchema(name="time", dtype=DataType.INT64)
vector_field = FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
message_field = FieldSchema(name="message", dtype=DataType.VARCHAR, max_length=65535)
role_field = FieldSchema(name="role", dtype=DataType.VARCHAR, max_length=256)

schema = CollectionSchema(
    fields=[id_field, user_id_field, time_field, vector_field, message_field, role_field],
    auto_id=True,
    enable_dynamic_field=False,
    description="Main collection schema"
)

logger.info(f"Initializing MilvusClient with local path: database/{MAIN_COLLECTION}.db")
client = MilvusClient(f"database/{MAIN_COLLECTION}.db")

index_params = client.prepare_index_params()
index_params.add_index(
    field_name=vector_field.name,
    index_type="AUTOINDEX",
    metric_type="IP"
)

if not client.has_collection(collection_name=MAIN_COLLECTION):
    logger.info(f"Collection '{MAIN_COLLECTION}' not found. Creating it...")
    client.create_collection(
        collection_name=MAIN_COLLECTION,
        schema=schema,
        metric_type="IP",  # Inner product distance
        consistency_level="Strong",
        primary_field_name=id_field.name,
        vector_field_name=vector_field.name,
        index_params=index_params
    )
    logger.info(f"Collection '{MAIN_COLLECTION}' created successfully.")
else:
    print(f"Collection '{MAIN_COLLECTION}' already exists.")
    logger.info(f"Collection '{MAIN_COLLECTION}' already exists.")
    client.load_collection(MAIN_COLLECTION)


async def db_handle_messages(user_id: int, role: str, content: list):
    """
    Inserts messages into the database. If the content starts with a ".", print all entries.
    """
    logger.info(f"Handling messages for user_id={user_id}, role='{role}', content={content}")
    vectors = encoder.encode(content, show_progress_bar=False)
    data = [
        {
            "user_id": user_id,
            "time": int(time.time()),
            "vector": vectors[i],
            "message": content[i],
            "role": role
        }
        for i in range(len(vectors))
    ]
    try:
        # Wrap the blocking insert call in asyncio.to_thread
        res = await asyncio.to_thread(
            client.insert,
            collection_name=MAIN_COLLECTION,
            data=data
        )
        inserted_count = res["insert_count"] if "insert_count" in res else "unknown"
        logger.info(f"Inserted {inserted_count} messages into '{MAIN_COLLECTION}' for user_id={user_id}")
    except Exception as e:
        logger.error(f"Error inserting data into '{MAIN_COLLECTION}': {e}")

    if content and content[0] == ".":
        await db_print_all()


async def db_get_similar(user_id: int, content: str):
    """
    Searches the database for messages similar to the given content.
    Returns the top 3 matching messages.
    """
    logger.info(f"Searching for similar messages to '{content}' for user_id={user_id}")
    vector = encoder.encode(content, show_progress_bar=False)
    try:
        # Wrap the blocking search call in asyncio.to_thread
        search_res = await asyncio.to_thread(
            client.search,
            collection_name=MAIN_COLLECTION,
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