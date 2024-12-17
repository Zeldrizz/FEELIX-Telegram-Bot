# bot/database.py
import time
from pymilvus import MilvusClient
from pymilvus import model
from pymilvus import DataType, FieldSchema, CollectionSchema
import torch
from sentence_transformers import SentenceTransformer

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
message_field = FieldSchema(name="message", dtype=DataType.VARCHAR)
role_field = FieldSchema(name="role", dtype=DataType.VARCHAR)

schema = CollectionSchema(fields=[id_field, user_id_field, time_field, vector_field, message_field, role_field],
                          auto_id=True, enable_dynamic_field=False, description="Main collection schema")

client = MilvusClient("database/milvus_main.db")

#надо поглядеть на параметры при создании
if not client.has_collection(collection_name=MAIN_COLLECTION):
    client.create_collection(
        collection_name=MAIN_COLLECTION,
        dimension=EMBEDDING_DIM,
        metric_type="IP",  # Inner product distance
        consistency_level="Strong",
        auto_id=True
    )

#хорошо бы сделать async
def db_handle_messages(user_id, role, content : list):
    vectors = encoder.encode(content, show_progress_bar=False)
    data = [
        {"user_id" : user_id, "time": int(time.time()), "vector": vectors[i], "message": content[i], "role": role}
        for i in range(len(vectors))
    ]
    # print("Data has", len(data), "entities, each with fields: ", data[0].keys())
    # print("Vector dim:", len(data[0]["vector"]))
    res = client.insert(collection_name=MAIN_COLLECTION, data=data)
    print(f"Number of messages inserted for user {user_id}: {res["insert_count"]}")
    if content[0] == ".":
        db_print_all()


def db_get_similar(user_id, content : str):
    vector = encoder.encode(content, show_progress_bar=False)
    try:
        search_res = client.search(
            collection_name=MAIN_COLLECTION,
            data=[
                vector
            ],
            limit=3,  # Return top 3 results
            search_params={"metric_type": "IP", "params": {}},  # Inner product distance
            output_fields=["message"],  # Return the text field
            # filter="user == " + str(user_id)
        )
        return [i["entity"]["message"] for i in search_res[0]]
        # return search_res[0][0]
    except Exception as e:
        print(e)

def db_print_all():
    res = client.query(
        collection_name=MAIN_COLLECTION,
        output_fields=[message_field.name],  # Returns all fields
        limit=500,
    )
    print("full database printed:")
    for i in res:
        print(i["message"])
