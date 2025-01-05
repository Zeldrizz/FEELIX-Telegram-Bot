# bot/database.py
import time
from pymilvus import MilvusClient
from pymilvus import model
from pymilvus import DataType, FieldSchema, CollectionSchema
import torch
from sentence_transformers import SentenceTransformer

from logging_config import logger

# from mem0 import Memory

EMBEDDING_DIM = 1024
MAIN_COLLECTION = "main_collection"


# Initialize torch settings for device-agnostic code.
N_GPU = torch.cuda.device_count()  # Число доступных GPU
DEVICE = torch.device(f'cuda:{N_GPU-1}' if N_GPU > 0 else 'cpu')


# Download the model from huggingface model hub.
embedding_model = "BAAI/bge-m3"
encoder = SentenceTransformer(embedding_model, device=DEVICE)
if encoder.get_sentence_embedding_dimension() != EMBEDDING_DIM:
    raise Exception("Database and encoder embedding dimensions do not match")

# Get the model parameters and save for later.
# EMBEDDING_DIM = encoder.get_sentence_embedding_dimension()
print(f"Embedding model name: {embedding_model}")
print(f"EMBEDDING_DIM: {EMBEDDING_DIM}")
print(f"MAX_SEQ_LENGTH: {encoder.get_max_seq_length()}")

id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True)
user_id_field = FieldSchema(name="user_id", dtype=DataType.INT64)
time_field = FieldSchema(name="time", dtype=DataType.INT64)
vector_field = FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
message_field = FieldSchema(name="message", dtype=DataType.VARCHAR, max_length=65535)
role_field = FieldSchema(name="role", dtype=DataType.VARCHAR, max_length=256)

schema = CollectionSchema(fields=[id_field, user_id_field, time_field, vector_field, message_field, role_field],
                          auto_id=True, enable_dynamic_field=False, description="Main collection schema")

logger.info("Initializing MilvusClient with local path: database/main_collection.db")
client = MilvusClient("database/main_collection.db")

#надо поглядеть на параметры при создании
if not client.has_collection(collection_name=MAIN_COLLECTION):
    logger.info(f"Collection '{MAIN_COLLECTION}' not found. Creating it...")
    client.create_collection(
        collection_name=MAIN_COLLECTION,
        # schema=schema,
        dimension=EMBEDDING_DIM,
        metric_type="IP",  # Inner product distance
        consistency_level="Strong",
        auto_id=True
    )
    logger.info(f"Collection '{MAIN_COLLECTION}' created successfully.")
else:
    print(f"Collection '{MAIN_COLLECTION}' already exists.")
    logger.info(f"Collection '{MAIN_COLLECTION}' already exists.")

#хорошо бы сделать async
def db_handle_messages(user_id, role, content : list):
    logger.info(f"Handling messages for user_id={user_id}, role='{role}', content={content}")
    vectors = encoder.encode(content, show_progress_bar=False)
    data = [
        {"user_id" : user_id, "time": int(time.time()), "vector": vectors[i], "message": content[i], "role": role}
        for i in range(len(vectors))
    ]
    # print("Data has", len(data), "entities, each with fields: ", data[0].keys())
    # print("Vector dim:", len(data[0]["vector"]))

    try:
        res = client.insert(collection_name=MAIN_COLLECTION, data=data)
        # print(f"Number of messages inserted for user {user_id}: {res["insert_count"]}")
        inserted_count = res["insert_count"] if "insert_count" in res else "unknown"
        logger.info(f"Inserted {inserted_count} messages into '{MAIN_COLLECTION}' for user_id={user_id}")
    except Exception as e:
        logger.error(f"Error inserting data into '{MAIN_COLLECTION}': {e}")

    if content[0] == ".":
        db_print_all()


def db_get_similar(user_id, content : str):
    logger.info(f"Searching for similar messages to '{content}' for user_id={user_id}")
    vector = encoder.encode(content, show_progress_bar=False)
    try:
        search_res = client.search(
            collection_name=MAIN_COLLECTION,
            data=[vector],
            limit=3,  # Return top 3 results
            search_params={"metric_type": "IP", "params": {}},  # Inner product distance
            output_fields=["message"],  # Return the text field
            # filter="user == " + str(user_id)  # Пример потенциального фильтра, если понадобится
        )

        # search_res = client.search(
        #     collection_name="main_collection_1",
        #     data=[vector],
        #     anns_field="vector",             # поле в котором хранится эмбеддинг
        #     limit=3,
        #     param={"metric_type": "IP"},     # или {"metric_type": "IP", "params": {...}}
        #     output_fields=["message"],
        # )

        if search_res and search_res[0]:
            msgs = [i["entity"]["message"] for i in search_res[0]]
            logger.info(f"Found {len(msgs)} similar messages for user_id={user_id}")
            return msgs
        else:
            logger.info(f"No search results found for user_id={user_id}")
            return []
    except Exception as e:
        logger.error(f"Error while searching similar messages for user_id={user_id}: {e}")
        return []

def db_print_all():
    logger.info(f"Printing up to 500 entries from the collection '{MAIN_COLLECTION}'")
    try:
        res = client.query(
            collection_name=MAIN_COLLECTION,
            output_fields=[message_field.name],  # Returns all fields
            limit=500,
        )
        print("Full database printed:")
        for i in res:
            print(i["message"])
    except Exception as e:
        logger.error(f"Error while querying all entries in '{MAIN_COLLECTION}': {e}")

def db_clear_user_history(user_id: int):
    filter_expression = f"user_id == {user_id}"
    print(filter_expression)
    print(type(filter_expression))
    try:
        client.delete(collection_name=MAIN_COLLECTION, expr=filter_expression)
        collection_info = client.describe_collection(MAIN_COLLECTION)
        print(collection_info)
        logger.info(f"Deleted user data from collection '{MAIN_COLLECTION}' for user_id={user_id}")
    except Exception as e:
        logger.error(f"Error while deleting user data for user_id={user_id}: {e}")