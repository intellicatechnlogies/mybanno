from django.core.management.base import BaseCommand, CommandError

from store.s3_backup import BackupError, load_config, upload_database_backup


class Command(BaseCommand):
    help = "Create a SQLite snapshot and upload it to the configured AWS S3 bucket"

    def add_arguments(self, parser):
        parser.add_argument("--config", default=None)

    def handle(self, *args, **options):
        try:
            config = load_config(options["config"])
            key = upload_database_backup(config)
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Database backup uploaded to S3: {key}")
        )
