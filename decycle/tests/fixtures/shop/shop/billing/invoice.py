from shop.orders.models import Order


class Invoice:
    def __init__(self, number: str, amount: int):
        self.number = number
        self.amount = amount


def issue_invoice(order: Order) -> Invoice:
    return Invoice(number=f"INV-{order.order_id}", amount=order.total())


def describe(order: Order) -> str:
    return f"{order.order_id}: {order.total()}"
