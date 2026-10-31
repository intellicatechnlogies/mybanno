import datetime
import logging
import sqlite3
import tempfile
import threading
import time
import os
import sys
from pathlib import Path

import boto3
from django.conf import settings
from .aws_credentials import AwsCredentialsError, load_backup_aws_config


DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
BACKUP_RETENTION_HOURS = 48
_worker_started = False
logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    pass


def load_config(config_path=None):
    try:
        return load_backup_aws_config()
    except AwsCredentialsError as exc:
        raise BackupError(str(exc)) from exc


def get_backup_source():
    source = os.environ.get("MYBANNO_BACKUP_SOURCE", "").strip().lower()
    if source in {"local", "server", "test", "production"}:
        if source == "production":
            return "server"
        return source
    if "runserver" in sys.argv:
        return "local"
    return "server"


def upload_database_backup(config=None, enforce_interval=False, source=None):
    config = config or load_config()
    source = source or get_backup_source()
    lock_key = None
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
        lock_key = acquire_backup_lock(s3, config["bucket"], source)
        if lock_key is None:
            return None
        latest_backup = get_latest_backup(s3, config["bucket"], source)
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
        source_db = sqlite3.connect(str(db_path))
        destination = sqlite3.connect(str(backup_path))
        try:
            source_db.backup(destination)
        finally:
            destination.close()
            source_db.close()

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d-%H%M%S-%f"
        )
        timestamped_key = f"backups/{source}/store.db-{timestamp}.db"

        s3.upload_file(str(backup_path), config["bucket"], timestamped_key)
        delete_old_backups(s3, config["bucket"])

        return timestamped_key
    finally:
        backup_path.unlink(missing_ok=True)
        if lock_key:
            try:
                s3.delete_object(Bucket=config["bucket"], Key=lock_key)
            except Exception as exc:
                logger.warning("Could not release S3 backup lock: %s", exc)


def get_latest_backup(s3, bucket, source=None):
    source = source or get_backup_source()
    paginator = s3.get_paginator("list_objects_v2")
    newest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=f"backups/{source}/store.db-"):
        for item in page.get("Contents", []):
            if newest is None or item["LastModified"] > newest["LastModified"]:
                newest = item
    return newest


def delete_old_backups(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix="backups/")
    objects = []
    for page in pages:
        objects.extend(page.get("Contents", []))

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=BACKUP_RETENTION_HOURS
    )
    obsolete_keys = [
        {"Key": item["Key"]}
        for item in objects
        if item["LastModified"] < cutoff and item["Key"].endswith(".db")
    ]

    unique_keys = {item["Key"]: item for item in obsolete_keys}
    if unique_keys:
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": list(unique_keys.values()), "Quiet": True},
        )


def acquire_backup_lock(s3, bucket, source):
    interval = int(
        os.environ.get(
            "MYBANNO_S3_BACKUP_INTERVAL_SECONDS",
            DEFAULT_INTERVAL_SECONDS,
        )
    )
    lock_key = f"backups/.locks/{source}.lock"

    try:
        s3.put_object(
            Bucket=bucket,
            Key=lock_key,
            Body=f"{source}:{os.getpid()}:{time.time()}".encode("ascii"),
            IfNoneMatch="*",
        )
        return lock_key
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get(
            "HTTPStatusCode"
        )
        if error_code not in {"PreconditionFailed", "ConditionalRequestConflict"} and status != 412:
            raise

        try:
            lock = s3.head_object(Bucket=bucket, Key=lock_key)
        except s3.exceptions.NoSuchKey:
            return acquire_backup_lock(s3, bucket, source)

        lock_modified = lock["LastModified"]
        if lock_modified.tzinfo is None:
            lock_modified = lock_modified.replace(tzinfo=datetime.timezone.utc)
        lock_age = (
            datetime.datetime.now(datetime.timezone.utc) - lock_modified
        ).total_seconds()
        if lock_age >= interval * 2:
            s3.delete_object(Bucket=bucket, Key=lock_key)
            return acquire_backup_lock(s3, bucket, source)
        return None


def start_backup_worker(source=None):
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def run():
        while True:
            try:
                key = upload_database_backup(
                    enforce_interval=True,
                    source=source,
                )
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
