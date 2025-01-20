import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

def get_postgres_cursor():
    connection = psycopg2.connect(os.getenv('COCKROACH_DB'))
    return connection.cursor(cursor_factory=RealDictCursor), connection

def get_mongo_client():
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client["Evalify"]
