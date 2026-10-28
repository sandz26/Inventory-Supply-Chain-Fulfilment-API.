from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from supply.views import (
    FulfilmentOrderViewSet,
    ProductViewSet,
    StockLevelViewSet,
    SupplierViewSet,
    WarehouseViewSet,
    health,
    me,
    register,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("products", ProductViewSet, basename="product")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("stock", StockLevelViewSet, basename="stock")
router.register("orders", FulfilmentOrderViewSet, basename="order")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/auth/register/", register, name="register"),
    path(
        "api/auth/token/",
        TokenObtainPairView.as_view(permission_classes=[AllowAny]),
        name="token",
    ),
    path(
        "api/auth/token/refresh/",
        TokenRefreshView.as_view(permission_classes=[AllowAny]),
        name="token-refresh",
    ),
    path("api/auth/me/", me, name="me"),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[AllowAny]), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny]),
        name="swagger-ui",
    ),
    path("api/", include(router.urls)),
]
