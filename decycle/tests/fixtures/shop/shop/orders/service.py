from shop.billing.invoice import issue_invoice
from shop.notifications.email import send_receipt
from shop.orders.models import Order


def place_order(order: Order) -> str:
    invoice = issue_invoice(order)
    send_receipt(invoice)
    return invoice.number
