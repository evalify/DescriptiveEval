import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from dotenv import load_dotenv
# For Type Hinting
from typing import Tuple
from pymongo.database import Database
from psycopg2.extensions import connection as postgres_connection

load_dotenv()


def get_postgres_cursor() -> Tuple[RealDictCursor, postgres_connection]:
    my_connection = psycopg2.connect(os.getenv('COCKROACH_DB'))
    return my_connection.cursor(cursor_factory=RealDictCursor), my_connection


def get_mongo_client() -> Database:
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client["Evalify"]
