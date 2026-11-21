"""Unit tests: shared money helper."""

from decimal import Decimal as D

from core.money import money


def test_money_rounds_half_up_to_two_places():
    assert money("10.005") == D("10.01")
    assert money("10.004") == D("10.00")
    assert money(3) == D("3.00")
    assert money(D("-1.005")) == D("-1.01")


def test_payroll_uses_the_shared_helper():
    from payroll import calculations

    assert calculations.money is money
