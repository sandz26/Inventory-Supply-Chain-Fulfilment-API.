import secrets

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STANDARD = "standard", "Standard"

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STANDARD,
        db_index=True,
    )

    def save(self, *args, **kwargs):
        # The first account is Django's superuser. Keep that and role in step.
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)
    contact_email = models.EmailField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} {self.name}"


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)
    city = models.CharField(max_length=80)

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} ({self.city})"


class Product(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="products")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    reorder_level = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sku"]
        # A buyer opens one supplier and only wants the live catalogue.
        indexes = [
            models.Index(fields=["supplier", "is_active"], name="product_supplier_active_idx"),
        ]

    def clean(self):
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValidationError({"unit_cost": "Cost cannot be negative."})

    def save(self, *args, **kwargs):
        self.sku = self.sku.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} {self.name}"


class StockLevel(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_levels")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels")
    quantity_on_hand = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["warehouse_id", "product_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "product"],
                name="stock_one_row_per_wh_sku",
            ),
        ]
        # Low-stock checks start at a building, then look at what is left.
        indexes = [
            models.Index(fields=["warehouse", "quantity_on_hand"], name="stock_wh_qty_idx"),
        ]

    def __str__(self):
        return f"{self.warehouse.code} {self.product.sku}: {self.quantity_on_hand}"


class FulfilmentOrder(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ALLOCATED = "allocated", "Allocated"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=20, unique=True, blank=True)
    requested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    ship_to_name = models.CharField(max_length=120)
    ship_to_city = models.CharField(max_length=80)
    products = models.ManyToManyField(Product, through="OrderLine", related_name="orders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # The floor list is open work, oldest first.
            models.Index(fields=["status", "created_at"], name="order_status_created_idx"),
            # A person opening their own jobs wants the newest at the top.
            models.Index(fields=["requested_by", "-created_at"], name="order_user_recent_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "FO-" + secrets.token_hex(3).upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} ({self.status})"


class OrderLine(models.Model):
    order = models.ForeignKey(FulfilmentOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="one_line_per_product"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="line_quantity_at_least_one",
            ),
        ]

    def clean(self):
        if self.quantity is not None and self.quantity < 1:
            raise ValidationError({"quantity": "Order at least one."})

    def __str__(self):
        return f"{self.order.reference} x {self.quantity} {self.product.sku}"
