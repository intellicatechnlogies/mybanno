import os
import sys

from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "store"

    def ready(self):
        if os.environ.get("MYBANNO_DISABLE_EMAIL_BACKUP") == "1":
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") not in (None, "true"):
            return
        if len(sys.argv) > 1 and sys.argv[0].endswith("manage.py"):
            management_command = sys.argv[1].lower()
            if management_command in {
                "backup_store_db",
                "check",
                "collectstatic",
                "migrate",
                "makemigrations",
                "shell",
                "test",
            }:
                return

        from store.email_backup import start_backup_worker

        start_backup_worker()
