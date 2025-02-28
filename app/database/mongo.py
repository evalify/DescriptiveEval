from app.config.constants import MONGODB_URI
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv

load_dotenv()


def get_mongo_client() -> Database:
    """MongoDB connection"""
    client = MongoClient(MONGODB_URI)
    return client["Evalify"]
