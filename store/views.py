from decimal import Decimal, InvalidOperation
from functools import wraps
import hashlib
import hmac
import json
import random
import time
from pathlib import Path
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import BooleanField, DecimalField, Q
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce, Lower
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.core.paginator import Paginator
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from werkzeug.security import check_password_hash as check_legacy_password_hash

from .forms import (
    CheckoutForm,
    CustomerLoginForm,
    CustomerSignupForm,
    DEFAULT_COLOR_VALUES,
    DEFAULT_PRODUCT_NAMES,
    DEFAULT_SIZES,
    OrderUpdateForm,
    ProductForm,
)
from .models import (
    AdminAccount,
    Credential,
    Customer,
    CustomerCartItem,
    Product,
    ShopOrder,
    ShopOrderItem,
)
from .product_names import product_name_options, remove_product_name_option
from .s3_media import delete_media_url, get_media_s3_client, load_media_config

PRODUCT_BATCH_SIZE = 50


@csrf_exempt
@require_POST
def add_credential(request):
    supplied_key = request.headers.get("X-API-Key", "")
    default_key = getattr(settings, "CREDENTIAL_API_KEY", "")
    if not supplied_key or not default_key or not hmac.compare_digest(supplied_key, default_key):
        return JsonResponse({"error": "Invalid or missing API key."}, status=401)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)

    service = str(payload.get("service", "")).strip()
    account = str(payload.get("account", "")).strip()
    credential_type = str(payload.get("credential_type", "")).strip()
    description = str(payload.get("description", "")).strip()
    plain_value = payload.get("value")

    if not service:
        return JsonResponse({"error": "service is required."}, status=400)
    if plain_value is None or not str(plain_value).strip():
        return JsonResponse({"error": "value is required."}, status=400)
    if len(service) > 100 or len(account) > 150 or len(credential_type) > 100 or len(description) > 500:
        return JsonResponse({"error": "One or more text fields exceed the allowed length."}, status=400)

    credential = Credential.objects.filter(
        service=service,
        account=account,
        credential_type=credential_type,
    ).first()
    created = credential is None
    if not created:
        credential.description = description
    else:
        credential = Credential(
            service=service,
            account=account,
            credential_type=credential_type,
            description=description,
        )
    credential.set_plain_value(str(plain_value))
    credential.updated_at = timezone.now()
    credential.save(update_fields=["encrypted_value", "description", "updated_at"] if not created else None)

    return JsonResponse(
        {
            "id": credential.pk,
            "service": credential.service,
            "account": credential.account,
            "credential_type": credential.credential_type,
            "description": credential.description,
            "created": created,
            "value": "encrypted",
        },
        status=201 if created else 200,
    )


def cached_thumbnail(request, key):
    normalized_key = str(key).replace("\\", "").strip("/")
    if not normalized_key.startswith("products/") or not normalized_key.endswith(".webp"):
        return HttpResponse("Invalid thumbnail path.", status=400)
    if "/thumbnails/" not in normalized_key:
        return HttpResponse("Invalid thumbnail path.", status=400)

    cache_dir = Path(settings.BASE_DIR) / ".media-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_name = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest() + ".webp"
    cache_path = cache_dir / cache_name

    if not cache_path.exists():
        try:
            config = load_media_config()
            response = get_media_s3_client(config).get_object(
                Bucket=config["bucket"],
                Key=normalized_key,
            )
            content = response["Body"].read()
            if not content:
                return HttpResponse("Thumbnail is empty.", status=404)
            temp_path = cache_path.with_suffix(".tmp")
            temp_path.write_bytes(content)
            temp_path.replace(cache_path)
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "NotFound", "404"):
                return HttpResponse("Thumbnail not found.", status=404)
            return HttpResponse("Could not load thumbnail.", status=502)

    response = FileResponse(cache_path.open("rb"), content_type="image/webp")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["ETag"] = '"' + hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()[:16] + '"'
    if request.method == "HEAD":
        response.close()
        return HttpResponse(
            status=200,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Type": "image/webp",
                "Content-Length": str(cache_path.stat().st_size),
                "ETag": '"' + hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()[:16] + '"',
            },
        )
    return response


