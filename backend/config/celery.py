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
        "schedule": 3600.0,  # каждый час
    },
    "check-risk-alerts-periodic": {
        "task": "analytics.check_and_send_risk_alerts",
        "schedule": crontab(hour=19, minute=0),  # Каждый вечер в 19:00 МСК
    },
}
