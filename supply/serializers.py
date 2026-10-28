from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from supply.models import FulfilmentOrder, OrderLine, Product, StockLevel, Supplier, User, Warehouse
from supply.services import replace_lines


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "role"]
        read_only_fields = ["id", "role"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "code", "contact_email", "is_active"]

    def validate_code(self, value):
        value = value.strip().upper()
        taken = Supplier.objects.filter(code=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("A supplier with this code already exists.")
        return value


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "name", "code", "city"]

    def validate_code(self, value):
        value = value.strip().upper()
        taken = Warehouse.objects.filter(code=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("A warehouse with this code already exists.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(
        max_length=40,
        help_text="Stored in uppercase. This is how the dock looks a product up.",
    )

    class Meta:
        model = Product
        fields = ["id", "sku", "name", "supplier", "unit_cost", "reorder_level", "is_active"]

    def validate_unit_cost(self, value):
        if value < 0:
            raise serializers.ValidationError("Cost cannot be negative.")
        return value

    def validate_sku(self, value):
        value = value.strip().upper()
        taken = Product.objects.filter(sku=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value


class StockLevelSerializer(serializers.ModelSerializer):
    quantity_on_hand = serializers.IntegerField(
        min_value=0,
        help_text="Units sitting in this warehouse right now.",
    )

    class Meta:
        model = StockLevel
        fields = ["id", "product", "warehouse", "quantity_on_hand"]

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        if product and warehouse:
            taken = StockLevel.objects.filter(product=product, warehouse=warehouse)
            if self.instance is not None:
                taken = taken.exclude(pk=self.instance.pk)
            if taken.exists():
                raise serializers.ValidationError(
                    "This warehouse already has a row for that product."
                )
        return attrs


class OrderLineSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = OrderLine
        fields = ["id", "product", "sku", "product_name", "quantity"]


class OrderLineWriteSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)


class FulfilmentOrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True, read_only=True)
    line_items = OrderLineWriteSerializer(many=True, write_only=True, required=False)
    requested_by = serializers.PrimaryKeyRelatedField(read_only=True)
    reference = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = FulfilmentOrder
        fields = [
            "id",
            "reference",
            "requested_by",
            "warehouse",
            "status",
            "ship_to_name",
            "ship_to_city",
            "lines",
            "line_items",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        creating = self.instance is None
        line_items = attrs.get("line_items")
        if creating and not line_items:
            raise serializers.ValidationError({"line_items": "Add at least one product."})
        if line_items is not None:
            product_ids = [item["product"].id for item in line_items]
            if len(product_ids) != len(set(product_ids)):
                raise serializers.ValidationError(
                    {"line_items": "Each product should appear once. Raise the quantity instead."}
                )
        if self.instance and self.instance.status != FulfilmentOrder.Status.OPEN and attrs:
            raise serializers.ValidationError("This order is no longer open.")
        return attrs

    def create(self, validated_data):
        line_items = validated_data.pop("line_items")
        order = FulfilmentOrder.objects.create(
            requested_by=self.context["request"].user,
            status=FulfilmentOrder.Status.OPEN,
            **validated_data,
        )
        replace_lines(order, line_items)
        return order

    def update(self, instance, validated_data):
        line_items = validated_data.pop("line_items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if line_items is not None:
            replace_lines(instance, line_items)
        return instance
