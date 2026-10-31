import mimetypes
import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from store.models import Product, ProductMedia
from store.s3_media import (
    create_thumbnail,
    extract_s3_key,
    get_media_s3_client,
    load_media_config,
    thumbnail_key_for,
)


class Command(BaseCommand):
    help = "Generate optimized WebP thumbnails for existing S3 product images"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Replace existing thumbnails")

    def handle(self, *args, **options):
        try:
            config = load_media_config()
            client = get_media_s3_client(config)
            urls = set()
            cache_dir = Path(settings.BASE_DIR) / ".media-cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            for product in Product.objects.all().iterator(chunk_size=100):
                if product.image_data:
                    urls.add(product.image_data)
                for media in product.media_items.filter(media_type=ProductMedia.IMAGE).iterator():
                    urls.add(media.data_url)

            generated = 0
            skipped = 0
            for url in urls:
                original_key = extract_s3_key(url, config["bucket"])
                thumbnail_key = thumbnail_key_for(original_key)
                if not original_key or not thumbnail_key:
                    skipped += 1
                    continue

                if not options["force"]:
                    try:
                        client.head_object(Bucket=config["bucket"], Key=thumbnail_key)
                        try:
                            cached = client.get_object(Bucket=config["bucket"], Key=thumbnail_key)
                            cache_name = hashlib.sha256(thumbnail_key.encode("utf-8")).hexdigest() + ".webp"
                            cache_dir.joinpath(cache_name).write_bytes(cached["Body"].read())
                        except Exception:
                            pass
                        skipped += 1
                        continue
                    except Exception:
                        pass

                original = client.get_object(Bucket=config["bucket"], Key=original_key)
                content = original["Body"].read()
                thumbnail = create_thumbnail(content)
                if not thumbnail:
                    skipped += 1
                    continue

                client.put_object(
                    Bucket=config["bucket"],
                    Key=thumbnail_key,
                    Body=thumbnail,
                    ContentType="image/webp",
                    CacheControl="public, max-age=31536000, immutable",
                )
                cache_name = hashlib.sha256(thumbnail_key.encode("utf-8")).hexdigest() + ".webp"
                cache_dir.joinpath(cache_name).write_bytes(thumbnail)
                generated += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"generated {generated} thumbnail(s); skipped {skipped}"
                )
            )
        except Exception as exc:
            raise CommandError(f"Thumbnail generation failed: {exc}") from exc