def serve_s3_media(request, key):
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    normalized_key = str(key).replace("\\", "").strip("/")
    if not normalized_key.startswith(("products/", "images/", "videos/")):
        return HttpResponse("Invalid media path.", status=400)
    config = load_media_config()
    signed_url = get_media_s3_client(config).generate_presigned_url(
        "get_object",
        Params={"Bucket": config["bucket"], "Key": normalized_key},
        ExpiresIn=24 * 60 * 60,
    )
    response = HttpResponseRedirect(signed_url)
    response["Cache-Control"] = "public, max-age=3600"
    return response


def signup(request):
    if request.session.get("customer_id"):
        return redirect("index")
    if request.method == "GET":
        params = {"signup": "1"}
        next_url = request.GET.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            params["next"] = next_url
        return redirect(f"{reverse('index')}?{urlencode(params)}")
    form = CustomerSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        challenge = request.session.get("customer_security_challenge", {})
        supplied_answer = request.POST.get("security_answer", "").strip()
        if (
            not challenge
            or float(challenge.get("expires", 0)) < time.time()
            or not hmac.compare_digest(supplied_answer, str(challenge.get("answer", "")))
        ):
            if request.headers.get("Accept") == "application/json":
                return JsonResponse({"error": "Security check failed. Please answer the new question and try again."}, status=400)
            messages.error(request, "Security check failed. Please answer the new question and try again.")
            return redirect(f"{reverse('index')}?signup=1")
        customer = Customer(
            first_name=form.cleaned_data["first_name"].strip(),
            last_name=form.cleaned_data["last_name"].strip(),
            email=form.cleaned_data["email"],
            mobile_number=form.cleaned_data["mobile_number"],
        )
        customer.set_password(form.cleaned_data["password"])
        customer.save()
        request.session["customer_id"] = customer.pk
        request.session["customer_name"] = customer.first_name
        request.session["customer_last_activity"] = time.time()
        merge_session_cart_into_customer(request, customer)
        messages.success(request, "Your account has been created.")
        if request.headers.get("Accept") == "application/json":
            next_url = request.POST.get("next", "")
            redirect_url = next_url if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}) else "/"
            return JsonResponse({"success": True, "redirect": redirect_url})
        return redirect(request.POST.get("next") if request.POST.get("next", "").startswith("/") else "index")
    if request.method == "POST" and request.headers.get("Accept") == "application/json":
        errors = {
            field: [error["message"] for error in field_errors]
            for field, field_errors in form.errors.get_json_data().items()
        }
        return JsonResponse(
            {
                "error": "Please correct the highlighted account details.",
                "errors": errors,
            },
            status=400,
        )
    return render(request, "customer_signup.html", {"form": form})


