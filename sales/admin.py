from django.contrib import admin

from .models import Listing, Sale


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "card", "asking_price", "status")
    list_filter = ("status",)


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("listing", "sale_price", "shipping_income", "ebay_commission", "sold_at")
    date_hierarchy = "sold_at"
