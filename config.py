import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "hms-secret-key-2024"
    SQLALCHEMY_DATABASE_URI = "sqlite:///hms.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = "redis://localhost:6379/0"
    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
    SESSION_TYPE = "redis"
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    CACHE_TYPE = "redis"
    CACHE_REDIS_URL = "redis://localhost:6379/1"
    CACHE_DEFAULT_TIMEOUT = 300
