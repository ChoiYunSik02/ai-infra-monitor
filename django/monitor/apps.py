import os
import sys
from django.apps import AppConfig

_bot_started = False


class MonitorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitor'

    def ready(self):
        global _bot_started
        if _bot_started:
            return
        # migrate, makemigrations 등 관리 명령에서는 시작 안 함
        if len(sys.argv) > 1 and sys.argv[1] not in ('runserver',):
            return
        _bot_started = True
        from monitor import telegram_bot, alert_checker
        telegram_bot.start()
        alert_checker.start()
