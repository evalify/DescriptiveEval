from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from model import get_llm
from evaluation import bulk_evaluate_quiz_responses

async def evaluation_job(quiz_id: str, model_provider, model_name, model_api_key):
    """
    Execute the evaluation job for the given quiz ID.
    
    :param quiz_id: The ID of the quiz to evaluate
    :param model_provider: The provider of the model to use
    :param model_name: The name of the model to use
    :param model_api_key: The API key for the model
    """

    # Get the database connections
    print("Enqueueing job")
    pg_cursor, pg_conn = get_postgres_cursor()
    mongo_db = get_mongo_client()
    redis_client = get_redis_client()
    save_to_file = True
    llm = get_llm(provider=model_provider, model_name=model_name, api_key=model_api_key)

    result = await bulk_evaluate_quiz_responses(
                       quiz_id,
                       pg_cursor,
                       pg_conn,
                       mongo_db,
                       redis_client,
                       save_to_file,
                       llm)
    
    # Close the database connections
    pg_cursor.close()
    pg_conn.close()
    print({"message": "Evaluation complete", "results": result})  # TODO: Give more detailed response