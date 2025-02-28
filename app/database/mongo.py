import os
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv
load_dotenv()


def get_mongo_client() -> Database:
    """MongoDB connection"""
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client["Evalify"]