def customer_security_question(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    left = random.randint(1, 12)
    right = random.randint(1, 12)
    request.session["customer_security_challenge"] = {
        "answer": str(left + right),
        "question": f"{left} + {right}",
        "expires": time.time() + 600,
    }
    return JsonResponse({"question": f"{left} + {right}"})


def customer_login(request):
    if request.session.get("customer_id"):
        return redirect("index")
    if request.method == "GET":
        params = {"login": "1"}
        next_url = request.GET.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            params["next"] = next_url
        return redirect(f"{reverse('index')}?{urlencode(params)}")
    form = CustomerLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        challenge = request.session.get("customer_security_challenge", {})
        supplied_answer = form.cleaned_data["security_answer"].strip()
        if (
            not challenge
            or float(challenge.get("expires", 0)) < time.time()
            or not hmac.compare_digest(supplied_answer, str(challenge.get("answer", "")))
        ):
            left = int(time.time_ns() % 12) + 1
            right = int((time.time_ns() // 1000) % 12) + 1
            request.session["customer_security_challenge"] = {
                "answer": str(left + right),
                "question": f"{left} + {right}",
                "expires": time.time() + 600,
            }
            if request.headers.get("Accept") == "application/json":
                return JsonResponse(
                    {"error": "Security check failed. Please answer the new question and try again."},
                    status=400,
                )
            messages.error(request, "Security check failed. Please answer the new question and try again.")
            return redirect(f"{reverse('index')}?login=1")

        attempts = request.session.get("customer_login_attempts", [])
        now = time.time()
        attempts = [attempted_at for attempted_at in attempts if now - attempted_at < 300]
        if len(attempts) >= 5:
            if request.headers.get("Accept") == "application/json":
                return JsonResponse({"error": "Too many login attempts. Please wait 5 minutes."}, status=429)
            messages.error(request, "Too many login attempts. Please wait 5 minutes.")
            return redirect(f"{reverse('index')}?login=1")

        login_value = form.cleaned_data["login"].strip().lower()
        customer = (
            Customer.objects.filter(mobile_number=login_value).first()
            if login_value.isdigit()
            else Customer.objects.filter(email__iexact=login_value).first()
        )
        if customer is None or not customer.check_password(form.cleaned_data["password"]):
            attempts.append(now)
            request.session["customer_login_attempts"] = attempts
            left = random.randint(1, 12)
            right = random.randint(1, 12)
            request.session["customer_security_challenge"] = {
                "answer": str(left + right),
                "question": f"{left} + {right}",
                "expires": time.time() + 600,
            }
            if request.headers.get("Accept") == "application/json":
                return JsonResponse({"error": "Invalid login details or password."}, status=401)
            messages.error(request, "Invalid login details or password.")
            return redirect(f"{reverse('index')}?login=1")
        else:
            request.session["customer_id"] = customer.pk
            request.session["customer_name"] = customer.first_name
            request.session["customer_last_activity"] = time.time()
            request.session["customer_login_attempts"] = []
            request.session.pop("customer_security_challenge", None)
            merge_session_cart_into_customer(request, customer)
            next_url = request.POST.get("next", "")
            if request.headers.get("Accept") == "application/json":
                return JsonResponse({"success": True, "redirect": next_url if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}) else "/"})
            return redirect(next_url if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}) else "index")
    if request.method == "POST":
        return redirect(f"{reverse('index')}?login=1")
    return redirect("index")


def customer_logout(request):
    if request.method in ("GET", "POST"):
        request.session.pop("customer_id", None)
        request.session.pop("customer_name", None)
        request.session.pop("customer_last_activity", None)
        if request.GET.get("timeout") == "1":
            messages.info(request, "Your session expired after 30 minutes of inactivity.")
        else:
            messages.success(request, "You have been logged out.")
    return redirect("index")


def customer_required(view):
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        customer_id = request.session.get("customer_id")
        if not customer_id:
            messages.warning(request, "Please log in to view your orders.")
            return redirect(f"{reverse('customer_login')}?next={request.path}")
        return view(request, *args, **kwargs)
    return wrapped_view


@customer_required
def order_history(request):
    customer = get_object_or_404(Customer, pk=request.session["customer_id"])
    orders = ShopOrder.objects.filter(customer=customer).prefetch_related("items").order_by("-created_at", "-pk")
    return render(request, "order_history.html", {"orders": orders})


