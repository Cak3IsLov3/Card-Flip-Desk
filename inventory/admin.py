from django.contrib import admin

from .models import Card, Purchase


class PurchaseInline(admin.TabularInline):
    model = Purchase
    extra = 0


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("__str__", "owner", "variant_display", "status", "listed_since")
    list_filter = ("status", "sport")
    search_fields = ("player", "set_name", "card_number")
    inlines = [PurchaseInline]
