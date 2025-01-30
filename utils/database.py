"""This module contains functions to interact with databases (Postgres, MongoDB, Redis)"""

import os
from typing import Tuple

import psycopg2
import redis
from dotenv import load_dotenv
from psycopg2.extensions import connection as postgres_connection
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from pymongo.database import Database
from redis import Redis

load_dotenv()


def get_postgres_cursor() -> Tuple[RealDictCursor, postgres_connection]:
    my_connection = psycopg2.connect(os.getenv('COCKROACH_DB'))
    return my_connection.cursor(cursor_factory=RealDictCursor), my_connection


def get_mongo_client() -> Database:
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client["Evalify"]


def get_redis_client() -> Redis:
    return redis.StrictRedis(
        host=os.getenv('REDIS_HOST', '172.17.9.74'),
        port=int(os.getenv('REDIS_PORT', 32768)),
        db=int(os.getenv('REDIS_DB', 2)),
        decode_responses=False
    )
