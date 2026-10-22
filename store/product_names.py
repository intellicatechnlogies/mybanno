import json
import threading
from pathlib import Path

from django.conf import settings

from .models import Product


_catalog_lock = threading.Lock()


def _catalog_path():
    return Path(
        getattr(
            settings,
            "PRODUCT_NAME_CATALOG_PATH",
            Path(settings.BASE_DIR) / ".product-name-catalog.json",
        )
    )


def _read_catalog():
    try:
        return json.loads(_catalog_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"removed_names": []}
    except (json.JSONDecodeError, OSError):
        return {"removed_names": []}


def _write_catalog(catalog):
    path = _catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(json.dumps(catalog), encoding="utf-8")
    temporary_path.replace(path)


def product_name_options(default_names):
    with _catalog_lock:
        catalog = _read_catalog()
    removed_names = {name.casefold() for name in catalog.get("removed_names", [])}
    return sorted(
        (name for name in default_names if name.casefold() not in removed_names),
        key=str.casefold,
    )


def remove_product_name_option(name):
    with _catalog_lock:
        catalog = _read_catalog()
        removed_names = {
            value.casefold(): value
            for value in catalog.get("removed_names", [])
        }
        removed_names[name.casefold()] = name
        catalog["removed_names"] = sorted(removed_names.values(), key=str.casefold)
        _write_catalog(catalog)
