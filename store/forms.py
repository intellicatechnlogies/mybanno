import base64
import re

from django import forms
from django.db import transaction
from django.utils import timezone

from .models import Product, ProductMedia, ShopOrder

DEFAULT_PRODUCT_NAMES = ["Linen Day Shirt", "Relaxed Cotton Tee", "Everyday Kurta", "Classic Overshirt"]
DEFAULT_CLOTH_TYPES = ["Linen", "Cotton", "Silk", "Denim", "Khadi", "Wool", "Rayon"]
DEFAULT_CATEGORIES = ["Shirts", "Tops", "Dresses", "Bottoms", "Kurtas", "Outerwear", "Accessories"]
DEFAULT_OCCASIONS = ["Casual", "Everyday", "Office", "Party", "Wedding", "Festive", "Vacation", "Ceremony"]
DEFAULT_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "Free Size"]
MAX_COLORS = 20
DEFAULT_COLOR_VALUES = {
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
DEFAULT_COLOR_NAMES = [color.title() for color in DEFAULT_COLOR_VALUES]
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_VIDEO_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(file, initial) for file in files]


class CheckoutForm(forms.Form):
    recipient_name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    mobile_number = forms.CharField(
        strip=False,
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "inputmode": "numeric",
                "pattern": "[0-9]{10}",
                "minlength": "10",
                "maxlength": "10",
                "autocomplete": "tel",
            }
        ),
    )
    address_line = forms.CharField(
        max_length=300,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "address-line1",
                "placeholder": "House / flat number, building, street",
            }
        ),
    )
    locality = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "address-level3",
                "placeholder": "Area, colony, or locality",
            }
        ),
    )
    landmark = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(
            attrs={"placeholder": "Nearby landmark (optional)"},
        ),
    )
    postal_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "autocomplete": "postal-code",
                "placeholder": "6-digit PIN code",
            }
        ),
    )

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data["mobile_number"]
        if len(mobile_number) != 10 or not mobile_number.isascii() or not mobile_number.isdigit():
            raise forms.ValidationError("Enter a mobile number containing exactly 10 digits.")
        return mobile_number

    def clean_postal_code(self):
        postal_code = self.cleaned_data["postal_code"]
        if not postal_code.isascii() or not postal_code.isdigit() or postal_code[0] == "0":
            raise forms.ValidationError("Enter a valid 6-digit PIN code.")
        return postal_code

    def formatted_delivery_address(self):
        address_lines = [
            self.cleaned_data["recipient_name"],
            self.cleaned_data["address_line"],
            self.cleaned_data["locality"],
        ]
        if self.cleaned_data["landmark"]:
            address_lines.append(f"Landmark: {self.cleaned_data['landmark']}")
        address_lines.append(
            f"Bhopal, Madhya Pradesh - {self.cleaned_data['postal_code']}"
        )
        return "\n".join(address_lines)


class OrderUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=ShopOrder.Status.choices)
    remarks = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


def catalog_options(field, defaults):
    existing = Product.objects.exclude(**{field: ""}).values_list(field, flat=True).distinct()
    return sorted({*defaults, *existing}, key=str.casefold)


