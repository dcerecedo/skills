from shop.catalog.product import Product


class Order:
    def __init__(self, order_id: str, product: Product, quantity: int):
        self.order_id = order_id
        self.product = product
        self.quantity = quantity

    def total(self) -> int:
        return self.product.price * self.quantity

    def confirm(self) -> str:
        from shop.orders.service import place_order  # function-local: still an edge

        return place_order(self)
