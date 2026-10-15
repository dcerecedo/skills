from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shop.orders.models import Order


class Product:
    def __init__(self, sku: str, price: int):
        self.sku = sku
        self.price = price

    def ordered_in(self, order: Order) -> bool:
        return order.product.sku == self.sku