@customer_required
def order_invoice_pdf(request, order_number):
    customer = get_object_or_404(Customer, pk=request.session["customer_id"])
    order = get_object_or_404(
        ShopOrder.objects.prefetch_related("items"),
        order_number=order_number,
        customer=customer,
    )

    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice {order.order_number}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Compact",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=9.5,
        spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="InvoiceTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        alignment=0,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="InvoiceHeader",
        parent=styles["Compact"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    ))
    styles.add(ParagraphStyle(
        name="InvoiceLabel",
        parent=styles["Compact"],
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#555555"),
    ))

    logo_path = settings.BASE_DIR / "static" / "mybanno-invoice-logo.png"
    header_left = Paragraph("<b>MYBANNO</b><br/><font size='7'>Customer order invoice</font>", styles["InvoiceTitle"])
    if logo_path.exists():
        logo_image = Image(str(logo_path), width=17 * mm, height=17 * mm)
        header_left = [logo_image, Paragraph("<b>MYBANNO</b>", styles["InvoiceTitle"])]

    header = Table(
        [[header_left, Paragraph("<b>Tax Invoice</b><br/><font size='7'>Invoice No: %s</font>" % order.order_number, styles["Compact"])]],
        colWidths=[118 * mm, 56 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#222222")),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
    ]))
    elements = [header, Spacer(1, 3 * mm)]

    details = Table([
        [Paragraph("<b>Order ID:</b> %s" % order.order_number, styles["Compact"]),
         Paragraph("<b>Order Date:</b> %s" % order.created_at.strftime("%d-%m-%Y"), styles["Compact"])],
        [Paragraph("<b>Invoice No:</b> %s" % order.order_number, styles["Compact"]),
         Paragraph("<b>Invoice Date:</b> %s" % order.created_at.strftime("%d-%m-%Y"), styles["Compact"])],
    ], colWidths=[87 * mm, 87 * mm])
    details.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.extend([details, Spacer(1, 2 * mm)])

    address = f"{customer.first_name} {customer.last_name}".strip()
    customer_blocks = Table([
        [Paragraph("<b>Billing Address</b>", styles["InvoiceHeader"]),
         Paragraph("<b>Shipping Address</b>", styles["InvoiceHeader"])],
        [Paragraph("%s<br/>%s<br/>Mobile: %s" % (
            address, order.delivery_address.replace("\n", "<br/>"), order.mobile_number), styles["Compact"]),
         Paragraph("%s<br/>%s<br/>Mobile: %s" % (
            address, order.delivery_address.replace("\n", "<br/>"), order.mobile_number), styles["Compact"])],
    ], colWidths=[87 * mm, 87 * mm])
    customer_blocks.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#777777")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dddddd")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.extend([customer_blocks, Spacer(1, 4 * mm)])

    data = [[
        Paragraph("Product", styles["InvoiceHeader"]),
        Paragraph("Qty", styles["InvoiceHeader"]),
        Paragraph("Price (Rs.)", styles["InvoiceHeader"]),
        Paragraph("Amount (Rs.)", styles["InvoiceHeader"]),
    ]]
    for item in order.items.all():
        variant = " / ".join(value for value in (item.color, item.size) if value)
        amount = item.unit_price * item.quantity
        data.append([
            Paragraph("<b>%s</b><br/><font size='7'>%s</font>" % (
                item.product_name, variant or "-"), styles["Compact"]),
            str(item.quantity),
            f"Rs. {item.unit_price:.2f}",
            f"Rs. {amount:.2f}",
        ])
    table = Table(data, colWidths=[106 * mm, 12 * mm, 29 * mm, 27 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f0ea")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111111")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d4cb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("LEADING", (0, 1), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (3, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    totals = Table([
        ["", Paragraph("<b>Grand Total</b>", styles["InvoiceHeader"]),
         Paragraph("<b>Rs. %s</b>" % f"{order.subtotal:.2f}", styles["InvoiceTitle"])],
    ], colWidths=[96 * mm, 43 * mm, 35 * mm])
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("LINEABOVE", (1, 0), (-1, 0), 0.8, colors.HexColor("#222222")),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ]))
    elements.extend([
        table,
        Spacer(1, 4 * mm),
        totals,
        Spacer(1, 8 * mm),
        Paragraph("<i>This is a computer-generated invoice.</i>", styles["InvoiceLabel"]),
    ])

    logo_path = settings.BASE_DIR / "static" / "mybanno-invoice-logo.png"

    def draw_logo_watermark(canvas, _document):
        if not logo_path.exists():
            return
        logo = ImageReader(str(logo_path))
        logo_width, logo_height = logo.getSize()
        watermark_width = 95 * mm
        watermark_height = watermark_width * logo_height / logo_width
        canvas.saveState()
        if hasattr(canvas, "setFillAlpha"):
            canvas.setFillAlpha(0.08)
        canvas.drawImage(
            logo,
            (A4[0] - watermark_width) / 2,
            (A4[1] - watermark_height) / 2,
            width=watermark_width,
            height=watermark_height,
            preserveAspectRatio=True,
            mask="auto",
        )
        canvas.restoreState()

    document.build(
        elements,
        onFirstPage=draw_logo_watermark,
        onLaterPages=draw_logo_watermark,
    )

    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Mybanno-{order.order_number}.pdf"'
    return response


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
                    "thumbnail": media["thumbnail_url"],
                    "color": media["color"],
                }
                for media in product.gallery_items
            ],
        }
    )


