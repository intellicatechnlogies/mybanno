from django.db import models
from django.utils import timezone
from decimal import Decimal
import re


class Product(models.Model):
    name = models.CharField(max_length=200)
    cloth_type = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    occasion_category = models.CharField(max_length=100, blank=True, default="")
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    actual_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offer_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    size_stock = models.JSONField(default=dict, blank=True)
    color_stock = models.JSONField(default=dict, blank=True)
    color_values = models.JSONField(default=dict, blank=True)
    sizes = models.CharField(max_length=200, blank=True, default="")
    image_data = models.TextField(blank=True, null=True)
    image_color = models.CharField(max_length=100, blank=True, default="")
    on_offer = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def size_list(self):
        return [size.strip() for size in self.sizes.split(",") if size.strip()]

    @property
    def has_size_stock(self):
        return bool(self.color_stock or self.size_stock)

    @property
    def colors(self):
        return list(self.color_stock)

    @property
    def color_options(self):
        defaults = {
            "black": "#000000",
            "white": "#ffffff",
            "red": "#dc2626",
            "blue": "#2563eb",
            "green": "#16a34a",
            "yellow": "#eab308",
            "orange": "#ea580c",
            "purple": "#9333ea",
            "pink": "#ec4899",
            "brown": "#854d0e",
            "gray": "#6b7280",
            "grey": "#6b7280",
            "navy": "#1e3a8a",
            "beige": "#d6c6a5",
            "cream": "#f5f0dc",
            "magenta": "#d946ef",
        }
        options = []
        for color in self.colors:
            value = self.color_values.get(color, "")
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                value = defaults.get(color.casefold(), "#b8b8b8")
            options.append({"name": color, "value": value.lower()})
        return options

    def color_value_for(self, color):
        return next(
            (
                option["value"]
                for option in self.color_options
                if option["name"] == color
            ),
            "",
        )

    def stock_for_size(self, size, color=None):
        if self.color_stock:
            if color is not None:
                return int(self.color_stock.get(color, {}).get(size, 0))
            return sum(int(inventory.get(size, 0)) for inventory in self.color_stock.values())
        if not self.has_size_stock:
            return self.stock
        return int(self.size_stock.get(size, 0))

    @property
    def total_stock(self):
        if self.color_stock:
            return sum(
                int(quantity)
                for inventory in self.color_stock.values()
                for quantity in inventory.values()
            )
        if not self.has_size_stock:
            return self.stock
        return sum(int(quantity) for quantity in self.size_stock.values())

    @property
    def size_inventory(self):
        return [
            {"size": size, "stock": self.stock_for_size(size)}
            for size in self.size_list
        ]

    @property
    def color_inventory(self):
        return [
            {
                "color": color,
                "value": self.color_value_for(color),
                "sizes": [
                    {"size": size, "stock": self.stock_for_size(size, color)}
                    for size in self.size_list
                ],
            }
            for color in self.colors
        ]

    @property
    def discount_percentage(self):
        actual_price = self.actual_price if self.actual_price is not None else self.price
        if self.offer_price is None or actual_price <= 0:
            return 0
        from decimal import ROUND_HALF_UP

        percentage = (actual_price - self.offer_price) * 100 / actual_price
        return int(percentage.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def gallery_items(self):
        items = []
        if self.image_data:
            items.append({
                "id": None,
                "media_type": "image",
                "data_url": self.image_data,
                "filename": "Product photo",
                "color": self.image_color,
                "is_legacy": True,
            })
        items.extend(
            {
                "id": media.pk,
                "media_type": media.media_type,
                "data_url": media.data_url,
                "filename": media.filename,
                "color": media.color,
                "is_legacy": False,
            }
            for media in self.media_items.all()
        )
        return items

    def media_for_color(self, color=""):
        items = self.gallery_items
        if color:
            matching = next(
                (
                    item
                    for item in items
                    if item["media_type"] == ProductMedia.IMAGE
                    and item["color"] == color
                ),
                None,
            )
            if matching:
                return matching
            generic = next(
                (
                    item
                    for item in items
                    if item["media_type"] == ProductMedia.IMAGE
                    and not item["color"]
                ),
                None,
            )
            if generic:
                return generic
        return items[0] if items else None


class ProductMedia(models.Model):
    IMAGE = "image"
    VIDEO = "video"
    MEDIA_TYPES = [
        (IMAGE, "Image"),
        (VIDEO, "Video"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="media_items")
    media_type = models.CharField(max_length=5, choices=MEDIA_TYPES)
    data_url = models.TextField()
    filename = models.CharField(max_length=255)
    color = models.CharField(max_length=100, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.product.name}: {self.filename}"


class ShopOrder(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    mobile_number = models.CharField(max_length=24)
    delivery_address = models.TextField(max_length=1000)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    remarks = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Order #{self.pk}"


class ShopOrderItem(models.Model):
    order = models.ForeignKey(ShopOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    color = models.CharField(max_length=100, blank=True)
    color_code = models.CharField(max_length=7, blank=True, default="")
    size = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"


class AdminAccount(models.Model):
    username = models.CharField(max_length=150, unique=True)
    password_hash = models.CharField(max_length=512)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.username
