from django.urls import path

from . import views


urlpatterns = [
    path("", views.index, name="index"),
    path("api/credentials", views.add_credential, name="add_credential"),
    path("media-cache/<path:key>", views.cached_thumbnail, name="cached_thumbnail"),
    path("media/<path:key>", views.serve_s3_media, name="serve_s3_media"),
    path("products/more", views.more_products, name="more_products"),
    path("products/<int:product_id>/", views.product_detail, name="product_detail"),
    path("products/<int:product_id>/modal", views.product_modal_data, name="product_modal_data"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/complete/", views.checkout_complete, name="checkout_complete"),
    path("admin/login", views.admin_login, name="admin_login"),
    path("admin/logout", views.admin_logout, name="admin_logout"),
    path("admin", views.admin_dashboard, name="admin_dashboard"),
    path("admin/product-names/delete", views.delete_product_name_option, name="delete_product_name_option"),
    path("admin/orders", views.admin_orders, name="admin_orders"),
    path("admin/orders/<int:order_id>/update", views.admin_order_update, name="admin_order_update"),
    path("admin/orders/<int:order_id>/delete", views.admin_order_delete, name="admin_order_delete"),
    path("admin/products/new", views.create_product, name="create_product"),
    path("admin/products/<int:product_id>/edit", views.edit_product, name="edit_product"),
    path("admin/products/<int:product_id>/delete", views.delete_product, name="delete_product"),
]
