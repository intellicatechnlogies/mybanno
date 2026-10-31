import base64
import binascii
import mimetypes
import re

from django.core.management.base import BaseCommand, CommandError

from store.models import Product, ProductMedia
from store.s3_media import MediaStorageError, upload_media


DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.*)$", re.DOTALL)


class Command(BaseCommand):
    help = "Convert existing base64 product images/videos into files in the S3 media bucket"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many records need migration without uploading",
        )

    def decode_data_url(self, data_url):
        match = DATA_URL_PATTERN.match(data_url or "")
        if not match:
            return None
        try:
            content = base64.b64decode(match.group("data"), validate=True)
        except (binascii.Error, ValueError):
            return None
        return match.group("mime"), content

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        converted = 0
        skipped = 0

        try:
            for product in Product.objects.all().iterator(chunk_size=100):
                if product.image_data and (product.image_data.startswith("data:")):
                    if dry_run:
                        converted += 1
                    else:
                        decoded = self.decode_data_url(product.image_data)
                        if decoded:
                            mime_type, content = decoded
                            extension = mimetypes.guess_extension(mime_type) or ".bin"
                            url, _ = upload_media(
                                product.pk,
                                ProductMedia.IMAGE,
                                f"legacy-product-photo{extension}",
                                mime_type,
                                content,
                            )
                            product.image_data = url
                            product.save(update_fields=["image_data"])
                            converted += 1
                        else:
                            skipped += 1

                for media in product.media_items.iterator():
                    if not media.data_url.startswith("data:"):
                        continue
                    if dry_run:
                        converted += 1
                        continue
                    decoded = self.decode_data_url(media.data_url)
                    if not decoded:
                        skipped += 1
                        continue
                    mime_type, content = decoded
                    extension = mimetypes.guess_extension(mime_type) or ".bin"
                    filename = media.filename or f"legacy-{media.media_type}{extension}"
                    url, _ = upload_media(
                        product.pk,
                        media.media_type,
                        filename,
                        mime_type,
                        content,
                    )
                    media.data_url = url
                    media.save(update_fields=["data_url"])
                    converted += 1
        except MediaStorageError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"Media migration failed: {exc}") from exc

        action = "would convert" if dry_run else "converted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {converted} legacy media record(s); skipped {skipped}"
            )
        )
