import time
from email import message_from_file

from humanfriendly.terminal import message
from openai import embeddings
from pkg_resources import distributions_from_metadata
from pymilvus import MilvusClient
from pymilvus import model
from pymilvus import DataType, FieldSchema, CollectionSchema

# from mem0 import Memory

EMBEDDINGS_DIM = 768
MAIN_COLLECTION = "main_collection"


id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True)
user_id_field = FieldSchema(name="user_id", dtype=DataType.INT64)
time_field = FieldSchema(name="time", dtype=DataType.INT64)
vector_field = FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDINGS_DIM)
message_field = FieldSchema(name="message", dtype=DataType.VARCHAR)
role_field = FieldSchema(name="role", dtype=DataType.VARCHAR)

schema = CollectionSchema(fields=[id_field, user_id_field, time_field, vector_field, message_field, role_field],
                          auto_id=True, enable_dynamic_field=False, description="Main collection schema")

# config = {
#     "vector_store": {
#         "provider": "milvus",
#         "config": {
#             "collection_name": "mem0_milvus",
#             "embedding_model_dims": str(EMBEDDINGS_DIM),
#             "url": "../database/milvus_main.db",  # Use local vector database for demo purpose
#         },
#     },
#     "version": "v1.1",
# }
#
# memory = Memory.from_config(config)


client = MilvusClient("database/milvus_main.db")

embedding_fn = model.DefaultEmbeddingFunction()

#надо поглядеть на параметры при создании
if not client.has_collection(collection_name=MAIN_COLLECTION):
    client.create_collection(
        collection_name=MAIN_COLLECTION,
        dimension=EMBEDDINGS_DIM,
        metric_type="IP",  # Inner product distance
        consistency_level="Strong",
        auto_id=True
    )


#хорошо бы сделать async
def db_handle_messages(user_id, role, content : list):
    vectors = embedding_fn.encode_documents(content)
    data = [
        {"user_id" : user_id, "time": int(time.time()), "vector": vectors[i], "message": content[i], "role": role}
        for i in range(len(vectors))
    ]
    # print("Data has", len(data), "entities, each with fields: ", data[0].keys())
    # print("Vector dim:", len(data[0]["vector"]))
    res = client.insert(collection_name=MAIN_COLLECTION, data=data)
    print(res)

    # res = memory.add(
    #     messages=content,
    #     user_id=user_id,
    #     # metadata={"category": "hobbies"},
    # )
    # print(res)


def db_get_similar(user_id, content : str):
    try:
        search_res = client.search(
            collection_name=MAIN_COLLECTION,
            data=[
                embedding_fn(content)[0]
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


# res = client.search(
#     collection_name="demo_collection",  # target collection
#     data=query_vectors,  # query vectors
#     limit=2,  # number of returned entities
#     output_fields=["text", "subject"],  # specifies fields to be returned
# )