def get_customer_from_session(request):
    customer_id = request.session.get("customer_id")
    return Customer.objects.filter(pk=customer_id).first() if customer_id else None


def merge_session_cart_into_customer(request, customer):
    session_cart = request.session.get("shop_cart", {})
    if not isinstance(session_cart, dict):
        session_cart = {}

    for item in customer.cart_items.select_related("product").all():
        key = (
            f"{item.product_id}|{item.color}|{item.size}"
            if item.product.colors
            else f"{item.product_id}|{item.size}"
        )
        if key not in session_cart:
            session_cart[key] = {
                "product_id": item.product_id,
                "color": item.color,
                "color_code": item.color_code or item.product.color_value_for(item.color),
                "size": item.size,
                "quantity": item.quantity,
            }

    for key, item in session_cart.items():
        if not isinstance(item, dict):
            continue
        product = Product.objects.filter(pk=item.get("product_id")).first()
        if product is None:
            continue
        CustomerCartItem.objects.update_or_create(
            customer=customer,
            product=product,
            color=str(item.get("color", "")).strip(),
            size=str(item.get("size", "")).strip(),
            defaults={
                "color_code": str(item.get("color_code", "")).strip() or product.color_value_for(str(item.get("color", ""))),
                "quantity": max(1, int(item.get("quantity", 1))),
            },
        )

    request.session["shop_cart"] = session_cart
    return session_cart


def save_customer_cart(request, customer=None):
    customer = customer or get_customer_from_session(request)
    if customer is None:
        return
    cart = request.session.get("shop_cart", {})
    cart = cart if isinstance(cart, dict) else {}
    customer.cart_items.all().delete()
    for item in cart.values():
        if not isinstance(item, dict):
            continue
        product = Product.objects.filter(pk=item.get("product_id")).first()
        if product is None:
            continue
        color = str(item.get("color", "")).strip()
        size = str(item.get("size", "")).strip()
        quantity = max(1, int(item.get("quantity", 1)))
        CustomerCartItem.objects.update_or_create(
            customer=customer,
            product=product,
            color=color,
            size=size,
            defaults={
                "color_code": str(item.get("color_code", "")).strip() or product.color_value_for(color),
                "quantity": quantity,
            },
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
    customer = get_customer_from_session(request)
    if customer is not None:
        save_customer_cart(request, customer)
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
    customer = get_customer_from_session(request)
    if customer is not None:
        cart_data = merge_session_cart_into_customer(request, customer)
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
        if customer is not None:
            save_customer_cart(request, customer)
        return redirect("cart")

    return render(request, "cart.html", {"items": items, "subtotal": subtotal})


def checkout(request):
    customer = get_customer_from_session(request)
    if customer is None:
        messages.warning(request, "Please log in before placing an order.")
        params = {"login": "1", "next": reverse("checkout")}
        return redirect(f"{reverse('index')}?{urlencode(params)}")

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

    customer = Customer.objects.filter(pk=request.session.get("customer_id")).first() if request.session.get("customer_id") else None
    form = CheckoutForm(
        request.POST or None,
        initial={
            "recipient_name": f"{customer.first_name} {customer.last_name}".strip() if customer else "",
            "mobile_number": customer.mobile_number if customer else "",
        },
    )
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
                    customer=customer,
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
            customer = get_customer_from_session(request)
            if customer is not None:
                customer.cart_items.all().delete()
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
    if order.customer_id and order.customer_id != request.session.get("customer_id"):
        return redirect("index")
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
    product = get_object_or_404(
        Product.objects.prefetch_related("media_items"),
        pk=product_id,
    )
    delete_media_url(product.image_data)
    for media in product.media_items.all():
        delete_media_url(media.data_url)
    product.delete()
    messages.success(request, "Product deleted.")
    return redirect("admin_dashboard")
