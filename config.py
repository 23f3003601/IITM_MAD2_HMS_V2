import os
from datetime import timedelta
from celery.schedules import crontab


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
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    # Celery Beat Schedule
    CELERYBEAT_SCHEDULE = {
        # Daily reminder sent every morning at 8:00 AM
        "send-daily-reminders": {
            "task": "app.send_daily_reminders",
            "schedule": crontab(hour=8, minute=0),
        },
        # Monthly report sent on the 1st of every month at 9:00 AM
        "send-monthly-report": {
            "task": "app.send_monthly_report",
            "schedule": crontab(hour=9, minute=0, day_of_month=1),
        },
    }
    CELERY_TIMEZONE = "Asia/Kolkata"
