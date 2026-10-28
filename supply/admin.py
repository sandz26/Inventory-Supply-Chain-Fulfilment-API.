from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from supply.models import FulfilmentOrder, OrderLine, Product, StockLevel, Supplier, User, Warehouse


@admin.register(User)
class SupplyUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_superuser")


admin.site.register(Supplier)
admin.site.register(Warehouse)
admin.site.register(Product)
admin.site.register(StockLevel)


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(FulfilmentOrder)
class FulfilmentOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "status", "warehouse", "requested_by", "created_at")
    inlines = [OrderLineInline]
