import datetime
import json
import logging
import sqlite3
import tempfile
import threading
import time
import os
from pathlib import Path

import boto3
from django.conf import settings


DEFAULT_INTERVAL_SECONDS = 10 * 60
BACKUP_RETENTION_COUNT = 3
_worker_started = False
logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    pass


def load_config(config_path=None):
    path = Path(config_path or settings.BASE_DIR / "aws.json")
    if not path.exists():
        raise BackupError(f"AWS configuration not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"Invalid JSON in {path}: {exc}") from exc

    access_key = (data.get("Access_key_ID") or "").strip()
    secret_key = (data.get("Secret_Access_Key") or "").strip()
    region = (data.get("Region") or "").strip()
    bucket = (data.get("Bucket") or "").strip()

    if not all((access_key, secret_key, region, bucket)):
        raise BackupError(
            "aws.json must contain Access_key_ID, Secret_Access_Key, Region, and Bucket"
        )

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
    }


def upload_database_backup(config=None, enforce_interval=False):
    config = config or load_config()
    db_path = Path(settings.DATABASES["default"]["NAME"])
    if not db_path.exists():
        raise BackupError(f"Database not found: {db_path}")

    session = boto3.Session(
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
    )
    s3 = session.client("s3")

    if enforce_interval:
        interval = int(
            os.environ.get(
                "MYBANNO_S3_BACKUP_INTERVAL_SECONDS",
                DEFAULT_INTERVAL_SECONDS,
            )
        )
        latest_backup = get_latest_backup(s3, config["bucket"])
        if latest_backup is not None:
            age_seconds = (
                datetime.datetime.now(datetime.timezone.utc)
                - latest_backup["LastModified"]
            ).total_seconds()
            if age_seconds < interval:
                return None

    with tempfile.NamedTemporaryFile(prefix="store-", suffix=".db", delete=False) as temp:
        backup_path = Path(temp.name)

    try:
        source = sqlite3.connect(str(db_path))
        destination = sqlite3.connect(str(backup_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d-%H%M%S-%f"
        )
        timestamped_key = f"backups/store.db-{timestamp}.db"

        s3.upload_file(str(backup_path), config["bucket"], timestamped_key)
        delete_old_backups(s3, config["bucket"])

        return timestamped_key
    finally:
        backup_path.unlink(missing_ok=True)


def get_latest_backup(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    newest = None
    for page in paginator.paginate(Bucket=bucket, Prefix="backups/store.db-"):
        for item in page.get("Contents", []):
            if newest is None or item["LastModified"] > newest["LastModified"]:
                newest = item
    return newest


def delete_old_backups(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix="backups/store.db-")
    objects = []
    for page in pages:
        objects.extend(page.get("Contents", []))

    objects.sort(key=lambda item: item["LastModified"], reverse=True)
    obsolete_keys = [
        {"Key": item["Key"]}
        for item in objects[BACKUP_RETENTION_COUNT:]
    ]

    for prefix in ("latest/store.db", "latest/"):
        latest_objects = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
        ).get("Contents", [])
        obsolete_keys.extend({"Key": item["Key"]} for item in latest_objects)

    unique_keys = {item["Key"]: item for item in obsolete_keys}
    if unique_keys:
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": list(unique_keys.values()), "Quiet": True},
        )


def start_backup_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def run():
        while True:
            try:
                key = upload_database_backup(enforce_interval=True)
                if key:
                    logger.info("S3 database backup uploaded: %s", key)
            except Exception as exc:
                logger.exception("S3 database backup failed: %s", exc)
            interval = int(
                os.environ.get(
                    "MYBANNO_S3_BACKUP_INTERVAL_SECONDS",
                    DEFAULT_INTERVAL_SECONDS,
                )
            )
            time.sleep(interval)

    thread = threading.Thread(target=run, name="mybanno-s3-backup", daemon=True)
    thread.start()
