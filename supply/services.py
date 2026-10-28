from django.db import transaction
from rest_framework.exceptions import ValidationError

from supply.models import FulfilmentOrder, OrderLine, StockLevel


def _lock_order(order):
    return FulfilmentOrder.objects.select_for_update().get(pk=order.pk)


def replace_lines(order, lines):
    order.lines.all().delete()
    OrderLine.objects.bulk_create(
        [
            OrderLine(order=order, product=line["product"], quantity=line["quantity"])
            for line in lines
        ]
    )


def allocate_order(order):
    # Two pickers can both read "5 left" and both pass. Lock the rows first.
    with transaction.atomic():
        order = _lock_order(order)
        if order.status != FulfilmentOrder.Status.OPEN:
            raise ValidationError("Only an open order can be allocated.")
        lines = list(order.lines.select_related("product"))
        if not lines:
            raise ValidationError("Add at least one product before allocating.")
        levels = {
            level.product_id: level
            for level in StockLevel.objects.select_for_update().filter(
                warehouse=order.warehouse,
                product_id__in=[line.product_id for line in lines],
            )
        }
        short = []
        for line in lines:
            level = levels.get(line.product_id)
            on_hand = level.quantity_on_hand if level else 0
            if on_hand < line.quantity:
                short.append(line.product.sku)
        if short:
            raise ValidationError(
                "Not enough stock for: " + ", ".join(short) + "."
            )
        for line in lines:
            level = levels[line.product_id]
            level.quantity_on_hand -= line.quantity
            level.save(update_fields=["quantity_on_hand"])
        order.status = FulfilmentOrder.Status.ALLOCATED
        order.save(update_fields=["status", "updated_at"])
        return order


def ship_order(order):
    with transaction.atomic():
        order = _lock_order(order)
        if order.status != FulfilmentOrder.Status.ALLOCATED:
            raise ValidationError("Allocate the stock before this leaves the building.")
        order.status = FulfilmentOrder.Status.SHIPPED
        order.save(update_fields=["status", "updated_at"])
        return order


def cancel_order(order):
    with transaction.atomic():
        order = _lock_order(order)
        if order.status == FulfilmentOrder.Status.SHIPPED:
            raise ValidationError("A shipped order stays on the books.")
        if order.status == FulfilmentOrder.Status.CANCELLED:
            return order
        if order.status == FulfilmentOrder.Status.ALLOCATED:
            lines = list(order.lines.select_related("product"))
            levels = {
                level.product_id: level
                for level in StockLevel.objects.select_for_update().filter(
                    warehouse=order.warehouse,
                    product_id__in=[line.product_id for line in lines],
                )
            }
            for line in lines:
                level = levels.get(line.product_id)
                if level is None:
                    continue
                level.quantity_on_hand += line.quantity
                level.save(update_fields=["quantity_on_hand"])
        order.status = FulfilmentOrder.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return order
