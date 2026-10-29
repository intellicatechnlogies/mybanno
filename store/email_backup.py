import imaplib
import json
import logging
import re
import smtplib
import sqlite3
import tempfile
import threading
import zipfile
import time
import os
import datetime
from email.message import EmailMessage
from pathlib import Path

from django.conf import settings


SUBJECT = "Mybanno - Email backup"
DEFAULT_INTERVAL_SECONDS = 10 * 60
DEFAULT_MAX_PART_BYTES = 18 * 1024 * 1024
_worker_started = False
logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    pass


def load_config(config_path=None):
    path = Path(config_path or settings.BASE_DIR / "email.json")
    if not path.exists():
        raise BackupError(f"Email configuration not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"Invalid JSON in {path}: {exc}") from exc

    smtp_server = data.get("SMTP_Server") or "smtp.gmail.com"
    port = int(data.get("Port") or 587)
    address = (data.get("Email") or "").strip()
    password = (data.get("App_Password") or "").replace(" ", "")

    if not address or not password:
        raise BackupError("email.json must contain Email and App_Password")

    return {
        "smtp_server": smtp_server,
        "port": port,
        "email": address,
        "password": password,
    }


def send_database_backup(config=None):
    config = config or load_config()
    db_path = Path(settings.DATABASES["default"]["NAME"])
    if not db_path.exists():
        raise BackupError(f"Database not found: {db_path}")

    with tempfile.NamedTemporaryFile(prefix="store-", suffix=".db", delete=False) as temp:
        backup_path = Path(temp.name)

    try:
        source = sqlite3.connect(str(db_path))
        destination = sqlite3.connect(str(backup_path))
        try:
            source.backup(destination)
            destination.execute("VACUUM")
        finally:
            destination.close()
            source.close()

        zip_path = backup_path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(backup_path, arcname="store.db")

        backup_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        max_part_bytes = int(
            os.environ.get("MYBANNO_BACKUP_MAX_PART_BYTES", DEFAULT_MAX_PART_BYTES)
        )
        zip_size = zip_path.stat().st_size
        part_count = max(1, (zip_size + max_part_bytes - 1) // max_part_bytes)

        with zip_path.open("rb") as archive_file:
            for part_number in range(1, part_count + 1):
                archive_chunk = archive_file.read(max_part_bytes)
                if not archive_chunk:
                    break

                message = EmailMessage()
                message["From"] = config["email"]
                message["To"] = config["email"]
                message["Subject"] = (
                    f"{SUBJECT} [{backup_id}] part {part_number} of {part_count}"
                )
                message.set_content(
                    "Automated Mybanno store.db backup.\n"
                    f"This email contains part {part_number} of {part_count}. "
                    "Concatenate the .zip.* files in order and unzip the result."
                )
                extension = "zip" if part_count == 1 else f"zip.{part_number:03d}"
                message.add_attachment(
                    archive_chunk,
                    maintype="application",
                    subtype="zip",
                    filename=f"store.db.{extension}",
                )

                with smtplib.SMTP(config["smtp_server"], config["port"], timeout=300) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(config["email"], config["password"])
                    smtp.send_message(message)

        try:
            keep_only_latest_backup(config)
        except Exception as exc:
            logger.warning("Backup was sent but old-mail cleanup failed: %s", exc)
    finally:
        backup_path.unlink(missing_ok=True)
        backup_path.with_suffix(".zip").unlink(missing_ok=True)

    return config["email"]


def keep_only_latest_backup(config=None):
    config = config or load_config()
    imap_host = "imap.gmail.com" if config["smtp_server"] == "smtp.gmail.com" else config["smtp_server"].replace("smtp.", "imap.", 1)

    with imaplib.IMAP4_SSL(imap_host, 993, timeout=300) as imap:
        imap.login(config["email"], config["password"])
        folders = ["INBOX"] + _find_sent_folders(imap)

        for folder in folders:
            mailbox = f'"{folder}"' if " " in folder else folder
            status, _ = imap.select(mailbox, readonly=False)
            if status != "OK":
                continue

            status, data = imap.uid("search", None, 'HEADER Subject "Mybanno - Email backup"')
            if status != "OK" or not data or not data[0]:
                continue

            backup_ids = {}
            for uid_bytes in data[0].split():
                uid = uid_bytes.decode("ascii")
                fetch_status, fetch_data = imap.uid("fetch", uid, "(RFC822.HEADER)")
                if fetch_status != "OK" or not fetch_data or not fetch_data[0]:
                    continue
                header = fetch_data[0][1] if isinstance(fetch_data[0], tuple) else fetch_data[0]
                header_text = header.decode("utf-8", errors="replace")
                match = re.search(r"\bMybanno - Email backup \[([0-9]{14})\]", header_text)
                if match:
                    backup_ids.setdefault(match.group(1), []).append(uid)

            if len(backup_ids) > 1:
                latest_backup_id = max(backup_ids)
                for backup_id, old_uids in backup_ids.items():
                    if backup_id == latest_backup_id:
                        continue
                    for uid in old_uids:
                        imap.uid("store", uid, "+FLAGS", "\\Deleted")
                imap.expunge()


def _find_sent_folders(imap):
    status, data = imap.list()
    if status != "OK" or not data:
        return []

    folders = []
    for item in data:
        if not item:
            continue
        text = item.decode("utf-8", errors="replace")
        quoted = re.findall(r'"([^"]*)"$', text)
        name = quoted[-1] if quoted else ""
        if "sent" in name.lower():
            folders.append(name)
    return list(dict.fromkeys(folders))


def start_backup_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def run():
        while True:
            try:
                send_database_backup()
            except Exception as exc:
                logger.exception("Database email backup failed: %s", exc)
            interval = int(
                os.environ.get(
                    "MYBANNO_BACKUP_INTERVAL_SECONDS",
                    DEFAULT_INTERVAL_SECONDS,
                )
            )
            time.sleep(interval)

    thread = threading.Thread(target=run, name="mybanno-db-backup", daemon=True)
    thread.start()
