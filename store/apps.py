import os
import sys

from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "store"

    def ready(self):
        if os.environ.get("MYBANNO_DISABLE_S3_BACKUP") == "1":
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") not in (None, "true"):
            return
        if len(sys.argv) > 1 and sys.argv[0].endswith("manage.py"):
            if sys.argv[1].lower() in {
                "backup_store_db_s3",
                "check",
                "collectstatic",
                "migrate",
                "makemigrations",
                "shell",
                "test",
            }:
                return

        from store.s3_backup import start_backup_worker

        start_backup_worker()
