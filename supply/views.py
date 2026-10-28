import time

from django.db import OperationalError, connection
from django.db.models import F, ProtectedError
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from supply.models import FulfilmentOrder, Product, StockLevel, Supplier, Warehouse
from supply.permissions import IsAdminRole, IsOwnerOrAdmin, is_admin
from supply.serializers import (
    FulfilmentOrderSerializer,
    ProductSerializer,
    RegisterSerializer,
    StockLevelSerializer,
    SupplierSerializer,
    UserSerializer,
    WarehouseSerializer,
)
from supply.services import allocate_order, cancel_order, ship_order

STARTED = time.monotonic()


def health(request):
    """Process is up, and we can still talk to the database."""
    database = "connected"
    service_status = "ok"
    code = 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        database = "unavailable"
        service_status = "down"
        code = 503
    return JsonResponse(
        {
            "status": service_status,
            "database": database,
            "uptime_seconds": round(time.monotonic() - STARTED, 3),
        },
        status=code,
    )


@extend_schema(request=RegisterSerializer, responses=UserSerializer)
@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """Create a standard account. Role is always standard from this route."""
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=UserSerializer)
@api_view(["GET"])
def me(request):
    """The account attached to the bearer token."""
    return Response(UserSerializer(request.user).data)


class AdminWriteViewSet(viewsets.ModelViewSet):
    """Signed-in users can read. Changing a row is an admin action."""

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsAdminRole()]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError(
                "This is still in use. Clear the stock or orders that point at it."
            )


class SupplierViewSet(AdminWriteViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer


class WarehouseViewSet(AdminWriteViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer


class ProductViewSet(AdminWriteViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = Product.objects.select_related("supplier")
        supplier = self.request.query_params.get("supplier")
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)
        active = self.request.query_params.get("active")
        if active in ("1", "0"):
            queryset = queryset.filter(is_active=active == "1")
        return queryset


class StockLevelViewSet(AdminWriteViewSet):
    serializer_class = StockLevelSerializer

    def get_queryset(self):
        queryset = StockLevel.objects.select_related("product", "warehouse")
        warehouse = self.request.query_params.get("warehouse")
        if warehouse:
            queryset = queryset.filter(warehouse_id=warehouse)
        if self.request.query_params.get("low") == "1":
            queryset = queryset.filter(quantity_on_hand__lte=F("product__reorder_level"))
        return queryset


class FulfilmentOrderViewSet(viewsets.ModelViewSet):
    """Outbound orders. Staff open them. Admins allocate and ship."""

    serializer_class = FulfilmentOrderSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = FulfilmentOrder.objects.select_related(
            "warehouse", "requested_by"
        ).prefetch_related("lines__product")
        if not is_admin(self.request.user):
            queryset = queryset.filter(requested_by=self.request.user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def get_permissions(self):
        if self.action in ("allocate", "ship"):
            return [IsAdminRole()]
        if self.action in ("update", "partial_update", "destroy", "cancel"):
            return [IsAuthenticated(), IsOwnerOrAdmin()]
        return [IsAuthenticated()]

    def perform_destroy(self, instance):
        if instance.status != FulfilmentOrder.Status.OPEN:
            raise ValidationError("Cancel an allocated order first so the stock goes back.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        """Hold the units on the shelf against this order."""
        order = allocate_order(self.get_object())
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        """Mark the order as having left the warehouse."""
        order = ship_order(self.get_object())
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Stop the order. Allocated units go back on the shelf."""
        order = cancel_order(self.get_object())
        return Response(self.get_serializer(order).data)
