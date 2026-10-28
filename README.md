# Inventory & Supply Chain Fulfilment API

Outbound fulfilment for one warehouse network: suppliers, SKUs, stock on hand, and the orders that draw that stock down. This is the odd-numbered candidate track (id ending 81).

## Setup

```bash
docker-compose up --build
```

The API listens on http://127.0.0.1:8000. Swagger is at http://127.0.0.1:8000/api/docs/.

Create the first admin (Django's superuser is treated as an admin):

```bash
docker-compose exec web python manage.py createsuperuser
```

`POSTGRES_HOST` switches the app onto PostgreSQL. Leave it unset and the same code uses a local SQLite file, which is what `pytest` does on a machine without Docker.

## Auth

`POST /api/auth/register/` creates a standard user. `POST /api/auth/token/` returns a bearer access token (1 hour) and a refresh token. Send `Authorization: Bearer <access>`. Admins can change suppliers, products, warehouses, and stock. Anyone signed in can read those. Orders belong to the person who opened them; an admin can see every order, allocate stock, and mark it shipped.

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}'
```

```bash
curl -s http://127.0.0.1:8000/api/products/ \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/orders/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "warehouse": 1,
    "ship_to_name": "River Cafe",
    "ship_to_city": "Pretoria",
    "line_items": [{"product": 1, "quantity": 2}]
  }'
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/orders/1/allocate/ \
  -H "Authorization: Bearer $TOKEN"
```

`/health/` returns `status`, `database`, and `uptime_seconds` with no token.

Failed requests share one body: `error.code`, `error.message`, and `error.details`.

## Why these indexes

- `product (supplier, is_active)` — a buyer opens one supplier and only wants the live catalogue, not every SKU in the building.
- `stock (warehouse, quantity_on_hand)` — the low-stock page always starts from a warehouse and then looks at what is left. The reorder level lives on the product, so the comparison happens after that index has already narrowed the rows.
- Unique `(warehouse, product)` on stock — two people receiving the same delivery should not create two piles for one SKU.
- `order (status, created_at)` — the floor list is the open work, oldest first.
- `order (requested_by, created_at desc)` — someone opening their own jobs wants the newest at the top, and that query should not scan every order in the building.
- `sku`, supplier `code`, warehouse `code`, and the order `reference` are unique because that is how people actually look a row up.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Coverage has to stay at 80% or better. GitHub Actions lints with flake8, runs the tests against PostgreSQL, and builds the image only after both succeed.
