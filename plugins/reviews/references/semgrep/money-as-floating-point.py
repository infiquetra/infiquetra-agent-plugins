"""Fresh rule-test target for saga.money-as-floating-point. Never executed."""

from decimal import Decimal


def book_floats():
    # ruleid: saga.money-as-floating-point
    amount = 19.99
    # ruleid: saga.money-as-floating-point
    price = float(raw_price)
    # ruleid: saga.money-as-floating-point
    total = 0.0
    # ruleid: saga.money-as-floating-point
    balance = 100.50
    # ruleid: saga.money-as-floating-point
    payment = 9.99
    # ruleid: saga.money-as-floating-point
    money = 1e3
    # ruleid: saga.money-as-floating-point
    salary = 75000.50
    # ruleid: saga.money-as-floating-point
    fee = 2.50
    # ruleid: saga.money-as-floating-point
    tax = 8.25
    # ruleid: saga.money-as-floating-point
    tip = .50
    # ruleid: saga.money-as-floating-point
    discount = 5.00
    # ruleid: saga.money-as-floating-point
    refund = 12.75
    # ruleid: saga.money-as-floating-point
    subtotal = 44.99
    # ruleid: saga.money-as-floating-point
    cost = 3.25


def book_float_shapes():
    # ruleid: saga.money-as-floating-point
    ledger = {"amount": 19.99}
    # ruleid: saga.money-as-floating-point
    total += 0.5
    # ruleid: saga.money-as-floating-point
    amount: float = compute_amount()
    if check():
        # ok: saga.money-as-floating-point
        total_cents = 1999
        # ok: saga.money-as-floating-point
        amount = Decimal("19.99")
        # ok: saga.money-as-floating-point
        price = get_price()
        # ok: saga.money-as-floating-point
        discount_rate = 0.15
        # ok: saga.money-as-floating-point
        count = 3.5
        # ok: saga.money-as-floating-point
        total = compute_total()
