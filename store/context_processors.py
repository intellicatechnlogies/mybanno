import math
import random
import time

from django.db.models import DecimalField, Max
from django.db.models.functions import Coalesce, Lower

from .forms import DEFAULT_CATEGORIES, DEFAULT_CLOTH_TYPES, DEFAULT_OCCASIONS, DEFAULT_SIZES
from .models import Product


def issue_customer_security_challenge(request):
    left = random.randint(1, 12)
    right = random.randint(1, 12)
    request.session["customer_security_challenge"] = {
        "answer": str(left + right),
        "question": f"{left} + {right}",
        "expires": time.time() + 600,
    }
    return {
        "question": f"{left} + {right}",
        "answer": str(left + right),
    }


def site_options(request):
    effective_price = Coalesce(
        "offer_price",
        "actual_price",
        "price",
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    max_price = Product.objects.aggregate(max_price=Max(effective_price))["max_price"]
    cart = request.session.get("shop_cart", {})
    cart_count = sum(
        int(item.get("quantity", 0))
        for item in cart.values()
        if isinstance(item, dict) and str(item.get("quantity", "")).isdigit()
    ) if isinstance(cart, dict) else 0
    challenge = request.session.get("customer_security_challenge")
    if not challenge or float(challenge.get("expires", 0)) < time.time():
        challenge = issue_customer_security_challenge(request)
    if "question" not in challenge:
        challenge = issue_customer_security_challenge(request)
    return {
        "header_categories": sorted(
            {*DEFAULT_CATEGORIES, *Product.objects.exclude(category="").values_list("category", flat=True).distinct()},
            key=str.casefold,
        ),
        "header_cloth_types": sorted(
            {*DEFAULT_CLOTH_TYPES, *Product.objects.exclude(cloth_type="").values_list("cloth_type", flat=True).distinct()},
            key=str.casefold,
        ),
        "header_occasions": sorted(
            {*DEFAULT_OCCASIONS, *Product.objects.exclude(occasion_category="").values_list("occasion_category", flat=True).distinct()},
            key=str.casefold,
        ),
        "header_sizes": DEFAULT_SIZES,
        "header_price_max": max(100, math.ceil(max_price or 100)),
        "cart_count": cart_count,
        "security_question": challenge["question"],
    }
