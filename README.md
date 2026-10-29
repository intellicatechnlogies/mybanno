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

## Email database backups on Windows

Create `.venv` and install dependencies first. Then keep the Gmail SMTP/IMAP account details in `email.json` (this file is intentionally ignored by Git):

```json
{
  "App_Password": "your-gmail-app-password",
  "SMTP_Server": "smtp.gmail.com",
  "Port": 587,
  "Email": "your-address@gmail.com"
}
```

Send one backup now with:

```powershell
.venv\Scripts\python.exe manage.py backup_store_db
```

The command creates a consistent SQLite snapshot and emails it from and to the configured address. Django also starts a background worker for `runserver` and production WSGI startup. It sends immediately and every 10 minutes by default. Set `MYBANNO_BACKUP_INTERVAL_SECONDS` to change the interval, or set `MYBANNO_DISABLE_EMAIL_BACKUP=1` to disable it. Backups larger than Gmail's attachment limit are split into 18 MB email parts automatically. Management commands, migrations, and static collection do not start the worker.

The existing `store.db` database is retained. The first migration copies existing products and admin accounts into Django-managed tables without deleting the original tables. Existing Werkzeug password hashes are accepted at sign-in and upgraded to Django's password hash format after a successful login. The local admin account uses username `test` and password `test`; the password is stored as a secure hash, not as plaintext. Change it before deployment.

Product photos and videos are stored in the SQLite database as base64 data URLs. Admins can upload multiple JPEG, PNG, or WebP photos and MP4, WebM, or MOV videos for each product. Each file is limited to 5 MB. Existing product photos remain in the database.

Products can be tagged with an occasion (such as Casual, Office, Party, Wedding, Festive, or Vacation). Occasion tags can also be added as custom options and are available in the shop filters and search.

The product-name choices are hardcoded in the product form and do not come from saved products. A name entered with “Other” is saved only on that individual product and is not added to the choices. Admins can remove a hardcoded product-name option from the dashboard without changing existing products; removals are kept outside the database in `.product-name-catalog.json` (or the path set by `PRODUCT_NAME_CATALOG_PATH`). Other catalog options are unchanged.

Admins choose sizes from a single horizontal row and select colors from searchable checkboxes within each size. Stock is entered per selected size/color combination, and each size total and product total are calculated automatically from those color quantities. Uploaded photos can optionally be associated with a color so selecting that swatch opens its photo; new uploads offer color associations even when added before choosing inventory variants. Shop and product-modal stock counts subtract quantities already in the visitor's cart, and unavailable color/size choices are disabled or hidden. Cart and order details show the swatch and color name, with the chosen color and size saved on each order item.

Set a strong `SECRET_KEY`, `DEBUG=False`, and suitable `ALLOWED_HOSTS` values before deploying publicly.
