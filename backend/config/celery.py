import os 
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("t_invest")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


app.conf.beat_schedule = {
    "sync-portfolios-every-hour": {
        "task": "portfolio.tasks.sync_portfolios",
        "schedule": 3600.0,  # каждый час (для теста можно поставить, например, 60.0)
    },
}
