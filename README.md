# Thread & Co. clothing store

A Django and SQLite clothing catalog. Visitors can search, filter, and browse products; admins can sign in to add, edit, and delete products with photos.

## Run locally (Windows)

1. Create a virtual environment: `py -m venv .venv`
2. Activate it: `.venv\\Scripts\\activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Apply database migrations: `py manage.py migrate`
5. Start the app: `py manage.py runserver`
6. Open http://127.0.0.1:8000

For deployment, collect static assets into `staticfiles/` with `py manage.py collectstatic`. Django writes this directory using the `STATIC_ROOT` setting.

The existing `store.db` database is retained. The first migration copies existing products and admin accounts into Django-managed tables without deleting the original tables. Existing Werkzeug password hashes are accepted at sign-in and upgraded to Django's password hash format after a successful login. The local admin account uses username `test` and password `test`; the password is stored as a secure hash, not as plaintext. Change it before deployment.

Product photos and videos are stored in the SQLite database as base64 data URLs. Admins can upload multiple JPEG, PNG, or WebP photos and MP4, WebM, or MOV videos for each product. Each file is limited to 5 MB. Existing product photos remain in the database.

Products can be tagged with an occasion (such as Casual, Office, Party, Wedding, Festive, or Vacation). Occasion tags can also be added as custom options and are available in the shop filters and search.

The product-name choices are hardcoded in the product form and do not come from saved products. A name entered with “Other” is saved only on that individual product and is not added to the choices. Admins can remove a hardcoded product-name option from the dashboard without changing existing products; removals are kept outside the database in `.product-name-catalog.json` (or the path set by `PRODUCT_NAME_CATALOG_PATH`). Other catalog options are unchanged.

Admins choose sizes from a single horizontal row and select colors from searchable checkboxes within each size. Stock is entered per selected size/color combination, and each size total and product total are calculated automatically from those color quantities. Uploaded photos can optionally be associated with a color so selecting that swatch opens its photo; new uploads offer color associations even when added before choosing inventory variants. Shop and product-modal stock counts subtract quantities already in the visitor's cart, and unavailable color/size choices are disabled or hidden. Cart and order details show the swatch and color name, with the chosen color and size saved on each order item.

Set a strong `SECRET_KEY`, `DEBUG=False`, and suitable `ALLOWED_HOSTS` values before deploying publicly.

## AWS S3 database backups

Keep AWS credentials and bucket settings in `aws.json`:

```json
{
  "Access_key_ID": "your-access-key-id",
  "Secret_Access_Key": "your-secret-access-key",
  "Region": "ap-southeast-2",
  "Bucket": "your-bucket-name"
}
```

`aws.json` is ignored by Git. Upload one backup immediately with:

```powershell
.venv\Scripts\python.exe manage.py backup_store_db_s3
```

For a local/test upload, add an explicit source label:

```powershell
.venv\Scripts\python.exe manage.py backup_store_db_s3 --source local
```

The application uploads a consistent SQLite snapshot immediately at startup and every 10 minutes. It uploads one complete backup object, with boto3 multipart transfer for large databases:

- Local: `backups/local/store.db-YYYYMMDD-HHMMSS-microseconds.db`
- Server: `backups/server/store.db-YYYYMMDD-HHMMSS-microseconds.db`
- Test/other explicit source: `backups/test/store.db-...db`

Each backup cycle uploads exactly one database file. Backups older than 48 hours are deleted automatically. Local and server backups are stored in separate folders so they are easy to verify.

Set `MYBANNO_DISABLE_S3_BACKUP=1` to disable automatic uploads. The worker interval can be changed with `MYBANNO_S3_BACKUP_INTERVAL_SECONDS`.

Automatic workers check the newest existing S3 backup before uploading. If one is less than the configured interval old, the worker skips that cycle. This prevents multiple Django/Gunicorn worker processes from creating extra backups during simultaneous startup. The manual backup command always uploads explicitly and does not apply the automatic cooldown.

Automatic workers also acquire a short-lived conditional S3 lock before checking the 10-minute schedule. Only one process can create the lock, so another worker cannot run a duplicate backup at startup. The lock is released after the upload or failure.

The AWS IAM identity needs `s3:ListBucket` for the bucket so it can identify and delete database backups older than 48 hours, plus `s3:PutObject` for uploads and `s3:DeleteObject` for retention cleanup.

## Product image and video storage

New product images and videos are uploaded to the `Clothimg_bucket` configured in `aws.json` and stored as S3 URLs in the existing `Product.image_data` and `ProductMedia.data_url` fields:

- Images: `products/<product-id>/images/<unique-file-name>`
- Videos: `products/<product-id>/videos/<unique-file-name>`

The existing product, color, filename, sort order, and media relationships are not changed.

Preview the base64-to-S3 conversion without changing data:

```powershell
python manage.py migrate_product_media_to_s3 --dry-run
```

Run the conversion after configuring valid AWS credentials and S3 permissions:

```powershell
python manage.py migrate_product_media_to_s3
```
