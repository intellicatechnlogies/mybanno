import json
import mimetypes
import re
import uuid
import io
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import boto3
from django.conf import settings
from PIL import Image, ImageOps
from .aws_credentials import AwsCredentialsError, BACKUP_BUCKET_ACCOUNT, load_aws_config, MEDIA_BUCKET_ACCOUNT


_media_clients = {}


class MediaStorageError(RuntimeError):
    pass


def load_media_config(config_path=None):
    try:
        return load_aws_config(MEDIA_BUCKET_ACCOUNT)
    except AwsCredentialsError as exc:
        raise MediaStorageError(str(exc)) from exc


def get_media_s3_client(config=None):
    config = config or load_media_config()
    cache_key = (
        config["access_key"],
        config["secret_key"],
        config["region"],
    )
    client = _media_clients.get(cache_key)
    if client is not None:
        return client
    session = boto3.Session(
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
    )
    client = session.client("s3")
    _media_clients[cache_key] = client
    return client


def public_s3_url(bucket, region, key):
    encoded_key = quote(key, safe="/")
    if region == "us-east-1":
        return f"https://{bucket}.s3.amazonaws.com/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def extract_s3_key(data_url, bucket):
    if not data_url or data_url.startswith("data:"):
        return ""
    parsed = urlparse(data_url)
    if parsed.scheme not in ("http", "https"):
        return ""

    host = parsed.hostname or ""
    path = parsed.path.lstrip("/")
    if host == f"{bucket}.s3.amazonaws.com":
        return unquote(path)
    if host.startswith(f"{bucket}.s3.") or host.startswith(f"{bucket}.s3-"):
        return unquote(path)
    if host == "s3.amazonaws.com":
        parts = path.split("/", 1)
        return unquote(parts[1]) if len(parts) == 2 and parts[0] == bucket else ""
    if host.startswith("s3.") or host.startswith("s3-"):
        parts = path.split("/", 1)
        return unquote(parts[1]) if len(parts) == 2 and parts[0] == bucket else ""
    return ""


def display_media_url(data_url):
    if not data_url or data_url.startswith("data:"):
        return data_url
    try:
        config = load_media_config()
    except MediaStorageError:
        return data_url
    key = extract_s3_key(data_url, config["bucket"])
    if not key:
        return data_url
    return get_media_s3_client(config).generate_presigned_url(
        "get_object",
        Params={"Bucket": config["bucket"], "Key": key},
        ExpiresIn=24 * 60 * 60,
    )


def safe_filename(filename):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-.")
    return name or "media"


def thumbnail_key_for(original_key):
    key = str(original_key).replace("\\", "/").strip("/")
    marker = "/images/"
    if marker not in key:
        return ""
    stem = Path(key.rsplit("/", 1)[-1]).stem
    return f"{key.rsplit(marker, 1)[0]}/thumbnails/{stem}.webp"


def thumbnail_media_url(data_url):
    if not data_url or data_url.startswith("data:"):
        return data_url
    try:
        config = load_media_config()
    except MediaStorageError:
        return display_media_url(data_url)
    original_key = extract_s3_key(data_url, config["bucket"])
    thumbnail_key = thumbnail_key_for(original_key)
    if not thumbnail_key:
        return display_media_url(data_url)
    return f"/media-cache/{quote(thumbnail_key, safe='/')}"


def create_thumbnail(content, max_size=600):
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=82, method=6)
        return output.getvalue()
    except Exception:
        return None


def upload_media(product_id, media_type, filename, content_type, content):
    config = load_media_config()
    if isinstance(content, str):
        content = content.encode("utf-8")
    media_folder = "images" if media_type == "image" else "videos"
    key = (
        f"products/{product_id}/{media_folder}/"
        f"{uuid.uuid4().hex}-{safe_filename(filename)}"
    )
    client = get_media_s3_client(config)
    client.put_object(
        Bucket=config["bucket"],
        Key=key,
        Body=content,
        ContentType=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        CacheControl="public, max-age=31536000, immutable",
    )
    if media_type == "image":
        thumbnail = create_thumbnail(content)
        if thumbnail:
            thumbnail_key = thumbnail_key_for(key)
            if thumbnail_key:
                try:
                    client.put_object(
                        Bucket=config["bucket"],
                        Key=thumbnail_key,
                        Body=thumbnail,
                        ContentType="image/webp",
                        CacheControl="public, max-age=31536000, immutable",
                    )
                except Exception:
                    pass
    return public_s3_url(config["bucket"], config["region"], key), key


def delete_media_url(data_url):
    if not data_url or data_url.startswith("data:"):
        return
    config = load_media_config()
    key = extract_s3_key(data_url, config["bucket"])
    if not key:
        return
    get_media_s3_client(config).delete_object(
        Bucket=config["bucket"],
        Key=key,
    )
    thumbnail_key = thumbnail_key_for(key)
    if thumbnail_key:
        get_media_s3_client(config).delete_object(
            Bucket=config["bucket"],
            Key=thumbnail_key,
        )
