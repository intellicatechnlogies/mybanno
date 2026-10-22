from decimal import Decimal, InvalidOperation
from functools import wraps
import time

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import BooleanField, DecimalField, Q
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce, Lower
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from werkzeug.security import check_password_hash as check_legacy_password_hash

from .forms import (
    CheckoutForm,
    DEFAULT_COLOR_VALUES,
    DEFAULT_PRODUCT_NAMES,
    DEFAULT_SIZES,
    OrderUpdateForm,
    ProductForm,
)
from .models import AdminAccount, Product, ShopOrder, ShopOrderItem
from .product_names import product_name_options, remove_product_name_option

PRODUCT_BATCH_SIZE = 5


def admin_required(view):
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if "admin_id" not in request.session:
            messages.warning(request, "Please log in to access the admin area.")
            login_url = reverse("admin_login")
            return redirect(f"{login_url}?next={request.path}")
        return view(request, *args, **kwargs)

    return wrapped_view


def verify_admin_password(password, encoded):
    try:
        if check_password(password, encoded):
            return True
    except ValueError:
        pass
    try:
        return check_legacy_password_hash(encoded, password)
    except (TypeError, ValueError):
        return False


def catalog_query(request, offset=0):
    args = request.GET
    query = args.get("q", "").strip()
    category = args.get("category", "").strip()
    cloth_type = args.get("cloth_type", "").strip()
    occasion_category = args.get("occasion", "").strip()
    size = args.get("size", "").strip()
    offer_only = args.get("offer", "").strip()
    min_price = args.get("min_price", "").strip()
    max_price = args.get("max_price", "").strip()
    sort = args.get("sort", "newest")

    effective_price = Coalesce(
        "offer_price",
        "actual_price",
        "price",
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    products = Product.objects.annotate(effective_price=effective_price).prefetch_related("media_items")
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(cloth_type__icontains=query)
            | Q(category__icontains=query)
            | Q(occasion_category__icontains=query)
            | Q(description__icontains=query)
        )
    if category:
        products = products.filter(category=category)
    if cloth_type:
        products = products.filter(cloth_type=cloth_type)
    if occasion_category:
        products = products.filter(occasion_category=occasion_category)
    if size:
        products = products.filter(
            RawSQL(
                "(',' || replace(sizes, ' ', '') || ',') LIKE %s",
                (f"%,{size.replace(' ', '')},%",),
                output_field=BooleanField(),
            )
        )
    if offer_only == "1":
        products = products.filter(Q(on_offer=True) | Q(offer_price__isnull=False))
    for label, value, lookup in (
        ("Minimum", min_price, "gte"),
        ("Maximum", max_price, "lte"),
    ):
        if value:
            try:
                price = Decimal(value)
                if not price.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                messages.warning(request, f"{label} price was ignored because it is not a number.")
                continue
            products = products.filter(**{f"effective_price__{lookup}": price})

    if sort == "price_low":
        products = products.order_by("effective_price")
    elif sort == "price_high":
        products = products.order_by("-effective_price")
    elif sort == "name":
        products = products.order_by(Lower("name"))
    else:
        products = products.order_by("-created_at")

    batch = list(products[offset : offset + PRODUCT_BATCH_SIZE + 1])
    page_products = batch[:PRODUCT_BATCH_SIZE]
    add_remaining_stock(page_products, request.session.get("shop_cart", {}))
    return page_products, len(batch) > PRODUCT_BATCH_SIZE


