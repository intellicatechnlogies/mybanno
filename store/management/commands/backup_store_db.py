from django.core.management.base import BaseCommand, CommandError

from store.email_backup import BackupError, load_config, send_database_backup


class Command(BaseCommand):
    help = "Create a SQLite backup and email it, keeping only the latest backup message"

    def add_arguments(self, parser):
        parser.add_argument("--config", default=None)

    def handle(self, *args, **options):
        try:
            config = load_config(options["config"])
            address = send_database_backup(config)
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Database backup emailed to {address}"))