class ProductForm(forms.Form):
    name = forms.ChoiceField(choices=[("", "Choose a product name"), ("__other__", "Other")])
    name_other = forms.CharField(required=False, max_length=200)
    cloth_type = forms.ChoiceField(choices=[("", "Choose a cloth type")])
    cloth_type_other = forms.CharField(required=False, max_length=100)
    category = forms.ChoiceField(choices=[("", "Choose a category")])
    category_other = forms.CharField(required=False, max_length=100)
    occasion_category = forms.ChoiceField(
        choices=[("", "Choose an occasion")],
        required=False,
    )
    occasion_category_other = forms.CharField(required=False, max_length=100)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    actual_price = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2)
    offer_price = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2)
    stock = forms.IntegerField(required=False, min_value=0)
    image_color = forms.CharField(required=False, max_length=100)
    sizes = forms.MultipleChoiceField(choices=[(size, size) for size in DEFAULT_SIZES])
    on_offer = forms.BooleanField(required=False)
    images = MultipleFileField(required=False, widget=MultipleFileInput(attrs={
        "accept": "image/png,image/jpeg,image/webp",
    }))
    videos = MultipleFileField(required=False, widget=MultipleFileInput(attrs={
        "accept": "video/mp4,video/webm,video/quicktime",
    }))
    remove_media = forms.MultipleChoiceField(required=False, choices=[])
    remove_legacy_image = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        names = catalog_options("name", DEFAULT_PRODUCT_NAMES)
        self.fields["name"].choices = [
            ("", "Choose a product name"),
            *((name, name) for name in names),
            ("__other__", "Other"),
        ]
        self.fields["cloth_type"].choices = [
            ("", "Choose a cloth type"),
            *((value, value) for value in catalog_options("cloth_type", DEFAULT_CLOTH_TYPES)),
            ("__other__", "Other"),
        ]
        self.fields["category"].choices = [
            ("", "Choose a category"),
            *((value, value) for value in catalog_options("category", DEFAULT_CATEGORIES)),
            ("__other__", "Other"),
        ]
        self.fields["occasion_category"].choices = [
            ("", "Choose an occasion"),
            *((value, value) for value in catalog_options("occasion_category", DEFAULT_OCCASIONS)),
            ("__other__", "Other"),
        ]
        cloth_types = [value for value, _ in self.fields["cloth_type"].choices[1:-1]]
        categories = [value for value, _ in self.fields["category"].choices[1:-1]]
        occasions = [value for value, _ in self.fields["occasion_category"].choices[1:-1]]
        existing_media = list(instance.media_items.all()) if instance else []
        existing_colors = instance.colors if instance else []
        existing_color_keys = {color.casefold() for color in existing_colors}
        self.color_names = list(dict.fromkeys(
            [
                *existing_colors,
                *(color for color in DEFAULT_COLOR_NAMES if color.casefold() not in existing_color_keys),
            ]
        ))[:MAX_COLORS]
        self.fields["remove_media"].choices = [(str(media.pk), media.filename) for media in existing_media]
        self.fields["images"].required = not bool(
            instance and (instance.image_data or any(media.media_type == ProductMedia.IMAGE for media in existing_media))
        )
        for color_index, color in enumerate(self.color_names):
            color_inventory = instance.color_stock.get(color, {}) if instance else {}
            for size_index, size in enumerate(DEFAULT_SIZES):
                self.fields[f"size_color_{size_index}_{color_index}"] = forms.BooleanField(
                    required=False,
                    initial=size in color_inventory,
                )
                self.fields[f"color_stock_{size_index}_{color_index}"] = forms.IntegerField(
                    required=False,
                    min_value=0,
                    initial=color_inventory.get(size, 0),
                )
        if instance and not kwargs.get("initial"):
            self.initial.update({
                "name": instance.name if instance.name in names else "__other__",
                "name_other": instance.name if instance.name not in names else "",
                "cloth_type": instance.cloth_type if instance.cloth_type in cloth_types else "__other__",
                "cloth_type_other": instance.cloth_type if instance.cloth_type not in cloth_types else "",
                "category": instance.category if instance.category in categories else "__other__",
                "category_other": instance.category if instance.category not in categories else "",
                "occasion_category": (
                    instance.occasion_category
                    if instance.occasion_category in occasions
                    else "__other__" if instance.occasion_category else ""
                ),
                "occasion_category_other": (
                    instance.occasion_category
                    if instance.occasion_category and instance.occasion_category not in occasions
                    else ""
                ),
                "description": instance.description,
                "actual_price": instance.actual_price if instance.actual_price is not None else instance.price,
                "offer_price": instance.offer_price,
                "stock": instance.stock,
                "image_color": instance.image_color,
                "sizes": [size.strip() for size in instance.sizes.split(",") if size.strip()],
                "on_offer": instance.on_offer,
            })

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        if name == "__other__":
            name = cleaned_data.get("name_other", "").strip()
            if not name:
                self.add_error("name_other", "Enter a product name.")
        cleaned_data["name"] = name
        for field_name, other_field_name, label in (
            ("cloth_type", "cloth_type_other", "cloth type"),
            ("category", "category_other", "category"),
            ("occasion_category", "occasion_category_other", "occasion"),
        ):
            if cleaned_data.get(field_name) == "__other__":
                value = cleaned_data.get(other_field_name, "").strip()
                if not value:
                    self.add_error(other_field_name, f"Enter a {label}.")
                cleaned_data[field_name] = value

        actual_price = cleaned_data.get("actual_price")
        offer_price = cleaned_data.get("offer_price")
        if offer_price is not None and actual_price is not None and offer_price >= actual_price:
            self.add_error("offer_price", "Offer price must be less than the actual price.")
        if cleaned_data.get("on_offer") and offer_price is None:
            self.add_error("offer_price", "Offer price is required when Sale is selected.")

        selected_sizes = cleaned_data.get("sizes", [])
        colors = [
            color
            for color_index, color in enumerate(self.color_names)
            if any(
                size in selected_sizes
                and cleaned_data.get(f"size_color_{size_index}_{color_index}")
                for size_index, size in enumerate(DEFAULT_SIZES)
            )
        ]

        size_stock = {}
        color_stock = {}
        cleaned_color_values = {}
        for color_index, color in enumerate(self.color_names):
            if color not in colors:
                continue
            code = self.instance.color_values.get(color, "") if self.instance else ""
            if not code:
                code = DEFAULT_COLOR_VALUES.get(color.casefold(), "#b8b8b8")
            if code and not re.fullmatch(r"#[0-9a-fA-F]{6}", code):
                self.add_error(None, f"Invalid swatch value for {color}.")
                code = ""
            if code:
                cleaned_color_values[color] = code.lower()
            color_stock[color] = {}
            for size_index, size in enumerate(DEFAULT_SIZES):
                if size not in selected_sizes:
                    continue
                if cleaned_data.get(f"size_color_{size_index}_{color_index}"):
                    color_stock[color][size] = (
                        cleaned_data.get(f"color_stock_{size_index}_{color_index}") or 0
                    )
        if len(cleaned_color_values) != len(colors):
            self.add_error("colors", "Choose a color swatch for every color option.")
        size_stock = {
            size: sum(inventory.get(size, 0) for inventory in color_stock.values())
            for size in selected_sizes
        }
        for size in selected_sizes:
            if not any(size in inventory for inventory in color_stock.values()):
                self.add_error(None, f"Choose at least one color and quantity for size {size}.")
        if selected_sizes and sum(size_stock.values()) < 1:
            self.add_error("stock", "Total stock across colors and sizes must be at least 1.")
        cleaned_data["stock"] = sum(size_stock.values())
        cleaned_data["colors"] = colors
        cleaned_data["color_values"] = cleaned_color_values
        cleaned_data["size_stock"] = size_stock
        cleaned_data["color_stock"] = color_stock
        image_colors = self.data.getlist("image_colors") if self.is_bound else []
        if len(image_colors) != len(cleaned_data.get("images", [])):
            image_colors = [""] * len(cleaned_data.get("images", []))
        for image_color in image_colors:
            if image_color and image_color not in colors:
                self.add_error("images", "Choose a color that is listed for this product.")
        cleaned_data["image_colors"] = image_colors
        if cleaned_data.get("image_color") not in colors:
            cleaned_data["image_color"] = ""

        image_files = cleaned_data.get("images", [])
        video_files = cleaned_data.get("videos", [])
        for uploaded_image in image_files:
            if uploaded_image.size > MAX_IMAGE_SIZE:
                self.add_error("images", "Each product photo must be no larger than 5 MB.")
            if uploaded_image.content_type not in ALLOWED_IMAGE_TYPES:
                self.add_error("images", "Product photos must be JPEG, PNG, or WebP files.")
        for uploaded_video in video_files:
            if uploaded_video.size > MAX_VIDEO_SIZE:
                self.add_error("videos", "Each product video must be no larger than 5 MB.")
            if uploaded_video.content_type not in ALLOWED_VIDEO_TYPES:
                self.add_error("videos", "Product videos must be MP4, WebM, or MOV files.")
        product_has_image = bool(
            self.instance
            and (
                (self.instance.image_data and not cleaned_data.get("remove_legacy_image"))
                or any(
                    media.media_type == ProductMedia.IMAGE
                    and str(media.pk) not in cleaned_data.get("remove_media", [])
                    for media in self.instance.media_items.all()
                )
            )
        )
        if not image_files and not product_has_image:
            self.add_error("images", "At least one product photo is required.")
        return cleaned_data

    @transaction.atomic
    def save(self):
        product = self.instance or Product()
        data = self.cleaned_data
        product.name = data["name"]
        product.cloth_type = data["cloth_type"]
        product.category = data["category"]
        product.occasion_category = data["occasion_category"]
        product.description = data["description"]
        product.price = data["actual_price"]
        product.actual_price = data["actual_price"]
        product.offer_price = data["offer_price"]
        product.size_stock = data["size_stock"]
        product.color_stock = data["color_stock"]
        product.color_values = data["color_values"]
        product.stock = sum(data["size_stock"].values())
        product.sizes = ", ".join(data["sizes"])
        product.image_color = data["image_color"]
        product.on_offer = data["on_offer"]
        product.updated_at = timezone.now()
        product.save()
        sort_order = product.media_items.count()
        existing_media = list(product.media_items.all())
        for media in existing_media:
            media_color = self.data.get(f"media_color_{media.pk}", "")
            media.color = media_color if media_color in data["colors"] else ""
            media.save(update_fields=["color"])
        for uploaded_file, image_color in zip(data["images"], data["image_colors"]):
            data_url = (
                f"data:{uploaded_file.content_type};"
                f"base64,{base64.b64encode(uploaded_file.read()).decode('ascii')}"
            )
            ProductMedia.objects.create(
                product=product,
                media_type=ProductMedia.IMAGE,
                data_url=data_url,
                filename=uploaded_file.name,
                color=image_color,
                sort_order=sort_order,
            )
            sort_order += 1
        for uploaded_file in data["videos"]:
            data_url = (
                f"data:{uploaded_file.content_type};"
                f"base64,{base64.b64encode(uploaded_file.read()).decode('ascii')}"
            )
            ProductMedia.objects.create(
                product=product,
                media_type=ProductMedia.VIDEO,
                data_url=data_url,
                filename=uploaded_file.name,
                sort_order=sort_order,
            )
            sort_order += 1
        remove_ids = data["remove_media"]
        if remove_ids:
            product.media_items.filter(pk__in=remove_ids).delete()
        if data["remove_legacy_image"]:
            product.image_data = None
            product.save(update_fields=["image_data"])
        return product