def add_remaining_stock(products, cart):
    cart = cart if isinstance(cart, dict) else {}
    quantities_by_product = {}
    for item in cart.values():
        if not isinstance(item, dict):
            continue
        try:
            product_id = int(item.get("product_id", ""))
            quantity = max(0, int(item.get("quantity", 0)))
        except (TypeError, ValueError):
            continue
        quantities = quantities_by_product.setdefault(product_id, {})
        key = (str(item.get("color", "")).strip(), str(item.get("size", "")).strip())
        quantities[key] = quantities.get(key, 0) + quantity

    for product in products:
        reserved = quantities_by_product.get(product.pk, {})
        if product.colors:
            color_stock = {
                color: {
                    size: max(
                        0,
                        product.stock_for_size(size, color) - reserved.get((color, size), 0),
                    )
                    for size in product.size_list
                }
                for color in product.colors
            }
            size_stock = {
                size: sum(inventory.get(size, 0) for inventory in color_stock.values())
                for size in product.size_list
            }
            product.remaining_color_stock = color_stock
            product.available_size_inventory = [
                {"size": size, "stock": stock}
                for size, stock in size_stock.items()
            ]
            product.available_stock = sum(size_stock.values())
        elif product.has_size_stock:
            size_stock = {
                size: max(0, product.stock_for_size(size) - reserved.get(("", size), 0))
                for size in product.size_list
            }
            product.available_size_inventory = [
                {"size": size, "stock": stock}
                for size, stock in size_stock.items()
            ]
            product.available_stock = sum(size_stock.values())
        else:
            product.available_size_inventory = []
            product.available_stock = max(0, product.total_stock - sum(
                quantity for (color, _size), quantity in reserved.items()
            ))


def index(request):
    products, has_more = catalog_query(request)
    return render(
        request,
        "index.html",
        {
            "products": products,
            "has_more": has_more,
            "sale_active": Product.objects.filter(
                Q(on_offer=True) | Q(offer_price__isnull=False)
            ).exists(),
            "categories": Product.objects.exclude(category="").values_list("category", flat=True).distinct().order_by(Lower("category")),
        },
    )


def more_products(request):
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        offset = 0
    products, has_more = catalog_query(request, offset=offset)
    response = render(request, "_product_cards.html", {"products": products})
    response["X-Has-More"] = "1" if has_more else "0"
    return response


def product_detail(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related("media_items"),
        pk=product_id,
    )
    return render(
        request,
        "product_detail.html",
        {
            "product": product,
            "gallery_items": product.gallery_items,
        },
    )


def product_modal_data(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related("media_items"),
        pk=product_id,
    )
    add_remaining_stock([product], request.session.get("shop_cart", {}))
    available_colors = [
        color
        for color in product.color_options
        if any(product.remaining_color_stock.get(color["name"], {}).values())
    ]
    return JsonResponse(
        {
            "id": product.pk,
            "name": product.name,
            "category": product.category,
            "cloth_type": product.cloth_type,
            "occasion_category": product.occasion_category,
            "description": product.description
            or "A carefully selected piece for your everyday wardrobe.",
            "price": str(
                product.actual_price if product.actual_price is not None else product.price
            ),
            "offer_price": str(product.offer_price) if product.offer_price is not None else "",
            "discount_percentage": product.discount_percentage,
            "stock": product.available_stock,
            "sizes": product.size_list,
            "size_stock": {
                entry["size"]: entry["stock"]
                for entry in product.available_size_inventory
            },
            "colors": available_colors,
            "color_stock": product.remaining_color_stock
            if product.colors
            else {},
            "media": [
                {
                    "type": media["media_type"],
                    "src": media["data_url"],
                    "color": media["color"],
                }
                for media in product.gallery_items
            ],
        }
    )


