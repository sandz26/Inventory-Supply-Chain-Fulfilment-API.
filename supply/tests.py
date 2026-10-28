from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from supply.models import FulfilmentOrder, Product, StockLevel, Supplier, User, Warehouse


PASSWORD = "S3cure-Stock-Pass"


def make_user(username, role=User.Role.STANDARD):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
        role=role,
    )


class AuthTests(APITestCase):
    def test_register_login_and_me(self):
        created = self.client.post(
            reverse("register"),
            {
                "username": "picker",
                "email": "picker@example.com",
                "password": PASSWORD,
                "role": "admin",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["role"], User.Role.STANDARD)

        token = self.client.post(
            reverse("token"),
            {"username": "picker", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(token.status_code, status.HTTP_200_OK)
        access = token.data["access"]
        refreshed = self.client.post(
            reverse("token-refresh"),
            {"refresh": token.data["refresh"]},
            format="json",
        )
        self.assertEqual(refreshed.status_code, status.HTTP_200_OK)
        self.assertIn("access", refreshed.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me = self.client.get(reverse("me"))
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["username"], "picker")

    def test_bad_login_uses_the_error_schema(self):
        response = self.client.post(
            reverse("token"),
            {"username": "missing", "password": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")
        self.assertIn("message", response.data["error"])
        self.assertIsNone(response.data["error"]["details"])

    def test_short_password_is_a_validation_error(self):
        response = self.client.post(
            reverse("register"),
            {"username": "short", "email": "short@example.com", "password": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("password", response.data["error"]["details"])


class CatalogueTests(APITestCase):
    def setUp(self):
        self.admin = make_user("ada", User.Role.ADMIN)
        self.staff = make_user("sam")
        self.supplier = Supplier.objects.create(
            name="North Mill",
            code="nm",
            contact_email="mill@example.com",
        )
        self.warehouse = Warehouse.objects.create(name="Main", code="jhb", city="Johannesburg")
        self.product = Product.objects.create(
            sku="bolt-1",
            name="Bolt",
            supplier=self.supplier,
            unit_cost=Decimal("2.50"),
            reorder_level=5,
        )

    def auth(self, user):
        self.client.force_authenticate(user)

    def test_standard_user_can_read_but_not_write(self):
        self.auth(self.staff)
        listing = self.client.get("/api/products/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["results"][0]["sku"], "BOLT-1")

        denied = self.client.post(
            "/api/products/",
            {
                "sku": "NUT-1",
                "name": "Nut",
                "supplier": self.supplier.id,
                "unit_cost": "1.00",
                "reorder_level": 2,
            },
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(denied.data["error"]["code"], "permission_denied")

        anonymous = self.client
        self.client.force_authenticate(user=None)
        hidden = anonymous.get("/api/products/")
        self.assertEqual(hidden.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_crud_and_filters(self):
        self.auth(self.admin)
        created = self.client.post(
            "/api/suppliers/",
            {"name": "South Loom", "code": "sl", "contact_email": "loom@example.com"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["code"], "SL")
        supplier_id = created.data["id"]

        renamed = self.client.patch(
            f"/api/suppliers/{supplier_id}/",
            {"name": "South Loom Co"},
            format="json",
        )
        self.assertEqual(renamed.status_code, status.HTTP_200_OK)

        replaced = self.client.put(
            f"/api/suppliers/{supplier_id}/",
            {
                "name": "South Loom Co",
                "code": "sl",
                "contact_email": "loom@example.com",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(replaced.status_code, status.HTTP_200_OK)

        warehouse = self.client.post(
            "/api/warehouses/",
            {"name": "Coast", "code": "dbn", "city": "Durban"},
            format="json",
        )
        self.assertEqual(warehouse.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.client.get(f"/api/warehouses/{warehouse.data['id']}/").status_code,
            status.HTTP_200_OK,
        )

        product = self.client.post(
            "/api/products/",
            {
                "sku": "nut-9",
                "name": "Nut",
                "supplier": supplier_id,
                "unit_cost": "1.25",
                "reorder_level": 4,
            },
            format="json",
        )
        self.assertEqual(product.status_code, status.HTTP_201_CREATED)
        product_id = product.data["id"]
        self.assertEqual(self.client.get(f"/api/products/{product_id}/").data["sku"], "NUT-9")

        duplicate = self.client.post(
            "/api/products/",
            {
                "sku": "nut-9",
                "name": "Other",
                "supplier": supplier_id,
                "unit_cost": "1.00",
                "reorder_level": 1,
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        negative = self.client.post(
            "/api/products/",
            {
                "sku": "bad-1",
                "name": "Bad",
                "supplier": supplier_id,
                "unit_cost": "-1.00",
                "reorder_level": 1,
            },
            format="json",
        )
        self.assertEqual(negative.status_code, status.HTTP_400_BAD_REQUEST)

        filtered = self.client.get(f"/api/products/?supplier={supplier_id}&active=1")
        self.assertEqual(filtered.data["count"], 1)

        stock = self.client.post(
            "/api/stock/",
            {"product": product_id, "warehouse": warehouse.data["id"], "quantity_on_hand": 3},
            format="json",
        )
        self.assertEqual(stock.status_code, status.HTTP_201_CREATED)
        again = self.client.post(
            "/api/stock/",
            {"product": product_id, "warehouse": warehouse.data["id"], "quantity_on_hand": 8},
            format="json",
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)

        low = self.client.get(f"/api/stock/?warehouse={warehouse.data['id']}&low=1")
        self.assertEqual(low.data["count"], 1)

        patched = self.client.patch(
            f"/api/stock/{stock.data['id']}/",
            {"quantity_on_hand": 1},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)

        removed = self.client.delete(f"/api/stock/{stock.data['id']}/")
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        product_gone = self.client.delete(f"/api/products/{product_id}/")
        self.assertEqual(product_gone.status_code, status.HTTP_204_NO_CONTENT)
        warehouse_gone = self.client.delete(f"/api/warehouses/{warehouse.data['id']}/")
        self.assertEqual(warehouse_gone.status_code, status.HTTP_204_NO_CONTENT)
        supplier_gone = self.client.delete(f"/api/suppliers/{supplier_id}/")
        self.assertEqual(supplier_gone.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_is_blocked_while_stock_still_points_at_the_product(self):
        self.auth(self.admin)
        StockLevel.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity_on_hand=2,
        )
        response = self.client.delete(f"/api/products/{self.product.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")


class OrderTests(APITestCase):
    def setUp(self):
        self.admin = make_user("ada", User.Role.ADMIN)
        self.owner = make_user("sam")
        self.other = make_user("lee")
        self.supplier = Supplier.objects.create(
            name="North Mill",
            code="NM",
            contact_email="mill@example.com",
        )
        self.warehouse = Warehouse.objects.create(name="Main", code="JHB", city="Johannesburg")
        self.product = Product.objects.create(
            sku="BOLT-1",
            name="Bolt",
            supplier=self.supplier,
            unit_cost=Decimal("2.50"),
            reorder_level=5,
        )
        self.stock = StockLevel.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity_on_hand=10,
        )

    def auth(self, user):
        self.client.force_authenticate(user)

    def open_order(self, user, quantity=4):
        self.auth(user)
        return self.client.post(
            "/api/orders/",
            {
                "warehouse": self.warehouse.id,
                "ship_to_name": "River Cafe",
                "ship_to_city": "Pretoria",
                "line_items": [{"product": self.product.id, "quantity": quantity}],
            },
            format="json",
        )

    def test_owner_crud_and_admin_fulfilment(self):
        created = self.open_order(self.owner)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        order_id = created.data["id"]
        self.assertEqual(created.data["status"], "open")
        self.assertTrue(created.data["reference"].startswith("FO-"))
        self.assertEqual(created.data["lines"][0]["sku"], "BOLT-1")

        listing = self.client.get("/api/orders/")
        self.assertEqual(listing.data["count"], 1)
        detail = self.client.get(f"/api/orders/{order_id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

        patched = self.client.patch(
            f"/api/orders/{order_id}/",
            {
                "ship_to_city": "Cape Town",
                "line_items": [{"product": self.product.id, "quantity": 2}],
            },
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["lines"][0]["quantity"], 2)

        self.auth(self.other)
        hidden = self.client.get(f"/api/orders/{order_id}/")
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get("/api/orders/").data["count"], 0)

        self.auth(self.owner)
        denied = self.client.post(f"/api/orders/{order_id}/allocate/")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.auth(self.admin)
        self.assertEqual(self.client.get("/api/orders/?status=open").data["count"], 1)
        allocated = self.client.post(f"/api/orders/{order_id}/allocate/")
        self.assertEqual(allocated.status_code, status.HTTP_200_OK)
        self.assertEqual(allocated.data["status"], "allocated")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 8)

        too_soon = self.client.post(f"/api/orders/{order_id}/ship/")
        self.assertEqual(too_soon.status_code, status.HTTP_200_OK)

        frozen = self.client.patch(
            f"/api/orders/{order_id}/",
            {"ship_to_city": "Durban"},
            format="json",
        )
        self.assertEqual(frozen.status_code, status.HTTP_400_BAD_REQUEST)
        lines_frozen = self.client.patch(
            f"/api/orders/{order_id}/",
            {"line_items": [{"product": self.product.id, "quantity": 1}]},
            format="json",
        )
        self.assertEqual(lines_frozen.status_code, status.HTTP_400_BAD_REQUEST)

        self.auth(self.owner)
        cancelled = self.client.post(f"/api/orders/{order_id}/cancel/")
        self.assertEqual(cancelled.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("shipped", cancelled.data["error"]["message"].lower())

    def test_short_stock_does_not_move_the_count_and_cancel_puts_it_back(self):
        created = self.open_order(self.owner, quantity=50)
        order_id = created.data["id"]
        self.auth(self.admin)
        refused = self.client.post(f"/api/orders/{order_id}/allocate/")
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 10)

        small = self.open_order(self.owner, quantity=3)
        small_id = small.data["id"]
        self.auth(self.admin)
        allocated = self.client.post(f"/api/orders/{small_id}/allocate/")
        self.assertEqual(allocated.status_code, status.HTTP_200_OK)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 7)

        self.auth(self.owner)
        cancelled = self.client.post(f"/api/orders/{small_id}/cancel/")
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 10)

        again = self.client.post(f"/api/orders/{small_id}/cancel/")
        self.assertEqual(again.status_code, status.HTTP_200_OK)

        self.auth(self.admin)
        still_open = self.client.post(f"/api/orders/{order_id}/ship/")
        self.assertEqual(still_open.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_lines_and_delete_rules(self):
        self.auth(self.owner)
        duplicate = self.client.post(
            "/api/orders/",
            {
                "warehouse": self.warehouse.id,
                "ship_to_name": "River Cafe",
                "ship_to_city": "Pretoria",
                "line_items": [
                    {"product": self.product.id, "quantity": 1},
                    {"product": self.product.id, "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        created = self.open_order(self.owner, quantity=1)
        order_id = created.data["id"]
        removed = self.client.delete(f"/api/orders/{order_id}/")
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)

        second = self.open_order(self.owner, quantity=1)
        self.auth(self.admin)
        self.client.post(f"/api/orders/{second.data['id']}/allocate/")
        blocked = self.client.delete(f"/api/orders/{second.data['id']}/")
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_replaces_an_open_order(self):
        created = self.open_order(self.owner)
        response = self.client.put(
            f"/api/orders/{created.data['id']}/",
            {
                "warehouse": self.warehouse.id,
                "ship_to_name": "Other Cafe",
                "ship_to_city": "Durban",
                "line_items": [{"product": self.product.id, "quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["ship_to_name"], "Other Cafe")


class HealthAndDocsTests(APITestCase):
    def test_health_reports_the_database(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["database"], "connected")
        self.assertGreaterEqual(response.json()["uptime_seconds"], 0)

    def test_health_when_the_database_is_quiet(self):
        with patch("supply.views.connection.cursor", side_effect=OperationalError("down")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["database"], "unavailable")

    def test_schema_and_swagger_are_public(self):
        schema = self.client.get(reverse("schema"))
        self.assertEqual(schema.status_code, status.HTTP_200_OK)
        docs = self.client.get(reverse("swagger-ui"))
        self.assertEqual(docs.status_code, status.HTTP_200_OK)


class ModelTests(APITestCase):
    def test_normalises_codes_and_rejects_a_negative_cost(self):
        user = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertEqual(str(user), "root")

        supplier = Supplier.objects.create(name="Mill", code="ab", contact_email="a@example.com")
        self.assertEqual(supplier.code, "AB")
        self.assertIn("AB", str(supplier))

        warehouse = Warehouse.objects.create(name="Main", code="jhb", city="Johannesburg")
        self.assertEqual(warehouse.code, "JHB")

        product = Product(
            sku="bolt-1",
            name="Bolt",
            supplier=supplier,
            unit_cost=Decimal("-1.00"),
            reorder_level=1,
        )
        with self.assertRaises(DjangoValidationError):
            product.full_clean()

        product.unit_cost = Decimal("1.00")
        product.save()
        self.assertEqual(product.sku, "BOLT-1")

        stock = StockLevel.objects.create(product=product, warehouse=warehouse, quantity_on_hand=4)
        self.assertIn("BOLT-1", str(stock))

        order = FulfilmentOrder.objects.create(
            requested_by=user,
            warehouse=warehouse,
            ship_to_name="Cafe",
            ship_to_city="Durban",
        )
        self.assertTrue(order.reference.startswith("FO-"))
        line = order.lines.create(product=product, quantity=2)
        self.assertIn("BOLT-1", str(line))
        self.assertIn(order.reference, str(order))
        line.quantity = 0
        with self.assertRaises(DjangoValidationError):
            line.full_clean()
