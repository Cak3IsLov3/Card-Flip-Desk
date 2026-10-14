from django.contrib import admin

from .models import FeeProfile


@admin.register(FeeProfile)
class FeeProfileAdmin(admin.ModelAdmin):
    list_display = ("category", "user", "commission_percentage", "fixed_fee", "payment_percentage", "valid_from")
    list_filter = ("category",)
