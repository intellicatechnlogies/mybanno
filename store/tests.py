import time
import base64
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AdminAccount, Product, ProductMedia, ShopOrder, ShopOrderItem


class StorefrontTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_HOST"] = "localhost"
        self.first_product = Product.objects.create(
            name="Linen Shirt",
            cloth_type="Linen",
            category="Shirts",
            price="80.00",
            actual_price="80.00",
            offer_price="60.00",
            stock=4,
            sizes="S, M",
            on_offer=False,
        )
        Product.objects.create(
            name="Cotton Dress",
            cloth_type="Cotton",
            category="Dresses",
            price="100.00",
            actual_price="100.00",
            stock=0,
            sizes="Free Size",
        )

    def checkout_details(self, **overrides):
        details = {
            "recipient_name": "Asha Sharma",
            "mobile_number": "9876543210",
            "address_line": "12 Example Road",
            "locality": "Arera Colony",
            "landmark": "Near City Park",
            "postal_code": "462016",
        }
        details.update(overrides)
        return details

    def test_size_inventory_and_discount_are_displayed(self):
        self.first_product.size_stock = {"S": 2, "M": 1}
        self.first_product.stock = 3
        self.first_product.save(update_fields=["size_stock", "stock"])

        response = self.client.get(reverse("index"), {"q": "Linen"})
        self.assertContains(response, "Wear your day.")
        self.assertContains(response, "Your way.")
        self.assertContains(response, 'class="hero-cta"')
        self.assertContains(response, 'class="hero-background-image"', count=2)
        self.assertContains(response, 'class="mobile-category-nav"')
        self.assertContains(response, 'href="/static/mobile.css?v=1"')
        self.assertNotContains(response, 'class="hero-showcase"')
        self.assertContains(response, "25% OFF")
        self.assertContains(response, "S · 2")
        self.assertContains(response, "M · 1")

        detail_response = self.client.get(
            reverse("product_detail", args=[self.first_product.pk])
        )
        self.assertContains(detail_response, "S · 2 in stock")
        self.assertContains(detail_response, "M · 1 in stock")

        modal_response = self.client.get(
            reverse("product_modal_data", args=[self.first_product.pk])
        )
        self.assertEqual(modal_response.json()["discount_percentage"], 25)
        self.assertEqual(modal_response.json()["size_stock"], {"S": 2, "M": 1})

    def test_size_inventory_limits_cart_and_decrements_selected_sizes(self):
        self.first_product.size_stock = {"S": 1, "M": 2}
        self.first_product.stock = 3
        self.first_product.save(update_fields=["size_stock", "stock"])
        add_url = reverse("cart_add")
        response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "size": "M", "quantity": "2"},
        )
        self.assertEqual(response.status_code, 200)
        overstock_response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "size": "M", "quantity": "1"},
        )
        self.assertEqual(overstock_response.status_code, 400)
        self.assertEqual(
            self.client.post(
                add_url,
                {"product_id": self.first_product.pk, "size": "S", "quantity": "1"},
            ).status_code,
            200,
        )

        response = self.client.post(
            reverse("checkout"),
            self.checkout_details(),
        )
        self.assertRedirects(response, reverse("checkout_complete"))
        self.first_product.refresh_from_db()
        self.assertEqual(self.first_product.size_stock, {"S": 0, "M": 0})
        self.assertEqual(self.first_product.stock, 0)

    def test_homepage_and_modal_show_stock_remaining_after_cart_reservation(self):
        self.first_product.size_stock = {"S": 2, "M": 1}
        self.first_product.stock = 3
        self.first_product.save(update_fields=["size_stock", "stock"])
        self.assertEqual(
            self.client.post(
                reverse("cart_add"),
                {"product_id": self.first_product.pk, "size": "M", "quantity": "1"},
            ).status_code,
            200,
        )

        homepage = self.client.get(reverse("index"), {"q": "Linen"})
        self.assertContains(homepage, "2 in stock")
        self.assertContains(homepage, "S · 2")
        self.assertContains(homepage, "M · 0")

        modal = self.client.get(
            reverse("product_modal_data", args=[self.first_product.pk])
        ).json()
        self.assertEqual(modal["stock"], 2)
        self.assertEqual(modal["size_stock"], {"S": 2, "M": 0})

    def test_color_and_size_inventory_are_selected_reserved_and_decremented_independently(self):
        self.first_product.color_stock = {
            "Black": {"S": 1, "M": 2},
            "Blue": {"S": 3, "M": 0},
        }
        self.first_product.size_stock = {"S": 4, "M": 2}
        self.first_product.stock = 6
        self.first_product.save(update_fields=["color_stock", "size_stock", "stock"])

        modal = self.client.get(reverse("product_modal_data", args=[self.first_product.pk])).json()
        self.assertEqual(
            [color["name"] for color in modal["colors"]],
            ["Black", "Blue"],
        )
        self.assertEqual(modal["color_stock"]["Black"]["S"], 1)
        self.assertEqual(modal["size_stock"], {"S": 4, "M": 2})
        self.assertContains(self.client.get(reverse("index")), "Available colors")
        self.assertContains(
            self.client.get(reverse("product_detail", args=[self.first_product.pk])),
            "S · 1 in stock",
        )

        add_url = reverse("cart_add")
        add_response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "color": "Blue", "size": "S", "quantity": "2"},
        )
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.json()["color_code"], "#2563eb")
        self.assertEqual(
            self.client.post(
                add_url,
                {"product_id": self.first_product.pk, "color": "Black", "size": "S", "quantity": "1"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                add_url,
                {"product_id": self.first_product.pk, "color": "Black", "size": "S", "quantity": "1"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                add_url,
                {"product_id": self.first_product.pk, "color": "Green", "size": "S", "quantity": "1"},
            ).status_code,
            400,
        )
        self.assertContains(self.client.get(reverse("cart")), "Color: Blue")
        self.assertContains(self.client.get(reverse("cart")), "--swatch:#2563eb")

        response = self.client.post(
            reverse("checkout"),
            self.checkout_details(),
        )
        self.assertRedirects(response, reverse("checkout_complete"))
        self.assertContains(self.client.get(reverse("checkout_complete")), "Blue")
        self.assertContains(self.client.get(reverse("checkout_complete")), "S × 2")
        ordered_items = {
            (item.color, item.size): item.quantity
            for item in ShopOrderItem.objects.all()
        }
        self.assertEqual(ordered_items, {("Blue", "S"): 2, ("Black", "S"): 1})
        self.assertEqual(
            ShopOrderItem.objects.get(color="Blue", size="S").color_code,
            "#2563eb",
        )
        self.first_product.refresh_from_db()
        self.assertEqual(self.first_product.color_stock["Black"]["S"], 0)
        self.assertEqual(self.first_product.color_stock["Blue"]["S"], 1)
        self.assertEqual(self.first_product.stock, 3)

    def test_modal_hides_colors_with_no_remaining_stock_for_current_cart(self):
        self.first_product.color_stock = {
            "Black": {"S": 1, "M": 0},
            "Blue": {"S": 2, "M": 0},
        }
        self.first_product.size_stock = {"S": 3, "M": 0}
        self.first_product.stock = 3
        self.first_product.save(update_fields=["color_stock", "size_stock", "stock"])
        self.assertEqual(
            self.client.post(
                reverse("cart_add"),
                {
                    "product_id": self.first_product.pk,
                    "color": "Blue",
                    "size": "S",
                    "quantity": "2",
                },
            ).status_code,
            200,
        )

        modal = self.client.get(
            reverse("product_modal_data", args=[self.first_product.pk])
        ).json()
        self.assertEqual([color["name"] for color in modal["colors"]], ["Black"])
        self.assertEqual(modal["color_stock"]["Blue"]["S"], 0)
        self.assertEqual(modal["size_stock"], {"S": 1, "M": 0})

    def test_search_filters_and_more_products(self):
        response = self.client.get(reverse("index"), {"q": "Linen"})
        self.assertContains(response, "Linen Shirt")
        self.assertNotContains(response, "Cotton Dress")

        response = self.client.get(reverse("index"), {"size": "Free Size"})
        self.assertContains(response, "Cotton Dress")
        self.assertNotContains(response, "Linen Shirt")

        response = self.client.get(reverse("index"), {"offer": "1"})
        self.assertContains(response, "Linen Shirt")
        self.assertNotContains(response, "Cotton Dress")

        response = self.client.get(reverse("index"), {"min_price": "70"})
        self.assertContains(response, "Cotton Dress")
        self.assertNotContains(response, "Linen Shirt")

        response = self.client.get(reverse("more_products"), {"offset": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Has-More"], "0")

    def test_occasion_is_saved_displayed_searchable_and_filterable_for_sale_and_regular_products(self):
        self.first_product.occasion_category = "Wedding"
        self.first_product.save(update_fields=["occasion_category"])
        regular_product = Product.objects.get(name="Cotton Dress")
        regular_product.occasion_category = "Wedding"
        regular_product.save(update_fields=["occasion_category"])

        response = self.client.get(reverse("index"), {"occasion": "Wedding"})
        self.assertContains(response, "Linen Shirt")
        self.assertContains(response, "Cotton Dress")
        self.assertContains(response, "Wedding")

        response = self.client.get(reverse("index"), {"q": "Wedding"})
        self.assertContains(response, "Linen Shirt")
        self.assertContains(response, "Cotton Dress")

        response = self.client.get(reverse("index"), {"offer": "1", "occasion": "Wedding"})
        self.assertContains(response, "Linen Shirt")
        self.assertNotContains(response, "Cotton Dress")

        response = self.client.get(
            reverse("product_modal_data", args=[self.first_product.pk])
        )
        self.assertEqual(response.json()["occasion_category"], "Wedding")

    def test_product_card_opens_detail_gallery(self):
        ProductMedia.objects.create(
            product=self.first_product,
            media_type=ProductMedia.IMAGE,
            data_url="data:image/png;base64,aW1hZ2U=",
            filename="front.png",
            sort_order=0,
        )
        ProductMedia.objects.create(
            product=self.first_product,
            media_type=ProductMedia.VIDEO,
            data_url="data:video/mp4;base64,dmlkZW8=",
            filename="walkthrough.mp4",
            sort_order=1,
        )

        catalog_response = self.client.get(reverse("index"))
        self.assertContains(catalog_response, 'rel="icon" type="image/png" href="/static/mibanno-logo-white.png?v=2"')
        self.assertContains(catalog_response, 'src="/static/mibanno-logo-white.png?v=2" alt="Mybanno"')
        self.assertContains(catalog_response, "Shop · Mybanno")
        self.assertContains(
            catalog_response,
            reverse("product_modal_data", args=[self.first_product.pk]),
        )
        self.assertContains(catalog_response, '<button class="product-card-link" type="button"')
        self.assertContains(catalog_response, 'class="product-card-add"')
        self.assertNotContains(catalog_response, 'class="product-card-link" href=')
        self.assertContains(catalog_response, '<dialog class="product-modal"')
        self.assertContains(
            catalog_response,
            'href="https://intellicatechnology.com/" target="_blank" rel="noopener noreferrer"',
        )

        modal_response = self.client.get(
            reverse("product_modal_data", args=[self.first_product.pk])
        )
        self.assertEqual(modal_response.status_code, 200)
        modal_product = modal_response.json()
        self.assertEqual(modal_product["name"], "Linen Shirt")
        self.assertEqual(
            [media["type"] for media in modal_product["media"]],
            ["image", "video"],
        )
        self.assertEqual(modal_product["sizes"], ["S", "M"])

        detail_response = self.client.get(reverse("product_detail", args=[self.first_product.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Linen Shirt")
        self.assertContains(detail_response, "data:image/png;base64,aW1hZ2U=")
        self.assertContains(detail_response, "data:video/mp4;base64,dmlkZW8=")
        self.assertContains(detail_response, "detail-main-video")
        self.assertContains(detail_response, 'aria-label="Previous photo or video"')
        self.assertContains(detail_response, 'aria-label="Next photo or video"')
        self.assertContains(detail_response, "1 / 2")
        self.assertNotContains(detail_response, "detail-thumbnail")
        self.assertContains(detail_response, "product-detail.js")

    def test_cart_add_update_remove_and_stock_validation(self):
        add_url = reverse("cart_add")
        response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "size": "M", "quantity": "2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart_count"], 2)
        invalid_size_response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "size": "XXL", "quantity": "1"},
        )
        self.assertEqual(invalid_size_response.status_code, 400)

        cart_url = reverse("cart")
        response = self.client.get(cart_url)
        self.assertContains(response, "Linen Shirt")
        self.assertContains(response, "120.00")

        cart_key = f"{self.first_product.pk}|M"
        response = self.client.post(
            cart_url,
            {"action": "update", "key": cart_key, "quantity": "3"},
        )
        self.assertRedirects(response, cart_url)
        self.assertEqual(self.client.session["shop_cart"][cart_key]["quantity"], 3)

        response = self.client.post(
            add_url,
            {"product_id": self.first_product.pk, "size": "M", "quantity": "2"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session["shop_cart"][cart_key]["quantity"], 3)

        response = self.client.post(
            cart_url,
            {"action": "remove", "key": cart_key},
        )
        self.assertRedirects(response, cart_url)
        self.assertEqual(self.client.session["shop_cart"], {})

    def test_checkout_saves_contact_order_items_and_decrements_stock(self):
        add_response = self.client.post(
            reverse("cart_add"),
            {"product_id": self.first_product.pk, "size": "M", "quantity": "2"},
        )
        self.assertEqual(add_response.status_code, 200)

        checkout_url = reverse("checkout")
        response = self.client.post(
            checkout_url,
            self.checkout_details(),
        )
        self.assertRedirects(response, reverse("checkout_complete"))
        order = ShopOrder.objects.get()
        item = ShopOrderItem.objects.get(order=order)
        self.assertEqual(order.mobile_number, "9876543210")
        self.assertEqual(
            order.delivery_address,
            "Asha Sharma\n12 Example Road\nArera Colony\n"
            "Landmark: Near City Park\nBhopal, Madhya Pradesh - 462016",
        )
        self.assertEqual(order.subtotal, Decimal("120.00"))
        self.assertEqual(item.product, self.first_product)
        self.assertEqual(item.product_name, "Linen Shirt")
        self.assertEqual(item.size, "M")
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal("60.00"))
        self.first_product.refresh_from_db()
        self.assertEqual(self.first_product.stock, 2)
        self.assertEqual(self.client.session["shop_cart"], {})

        response = self.client.get(reverse("checkout_complete"))
        self.assertContains(response, "Thank you for your order")
        self.assertContains(response, "Linen Shirt")

    def test_checkout_shows_bhopal_delivery_scope_and_validates_pin_code(self):
        self.client.post(
            reverse("cart_add"),
            {"product_id": self.first_product.pk, "size": "M", "quantity": "1"},
        )

        checkout_url = reverse("checkout")
        page = self.client.get(checkout_url)
        self.assertContains(page, "Bhopal city only")
        self.assertContains(page, "Full name")
        self.assertContains(page, "Area / locality")
        self.assertContains(page, "Landmark (optional)")
        self.assertContains(page, "Bhopal, Madhya Pradesh")

        response = self.client.post(
            checkout_url,
            self.checkout_details(postal_code="46201A"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid 6-digit PIN code")
        self.assertFalse(ShopOrder.objects.exists())

    def test_checkout_rejects_invalid_mobile_and_insufficient_stock(self):
        self.client.post(
            reverse("cart_add"),
            {"product_id": self.first_product.pk, "size": "M", "quantity": "2"},
        )
        for mobile_number in ("123", "12345678901", "98765 43210", "abcdefghij", "１２３４５６７８９０"):
            with self.subTest(mobile_number=mobile_number):
                response = self.client.post(
                    reverse("checkout"),
                    self.checkout_details(mobile_number=mobile_number),
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "exactly 10 digits")
        self.assertFalse(ShopOrder.objects.exists())

        self.first_product.stock = 1
        self.first_product.save(update_fields=["stock"])
        response = self.client.post(
            reverse("checkout"),
            self.checkout_details(),
        )
        self.assertRedirects(response, reverse("cart"))
        self.assertFalse(ShopOrder.objects.exists())
        self.assertEqual(self.client.session["shop_cart"][f"{self.first_product.pk}|M"]["quantity"], 2)

    def test_checkout_counts_stock_across_sizes_of_same_product(self):
        session = self.client.session
        session["shop_cart"] = {
            f"{self.first_product.pk}|S": {
                "product_id": self.first_product.pk,
                "size": "S",
                "quantity": 3,
            },
            f"{self.first_product.pk}|M": {
                "product_id": self.first_product.pk,
                "size": "M",
                "quantity": 3,
            },
        }
        session.save()

        response = self.client.post(
            reverse("checkout"),
            self.checkout_details(),
        )

        self.assertRedirects(response, reverse("cart"))
        self.assertFalse(ShopOrder.objects.exists())
        self.first_product.refresh_from_db()
        self.assertEqual(self.first_product.stock, 4)

    def test_admin_can_view_order_details(self):
        order = ShopOrder.objects.create(
            mobile_number="9876543210",
            delivery_address="12 Example Road\nJaipur",
            subtotal=Decimal("120.00"),
        )
        ShopOrderItem.objects.create(
            order=order,
            product=self.first_product,
            product_name=self.first_product.name,
            color="Navy",
            size="M",
            quantity=2,
            unit_price=Decimal("60.00"),
        )

        orders_url = reverse("admin_orders")
        response = self.client.get(orders_url)
        self.assertRedirects(response, f"{reverse('admin_login')}?next=%2Fadmin%2Forders")

        session = self.client.session
        session["admin_id"] = 42
        session["admin_last_activity"] = time.time()
        session.save()
        response = self.client.get(orders_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{order.pk}")
        self.assertContains(response, "9876543210")
        self.assertContains(response, "12 Example Road")
        self.assertContains(response, "Linen Shirt")
        self.assertContains(response, "M × 2")
        self.assertContains(response, "Navy")
        self.assertContains(
            response,
            f'href="{reverse("product_detail", args=[self.first_product.pk])}"',
        )
        self.assertContains(response, "120.00")
        self.assertContains(response, reverse("admin_orders"))
        self.assertContains(response, "In progress")
        self.assertContains(response, "<th>Status</th>")
        self.assertContains(response, "<th>Remarks</th>")
        self.assertContains(response, "<th>Actions</th>")
        self.assertContains(response, f'id="order-update-{order.pk}"')
        self.assertContains(response, f'form="order-update-{order.pk}"')
        self.assertContains(response, 'type="submit" disabled>Save</button>')
        self.assertContains(
            response,
            f"Are you sure you want to delete order #{order.pk}? This cannot be undone.",
        )
        self.assertContains(response, "admin-orders.js")

    def test_admin_can_update_filter_and_order_orders(self):
        now = timezone.now()
        orders = [
            ShopOrder.objects.create(
                mobile_number=f"987654321{index}",
                delivery_address=f"{index} Example Road",
                subtotal=Decimal("60.00"),
                created_at=now + timedelta(minutes=index),
            )
            for index in range(3)
        ]
        orders[1].status = ShopOrder.Status.COMPLETED
        orders[1].remarks = "Packed"
        orders[1].save(update_fields=["status", "remarks"])

        session = self.client.session
        session["admin_id"] = 42
        session["admin_last_activity"] = time.time()
        session.save()

        response = self.client.get(reverse("admin_orders"))
        self.assertEqual(
            [order.pk for order in response.context["page"].object_list],
            [order.pk for order in orders],
        )
        self.assertContains(response, "In progress")

        response = self.client.get(reverse("admin_orders"), {"status": ShopOrder.Status.COMPLETED})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertContains(response, "Packed")

        update_url = reverse("admin_order_update", args=[orders[0].pk])
        response = self.client.post(
            update_url,
            {"status": ShopOrder.Status.CANCELLED, "remarks": "Customer requested cancellation"},
        )
        self.assertRedirects(response, reverse("admin_orders"))
        orders[0].refresh_from_db()
        self.assertEqual(orders[0].status, ShopOrder.Status.CANCELLED)
        self.assertEqual(orders[0].remarks, "Customer requested cancellation")

    def test_admin_can_delete_order_only_with_post(self):
        order = ShopOrder.objects.create(
            mobile_number="9876543210",
            delivery_address="12 Example Road",
            subtotal=Decimal("60.00"),
        )
        item = ShopOrderItem.objects.create(
            order=order,
            product=self.first_product,
            product_name=self.first_product.name,
            size="M",
            quantity=1,
            unit_price=Decimal("60.00"),
        )
        delete_url = reverse("admin_order_delete", args=[order.pk])

        response = self.client.post(
            delete_url,
            {"return_status": ShopOrder.Status.IN_PROGRESS},
        )
        self.assertRedirects(
            response,
            f"{reverse('admin_login')}?next=%2Fadmin%2Forders%2F{order.pk}%2Fdelete",
        )

        session = self.client.session
        session["admin_id"] = 42
        session["admin_last_activity"] = time.time()
        session.save()

        response = self.client.get(delete_url)
        self.assertEqual(response.status_code, 405)

        response = self.client.post(
            delete_url,
            {"return_status": ShopOrder.Status.IN_PROGRESS},
        )
        self.assertRedirects(
            response,
            f"{reverse('admin_orders')}?status={ShopOrder.Status.IN_PROGRESS}",
        )
        self.assertFalse(ShopOrder.objects.filter(pk=order.pk).exists())
        self.assertFalse(ShopOrderItem.objects.filter(pk=item.pk).exists())

    def test_missing_product_detail_returns_404(self):
        response = self.client.get(reverse("product_detail", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_admin_login_product_creation_and_delete(self):
        AdminAccount.objects.create(
            username="manager",
            password_hash=make_password("secure-password"),
        )
        response = self.client.post(
            reverse("admin_login"),
            {"username": "manager", "password": "secure-password"},
        )
        self.assertRedirects(response, reverse("admin_dashboard"))

        create_form_response = self.client.get(reverse("create_product"))
        self.assertContains(create_form_response, 'style="--swatch:#dc2626"')
        self.assertContains(create_form_response, 'style="--swatch:#2563eb"')
        self.assertNotContains(create_form_response, "data-save-size")

        images = [
            SimpleUploadedFile("shirt.png", b"test image", content_type="image/png"),
            SimpleUploadedFile("shirt-back.jpg", b"back image", content_type="image/jpeg"),
        ]
        videos = [
            SimpleUploadedFile("shirt.mp4", b"test video", content_type="video/mp4"),
        ]
        response = self.client.post(
            reverse("create_product"),
            {
                "name": "__other__",
                "name_other": "New Shirt",
                "cloth_type": "__other__",
                "cloth_type_other": "Woven blend",
                "category": "__other__",
                "category_other": "Festive wear",
                "occasion_category": "__other__",
                "occasion_category_other": "Graduation",
                "actual_price": "45.00",
                "offer_price": "",
                "stock": "3",
                "sizes": ["M"],
                "size_color_2_0": "1",
                "size_color_2_3": "1",
                "color_stock_2_0": "1",
                "color_stock_2_3": "2",
                "image_colors": ["Black", "Blue"],
                "images": images,
                "videos": videos,
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        product = Product.objects.get(name="New Shirt")
        self.assertEqual(product.cloth_type, "Woven blend")
        self.assertEqual(product.category, "Festive wear")
        self.assertEqual(product.occasion_category, "Graduation")
        self.assertEqual(product.size_stock, {"M": 3})
        self.assertEqual(product.color_stock, {"Black": {"M": 1}, "Blue": {"M": 2}})
        self.assertEqual(product.color_values, {"Black": "#000000", "Blue": "#2563eb"})
        self.assertEqual(product.stock, 3)
        self.assertEqual(product.media_items.count(), 3)
        self.assertEqual(
            list(product.media_items.filter(media_type="image").values_list("color", flat=True)),
            ["Black", "Blue"],
        )
        media_response = self.client.get(reverse("product_modal_data", args=[product.pk]))
        self.assertEqual(
            [media["color"] for media in media_response.json()["media"][:2]],
            ["Black", "Blue"],
        )
        self.assertEqual(
            list(product.media_items.values_list("media_type", flat=True)),
            ["image", "image", "video"],
        )
        first_image = product.media_items.filter(media_type="image").first()
        first_video = product.media_items.filter(media_type="video").get()
        self.assertEqual(base64.b64decode(first_image.data_url.partition(",")[2]), b"test image")
        self.assertEqual(base64.b64decode(first_video.data_url.partition(",")[2]), b"test video")

        response = self.client.get(reverse("index"), {"q": "New Shirt"})
        self.assertContains(response, reverse("product_detail", args=[product.pk]))

        response = self.client.get(reverse("edit_product", args=[product.pk]))
        self.assertNotContains(response, 'id="colors"')
        self.assertNotContains(response, "Available colors")
        self.assertContains(response, 'name="color_stock_2_0"')
        self.assertContains(response, 'name="color_stock_2_1"')
        self.assertContains(response, 'class="form-group full size-color-panels"')
        self.assertNotContains(response, 'name="size_stock_2"')
        self.assertNotContains(response, 'class="legacy-size-quantity"')
        self.assertContains(response, 'type="search" class="size-color-search"')
        self.assertContains(response, 'class="color-picker-dropdown"')
        self.assertContains(response, 'class="color-selection-display">Color</span>')
        self.assertContains(response, 'data-color="Black" name="size_color_2_0" value="1" checked>')
        self.assertContains(response, 'class="selected-color-stock-list"')
        self.assertContains(response, 'aria-label="Black quantity in size M"')
        self.assertContains(response, 'style="--swatch:#000000"')
        self.assertContains(response, 'class="size-total-stock"')
        self.assertNotContains(response, 'data-save-size')
        self.assertContains(response, '<output class="size-total-quantity">3</output>')
        self.assertContains(response, 'id="cloth_type"')
        self.assertContains(response, 'id="category"')
        self.assertContains(response, 'id="occasion_category"')
        self.assertContains(response, 'value="Woven blend" selected')
        self.assertContains(response, 'value="Festive wear" selected')
        self.assertContains(response, 'value="Graduation" selected')

        response = self.client.post(
            reverse("edit_product", args=[product.pk]),
            {
                "name": "New Shirt",
                "name_other": "",
                "cloth_type": "Cotton",
                "category": "Tops",
                "occasion_category": "Party",
                "actual_price": "55.00",
                "offer_price": "",
                "stock": "6",
                "sizes": ["M"],
                "description": "Updated details",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose at least one color and quantity for size M.")
        product.refresh_from_db()
        self.assertEqual(product.color_stock, {"Black": {"M": 1}, "Blue": {"M": 2}})

        response = self.client.post(
            reverse("edit_product", args=[product.pk]),
            {
                "name": "New Shirt",
                "name_other": "",
                "cloth_type": "Cotton",
                "category": "Tops",
                "occasion_category": "Party",
                "actual_price": "55.00",
                "offer_price": "",
                "stock": "6",
                "sizes": ["M"],
                "size_color_2_0": "1",
                "color_stock_2_0": "6",
                "description": "Updated details",
                "remove_media": [str(first_image.pk)],
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        product.refresh_from_db()
        self.assertEqual(str(product.actual_price), "55.00")
        self.assertEqual(product.description, "Updated details")
        self.assertEqual(product.occasion_category, "Party")
        self.assertEqual(product.size_stock, {"M": 6})
        self.assertEqual(product.color_stock, {"Black": {"M": 6}})
        self.assertEqual(product.stock, 6)
        self.assertEqual(product.media_items.count(), 2)
        self.assertFalse(product.media_items.filter(pk=first_image.pk).exists())

        response = self.client.post(reverse("delete_product", args=[product.pk]))
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_admin_session_expires_after_inactivity(self):
        session = self.client.session
        session["admin_id"] = 42
        session["admin_last_activity"] = time.time() - (31 * 60)
        session.save()

        response = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(response, f"{reverse('admin_login')}?next=%2Fadmin")

    def test_offer_price_must_be_below_actual_price(self):
        AdminAccount.objects.create(
            username="manager",
            password_hash=make_password("secure-password"),
        )
        self.client.post(
            reverse("admin_login"),
            {"username": "manager", "password": "secure-password"},
        )
        response = self.client.post(
            reverse("create_product"),
            {
                "name": "__other__",
                "name_other": "Invalid Offer",
                "cloth_type": "Cotton",
                "category": "Tops",
                "occasion_category": "Casual",
                "actual_price": "45.00",
                "offer_price": "50.00",
                "stock": "3",
                "sizes": ["M"],
                "images": [SimpleUploadedFile("invalid.png", b"image", content_type="image/png")],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(name="Invalid Offer").exists())

    def test_product_stock_must_be_greater_than_zero(self):
        AdminAccount.objects.create(
            username="manager",
            password_hash=make_password("secure-password"),
        )
        self.client.post(
            reverse("admin_login"),
            {"username": "manager", "password": "secure-password"},
        )
        response = self.client.post(
            reverse("create_product"),
            {
                "name": "__other__",
                "name_other": "No Stock Product",
                "cloth_type": "Cotton",
                "category": "Tops",
                "occasion_category": "Casual",
                "actual_price": "45.00",
                "offer_price": "",
                "stock": "0",
                "sizes": ["M"],
                "size_color_2_0": "1",
                "color_stock_2_0": "0",
                "images": [SimpleUploadedFile("stock.png", b"image", content_type="image/png")],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total stock across colors and sizes must be at least 1.")
        self.assertFalse(Product.objects.filter(name="No Stock Product").exists())
