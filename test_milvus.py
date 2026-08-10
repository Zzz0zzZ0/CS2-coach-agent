import os


def main():
    from dotenv import load_dotenv
    from langchain_community.embeddings import DashScopeEmbeddings
    from langchain_community.vectorstores import Milvus
    from pymilvus import connections

    load_dotenv(".env")
    uri = "http://127.0.0.1:19530"
    embeddings = DashScopeEmbeddings(model="text-embedding-v2", dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"))

    try:
        connections.connect("default", uri=uri)
        print("connections.connect default OK")
    except Exception as e:
        print(e)

    try:
        vectorstore = Milvus(
            embedding_function=embeddings,
            collection_name="test_col2",
            drop_old=True,
            auto_id=True
        )
        print("vectorstore init OK")
        vectorstore.add_texts(["hello"])
        print("add_texts OK")
    except Exception as e:
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
