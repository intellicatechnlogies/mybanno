import os
import sys

from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "store"

    def ready(self):
        if "runserver" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") not in (None, "true"):
            return
        if os.environ.get("MYBANNO_DISABLE_EMAIL_BACKUP") == "1":
            return

        from store.email_backup import start_backup_worker

        start_backup_worker()
