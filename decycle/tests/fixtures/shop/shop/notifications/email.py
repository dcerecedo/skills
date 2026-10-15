from shop.billing.invoice import Invoice

SENT: list[str] = []


def send_receipt(invoice: Invoice) -> None:
    SENT.append(f"receipt {invoice.number} {invoice.amount}")