def cart_add(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        product_id = int(request.POST.get("product_id", ""))
        quantity = int(request.POST.get("quantity", "1"))
    except ValueError:
        return JsonResponse({"error": "Choose a valid product and quantity."}, status=400)

    product = Product.objects.prefetch_related("media_items").filter(pk=product_id).first()
    if product is None:
        return JsonResponse({"error": "This product is no longer available."}, status=404)
    size = request.POST.get("size", "").strip()
    color = request.POST.get("color", "").strip()
    cart = request.session.get("shop_cart", {})
    cart = cart if isinstance(cart, dict) else {}
    add_remaining_stock([product], cart)
    available_colors = [
        product_color for product_color in product.colors
        if any(product.remaining_color_stock.get(product_color, {}).values())
    ]
    if len(available_colors) > 1 and color not in available_colors:
        return JsonResponse({"error": "Choose an available color."}, status=400)
    if len(available_colors) == 1:
        if color and color not in available_colors:
            return JsonResponse({"error": "Choose an available color."}, status=400)
        color = color or available_colors[0]
    elif color not in product.colors and available_colors:
        return JsonResponse({"error": "Choose an available color."}, status=400)
    elif not product.colors:
        color = ""
    if product.size_list and size not in product.size_list:
        return JsonResponse({"error": "Choose an available size."}, status=400)
    if quantity < 1:
        return JsonResponse({"error": "Quantity must be at least 1."}, status=400)

    product_quantity = sum(
        int(item.get("quantity", 0))
        for item in cart.values()
        if isinstance(item, dict)
        and str(item.get("product_id")) == str(product.pk)
        and (
            not product.has_size_stock
            or (
                str(item.get("size", "")).strip() == size
                and str(item.get("color", "")).strip() == color
            )
        )
    )
    size_stock = product.stock_for_size(size, color if product.colors else None)
    if product_quantity + quantity > size_stock:
        return JsonResponse(
            {"error": f"Only {max(0, size_stock - product_quantity)} more available."},
            status=400,
        )

    key = f"{product.pk}|{color}|{size}" if product.colors else f"{product.pk}|{size}"
    existing = cart.get(key, {})
    cart[key] = {
        "product_id": product.pk,
        "color": color,
        "color_code": product.color_value_for(color),
        "size": size,
        "quantity": int(existing.get("quantity", 0)) + quantity,
    }
    request.session["shop_cart"] = cart
    return JsonResponse(
        {
            "message": (
                f"{product.name} · {color}{' · ' + size if size else ''} added to cart."
                if color
                else f"{product.name}{' · ' + size if size else ''} added to cart."
            ),
            "color": color,
            "color_code": product.color_value_for(color),
            "cart_count": sum(int(item["quantity"]) for item in cart.values()),
        }
    )


def cart(request):
    cart_data = request.session.get("shop_cart", {})
    cart_data = cart_data if isinstance(cart_data, dict) else {}
    products = {
        product.pk: product
        for product in Product.objects.filter(
            pk__in=[
                item.get("product_id")
                for item in cart_data.values()
                if isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
            ]
        ).prefetch_related("media_items")
    }
    items = []
    cleaned_cart = {}
    subtotal = Decimal("0.00")
    for key, cart_item in cart_data.items():
        if not isinstance(cart_item, dict):
            continue
        product = products.get(cart_item.get("product_id"))
        if product is None:
            continue
        try:
            quantity = int(cart_item.get("quantity", 0))
        except (ValueError, TypeError):
            continue
        if quantity < 1:
            continue
        unit_price = (
            product.offer_price
            if product.offer_price is not None
            else product.actual_price
            if product.actual_price is not None
            else product.price
        )
        line_total = unit_price * quantity
        subtotal += line_total
        cleaned_cart[key] = cart_item
        items.append(
            {
                "key": key,
                "product": product,
                "media": product.media_for_color(cart_item.get("color", "")),
                "color": cart_item.get("color", ""),
                "color_code": cart_item.get("color_code")
                or product.color_value_for(cart_item.get("color", "")),
                "size": cart_item.get("size", ""),
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "max_quantity": product.stock_for_size(
                    cart_item.get("size", ""),
                    cart_item.get("color") if product.colors else None,
                ),
            }
        )
    if cleaned_cart != cart_data:
        request.session["shop_cart"] = cleaned_cart

    if request.method == "POST":
        action = request.POST.get("action")
        key = request.POST.get("key", "")
        if action == "remove":
            cleaned_cart.pop(key, None)
        elif action == "update" and key in cleaned_cart:
            try:
                quantity = int(request.POST.get("quantity", ""))
            except ValueError:
                quantity = 0
            item = cleaned_cart[key]
            product = products.get(item.get("product_id"))
            other_quantity = sum(
                int(other.get("quantity", 0))
                for other_key, other in cleaned_cart.items()
                if other_key != key
                and isinstance(other, dict)
                and str(other.get("product_id")) == str(item.get("product_id"))
                and (
                    not product
                    or not product.has_size_stock
                    or (
                        str(other.get("size", "")).strip()
                        == str(item.get("size", "")).strip()
                        and str(other.get("color", "")).strip()
                        == str(item.get("color", "")).strip()
                    )
                )
            )
            max_quantity = (
                product.stock_for_size(
                    item.get("size", ""),
                    item.get("color") if product.colors else None,
                )
                if product else 0
            )
            if quantity < 1:
                messages.error(request, "Quantity must be at least 1.")
            elif product is None or other_quantity + quantity > max_quantity:
                messages.error(request, "Requested quantity exceeds available stock.")
            else:
                item["quantity"] = quantity
        request.session["shop_cart"] = cleaned_cart
        return redirect("cart")

    return render(request, "cart.html", {"items": items, "subtotal": subtotal})


def checkout(request):
    cart_data = request.session.get("shop_cart", {})
    cart_data = cart_data if isinstance(cart_data, dict) else {}
    if not cart_data:
        messages.info(request, "Add a product to your cart before checkout.")
        return redirect("cart")

    checkout_products = {
        product.pk: product
        for product in Product.objects.filter(
            pk__in=[
                item.get("product_id")
                for item in cart_data.values()
                if isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
            ]
        )
    }
    checkout_subtotal = Decimal("0.00")
    for cart_item in cart_data.values():
        if not isinstance(cart_item, dict):
            continue
        product = checkout_products.get(cart_item.get("product_id"))
        try:
            quantity = int(cart_item.get("quantity", 0))
        except (ValueError, TypeError):
            continue
        if product is None or quantity < 1:
            continue
        unit_price = (
            product.offer_price
            if product.offer_price is not None
            else product.actual_price
            if product.actual_price is not None
            else product.price
        )
        checkout_subtotal += unit_price * quantity

    form = CheckoutForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product_ids = {
            item.get("product_id")
            for item in cart_data.values()
            if isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
        }
        order = None
        stock_error = None
        with transaction.atomic():
            products = {
                product.pk: product
                for product in Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")
            }
            valid_items = []
            reserved_stock = {}
            for item in cart_data.values():
                if not isinstance(item, dict):
                    stock_error = "Your cart contains an invalid item. Please review it and try again."
                    break
                product = products.get(item.get("product_id"))
                try:
                    quantity = int(item.get("quantity", 0))
                except (ValueError, TypeError):
                    quantity = 0
                size = str(item.get("size", "")).strip()
                color = str(item.get("color", "")).strip()
                if product is None or quantity < 1:
                    stock_error = "A product in your cart is no longer available. Please review your cart."
                    break
                if product.colors and color not in product.colors:
                    stock_error = f"Please review the color selected for {product.name}."
                    break
                if product.size_list and size not in product.size_list:
                    stock_error = f"Please review the size selected for {product.name}."
                    break
                stock_key = (
                    product.pk,
                    color if product.colors else "",
                    size if product.has_size_stock else "",
                )
                product_reserved = reserved_stock.get(stock_key, 0)
                size_stock = product.stock_for_size(size, color if product.colors else None)
                if product_reserved + quantity > size_stock:
                    available = max(0, size_stock - product_reserved)
                    stock_error = f"Only {available} of {product.name} are currently available."
                    break
                unit_price = (
                    product.offer_price
                    if product.offer_price is not None
                    else product.actual_price
                    if product.actual_price is not None
                    else product.price
                )
                valid_items.append((product, color, size, quantity, unit_price))
                reserved_stock[stock_key] = product_reserved + quantity

            if stock_error is None and valid_items:
                subtotal = sum(
                    (unit_price * quantity for _, _, _, quantity, unit_price in valid_items),
                    Decimal("0.00"),
                )
                order = ShopOrder.objects.create(
                    mobile_number=form.cleaned_data["mobile_number"],
                    delivery_address=form.formatted_delivery_address(),
                    subtotal=subtotal,
                )
                for product, color, size, quantity, unit_price in valid_items:
                    ShopOrderItem.objects.create(
                        order=order,
                        product=product,
                        product_name=product.name,
                        color=color,
                        color_code=product.color_value_for(color),
                        size=size,
                        quantity=quantity,
                        unit_price=unit_price,
                    )
                    if product.colors:
                        product.color_stock[color][size] = product.stock_for_size(
                            size, color
                        ) - quantity
                        product.size_stock = {
                            stock_size: product.stock_for_size(stock_size)
                            for stock_size in product.size_list
                        }
                        product.stock = product.total_stock
                        product.save(update_fields=["color_stock", "size_stock", "stock"])
                    elif product.has_size_stock:
                        product.size_stock[size] = product.stock_for_size(size) - quantity
                        product.stock = product.total_stock
                        product.save(update_fields=["size_stock", "stock"])
                    else:
                        product.stock -= quantity
                        product.save(update_fields=["stock"])

        if stock_error:
            messages.error(request, stock_error)
            return redirect("cart")
        if order is not None:
            request.session["shop_cart"] = {}
            request.session["last_order_id"] = order.pk
            return redirect("checkout_complete")

    return render(
        request,
        "checkout.html",
        {"form": form, "checkout_subtotal": checkout_subtotal},
    )


def checkout_complete(request):
    order_id = request.session.get("last_order_id")
    if not order_id:
        return redirect("index")
    order = get_object_or_404(ShopOrder.objects.prefetch_related("items"), pk=order_id)
    return render(request, "checkout_complete.html", {"order": order})


def admin_login(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        account = AdminAccount.objects.filter(username=username).first()
        if account and verify_admin_password(password, account.password_hash):
            if not account.password_hash.startswith(("pbkdf2_sha256$", "argon2$", "bcrypt$", "scrypt$")):
                account.password_hash = make_password(password)
                account.save(update_fields=["password_hash"])
            request.session.flush()
            request.session["admin_id"] = account.pk
            request.session["admin_username"] = account.username
            request.session["admin_last_activity"] = time.time()
            next_url = request.GET.get("next", "")
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect("admin_dashboard")
        messages.error(request, "Invalid username or password.")
    return render(request, "admin_login.html")


def admin_logout(request):
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect("index")


@admin_required
def admin_dashboard(request):
    products = Product.objects.prefetch_related("media_items").order_by("-created_at")
    return render(
        request,
        "admin_dashboard.html",
        {
            "products": products,
            "product_names": product_name_options(DEFAULT_PRODUCT_NAMES),
        },
    )


@admin_required
def delete_product_name_option(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    name = request.POST.get("name", "").strip()
    if not name or name not in product_name_options(DEFAULT_PRODUCT_NAMES):
        messages.error(request, "Choose a valid product name option.")
    else:
        remove_product_name_option(name)
        messages.success(request, f'"{name}" was removed from the product name options.')
    return redirect("admin_dashboard")


@admin_required
def admin_orders(request):
    status_filter = request.GET.get("status", "").strip()
    valid_statuses = {value for value, _ in ShopOrder.Status.choices}
    if status_filter and status_filter not in valid_statuses:
        messages.warning(request, "The selected order status is not valid.")
        status_filter = ""

    orders = ShopOrder.objects.prefetch_related("items").order_by("created_at", "pk")
    if status_filter:
        orders = orders.filter(status=status_filter)
    page = Paginator(orders, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "admin_orders.html",
        {
            "page": page,
            "status_filter": status_filter,
            "status_choices": ShopOrder.Status.choices,
        },
    )


@admin_required
def admin_order_update(request, order_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    order = get_object_or_404(ShopOrder, pk=order_id)
    form = OrderUpdateForm(request.POST)
    return_status = request.POST.get("return_status", "").strip()
    valid_statuses = {value for value, _ in ShopOrder.Status.choices}
    if return_status not in valid_statuses:
        return_status = ""

    if form.is_valid():
        order.status = form.cleaned_data["status"]
        order.remarks = form.cleaned_data["remarks"].strip()
        order.save(update_fields=["status", "remarks"])
        messages.success(request, f"Order #{order.pk} was updated.")
    else:
        messages.error(request, "Please choose a valid status and enter remarks up to 2000 characters.")

    url = reverse("admin_orders")
    if return_status:
        url = f"{url}?status={return_status}"
    return redirect(url)


@admin_required
def admin_order_delete(request, order_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    order = get_object_or_404(ShopOrder, pk=order_id)
    order_id = order.pk
    order.delete()
    messages.success(request, f"Order #{order_id} was deleted.")

    return_status = request.POST.get("return_status", "").strip()
    valid_statuses = {value for value, _ in ShopOrder.Status.choices}
    url = reverse("admin_orders")
    if return_status in valid_statuses:
        url = f"{url}?status={return_status}"
    return redirect(url)


def render_product_form(request, form, product, page_title):
    if form.is_bound and not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    name_choice = form["name"].value() or ""
    cloth_type_choice = form["cloth_type"].value() or ""
    category_choice = form["category"].value() or ""
    selected_sizes = form["sizes"].value() or []
    color_stock_options = [
        {
            "color": color,
            "value": (
                product.color_value_for(color)
                if product
                else DEFAULT_COLOR_VALUES.get(color.casefold(), "#b8b8b8")
            ),
            "index": color_index,
        }
        for color_index, color in enumerate(form.color_names)
    ]
    product_values = {
        "name": form["name_other"].value() if name_choice == "__other__" else name_choice,
        "name_choice": name_choice,
        "name_other": form["name_other"].value() or "",
        "cloth_type": cloth_type_choice,
        "cloth_type_choice": cloth_type_choice,
        "cloth_type_other": form["cloth_type_other"].value() or "",
        "category": category_choice,
        "category_choice": category_choice,
        "category_other": form["category_other"].value() or "",
        "occasion_category": form["occasion_category"].value() or "",
        "occasion_category_other": form["occasion_category_other"].value() or "",
        "description": form["description"].value() or "",
        "actual_price": form["actual_price"].value() or "",
        "offer_price": form["offer_price"].value() or "",
        "stock": form["stock"].value() or "0",
        "image_color": form["image_color"].value() or "",
        "sizes": ", ".join(selected_sizes),
        "on_offer": "on" if form["on_offer"].value() else "",
        "image_data": product.image_data if product else "",
        "has_images": bool(product and (
            product.image_data or any(item["media_type"] == "image" for item in product.gallery_items)
        )),
        "gallery_items": product.gallery_items if product else [],
        "id": product.pk if product else None,
    }
    return render(
        request,
        "product_form.html",
        {
            "product": product_values,
            "form": form,
            "page_title": page_title,
            "product_names": form.fields["name"].choices[1:-1],
            "cloth_types": form.fields["cloth_type"].choices[1:-1],
            "categories": form.fields["category"].choices[1:-1],
            "occasions": form.fields["occasion_category"].choices[1:-1],
            "sizes": DEFAULT_SIZES,
            "selected_sizes": selected_sizes,
            "color_stock_options": color_stock_options,
            "size_color_options": [
                {
                    "size": size,
                    "index": size_index,
                    "selected": size in selected_sizes,
                    "legacy_stock": (
                        product.stock_for_size(size)
                        if product and product.has_size_stock and not product.colors
                        else 0
                    ),
                    "has_color_selection": any(
                        bool(form[f"size_color_{size_index}_{color_index}"].value())
                        for color_index in range(len(form.color_names))
                    ),
                    "total_quantity": sum(
                        safe_quantity_value(
                            form[f"color_stock_{size_index}_{color_index}"].value()
                        )
                        for color_index in range(len(form.color_names))
                        if form[f"size_color_{size_index}_{color_index}"].value()
                    ),
                    "colors": [
                        {
                            **color_option,
                            "field_name": f"size_color_{size_index}_{color_option['index']}",
                            "quantity_field_name": f"color_stock_{size_index}_{color_option['index']}",
                            "selected": bool(form[f"size_color_{size_index}_{color_option['index']}"].value()),
                            "quantity": form[f"color_stock_{size_index}_{color_option['index']}"].value() or "0",
                        }
                        for color_option in color_stock_options
                    ],
                }
                for size_index, size in enumerate(DEFAULT_SIZES)
            ],
        },
    )


def safe_quantity_value(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@admin_required
def create_product(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product created successfully.")
        return redirect("admin_dashboard")
    return render_product_form(request, form, None, "Add product")


@admin_required
def edit_product(request, product_id):
    product = get_object_or_404(Product.objects.prefetch_related("media_items"), pk=product_id)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product updated successfully.")
        return redirect("admin_dashboard")
    return render_product_form(request, form, product, "Edit product")


@admin_required
def delete_product(request, product_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    get_object_or_404(Product, pk=product_id).delete()
    messages.success(request, "Product deleted.")
    return redirect("admin_dashboard")
