"""Integration tests: payments & credit notes on the invoice page, statement,
receivables (aging), customer balance, dashboard, sidebar."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from invoicing.models import Invoice, Payment
from invoicing.services import record_payment
from invoicing.tests.factories import invoice_with_lines, issued_invoice

pytestmark = pytest.mark.django_db

RECEIVABLES_URL = reverse("invoicing:receivables")
ACCOUNTANT = ("view_invoice", "add_invoice", "change_invoice", "add_payment", "view_payment",
              "view_customer", "view_job")


@pytest.fixture
def accountant(client_with_perms):
    return client_with_perms(*ACCOUNTANT)


def url(name, obj):
    return reverse(f"invoicing:{name}", args=[obj.pk])


def today():
    return timezone.localdate()


# --- payments ------------------------------------------------------------------

def test_record_payment_via_post(accountant):
    inv = issued_invoice()
    data = {"amount": "500", "date": today().isoformat(), "method": "bank", "reference": "TRX9", "note": ""}
    response = accountant.post(url("add_payment", inv), data)
    assert response.status_code == 302
    assert Payment.objects.get().amount == D("500.00")


def test_overpayment_shows_error(accountant):
    inv = issued_invoice()
    data = {"amount": "2000", "date": today().isoformat(), "method": "cash", "reference": "", "note": ""}
    response = accountant.post(url("add_payment", inv), data, follow=True)
    assert not Payment.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_invalid_payment_form_shows_error(accountant):
    inv = issued_invoice()
    response = accountant.post(url("add_payment", inv), {"amount": "abc", "date": "", "method": "cash"}, follow=True)
    assert not Payment.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_payment_needs_permission(client_with_perms):
    client = client_with_perms("view_invoice")
    inv = issued_invoice()
    data = {"amount": "1", "date": today().isoformat(), "method": "cash", "reference": "", "note": ""}
    assert client.post(url("add_payment", inv), data).status_code == 403


def test_invoice_page_shows_payments_and_balance(accountant):
    inv = issued_invoice()
    record_payment(inv, None, amount=D("500"), date=today(), method="bank", reference="TRX-77")
    response = accountant.get(url("detail", inv))
    html = response.content.decode()
    assert response.context["invoice"].balance == D("650.00")
    assert "TRX-77" in html and "650.00" in html


def test_payment_form_hidden_when_fully_paid(accountant):
    inv = issued_invoice()
    record_payment(inv, None, amount=D("1150"), date=today(), method="bank", reference="")
    assert url("add_payment", inv) not in accountant.get(url("detail", inv)).content.decode()


def test_delete_payment_requires_permission(accountant, client_with_perms):
    inv = issued_invoice()
    p = record_payment(inv, None, amount=D("100"), date=today(), method="cash", reference="")
    assert accountant.post(reverse("invoicing:delete_payment", args=[p.pk])).status_code == 403


def test_delete_payment(client_with_perms):
    client = client_with_perms("view_invoice", "delete_payment")
    inv = issued_invoice()
    p = record_payment(inv, None, amount=D("100"), date=today(), method="cash", reference="")
    response = client.post(reverse("invoicing:delete_payment", args=[p.pk]))
    assert response.status_code == 302 and not Payment.objects.exists()


# --- credit notes --------------------------------------------------------------

def test_create_credit_note_via_post(accountant):
    inv = issued_invoice()
    response = accountant.post(url("credit_note", inv), {"reason": "Wrong quantity"})
    cn = Invoice.objects.get(kind=Invoice.Kind.CREDIT_NOTE)
    assert response.status_code == 302
    assert response.url == url("update", cn)


def test_credit_note_without_reason_shows_error(accountant):
    inv = issued_invoice()
    response = accountant.post(url("credit_note", inv), {"reason": ""}, follow=True)
    assert not Invoice.objects.filter(kind=Invoice.Kind.CREDIT_NOTE).exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_credit_note_edit_page_locks_customer(accountant):
    inv = issued_invoice()
    accountant.post(url("credit_note", inv), {"reason": "x"})
    cn = Invoice.objects.get(kind=Invoice.Kind.CREDIT_NOTE)
    form = accountant.get(url("update", cn)).context["form"]
    assert "customer" not in form.fields and "job" not in form.fields


def test_credit_note_edit_saves_lines(accountant):
    inv = issued_invoice()
    accountant.post(url("credit_note", inv), {"reason": "x"})
    cn = Invoice.objects.get(kind=Invoice.Kind.CREDIT_NOTE)
    line = cn.lines.get()
    new_date = (today() - dt.timedelta(days=1)).isoformat()      # differs from the draft's default
    data = {
        "issue_date": new_date, "reason": "Discount", "notes": "",
        "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "1", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
        "lines-0-id": str(line.pk), "lines-0-invoice": str(cn.pk), "lines-0-description": "Discount",
        "lines-0-quantity": "1", "lines-0-unit_price": "100", "lines-0-vat_rate": "15",
        "lines-1-description": "", "lines-1-quantity": "1", "lines-1-unit_price": "", "lines-1-vat_rate": "15",
    }
    response = accountant.post(url("update", cn), data)
    cn.refresh_from_db()
    assert response.status_code == 302
    assert (cn.total, cn.reason) == (D("115.00"), "Discount")
    assert cn.issue_date.isoformat() == new_date and cn.due_date == cn.issue_date


def test_issued_credit_note_print_shows_title_and_reference(client_with_perms, admin_user):
    from invoicing.services import create_credit_note, issue

    client = client_with_perms(*ACCOUNTANT)
    inv = issued_invoice()
    cn = create_credit_note(inv, admin_user, reason="Overcharged")
    issue(cn, admin_user)
    html = client.get(url("detail", cn)).content.decode()
    assert "إشعار دائن" in html and "Credit Note" in html
    assert inv.number in html and "Overcharged" in html
    assert 'class="zatca-qr"' in html


# --- statement -----------------------------------------------------------------

def test_statement_page(accountant):
    customer = CustomerFactory(name="Riyadh Towers")
    inv = issued_invoice(customer=customer)
    record_payment(inv, None, amount=D("150"), date=today(), method="cash", reference="")
    response = accountant.get(reverse("invoicing:statement", args=[customer.pk]))
    html = response.content.decode()
    assert response.status_code == 200
    assert response.context["statement"].closing_balance == D("1000.00")
    assert "Riyadh Towers" in html and inv.number in html


def test_statement_custom_period_and_bad_dates(accountant):
    customer = CustomerFactory()
    url_ = reverse("invoicing:statement", args=[customer.pk])
    ctx = accountant.get(url_, {"start": "2026-01-01", "end": "2026-01-31"}).context
    assert (ctx["start"], ctx["end"]) == (dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    ctx = accountant.get(url_, {"start": "garbage", "end": "2026-13-01"}).context
    assert ctx["end"] == today() and ctx["start"] == today().replace(month=1, day=1)


def test_statement_end_before_start_is_swapped(accountant):
    customer = CustomerFactory()
    ctx = accountant.get(reverse("invoicing:statement", args=[customer.pk]),
                         {"start": "2026-03-01", "end": "2026-01-01"}).context
    assert (ctx["start"], ctx["end"]) == (dt.date(2026, 1, 1), dt.date(2026, 3, 1))


def test_statement_requires_permission(viewer_client):
    assert viewer_client.get(reverse("invoicing:statement", args=[CustomerFactory().pk])).status_code == 403


# --- receivables (aging) ---------------------------------------------------------

def test_receivables_page(accountant):
    customer = CustomerFactory(name="Late Payer")
    issued_invoice(customer=customer, issue_date=today() - dt.timedelta(days=70),
                   due_date=today() - dt.timedelta(days=40))
    response = accountant.get(RECEIVABLES_URL)
    assert response.context["report"].totals["overdue"] == D("1150.00")
    assert "Late Payer" in response.content.decode()


def test_receivables_requires_permission(viewer_client):
    assert viewer_client.get(RECEIVABLES_URL).status_code == 403


# --- invoice list, customer page, dashboard, sidebar ------------------------------

def test_invoice_list_payment_filters(accountant):
    unpaid = issued_invoice()
    paid = issued_invoice()
    record_payment(paid, None, amount=D("1150"), date=today(), method="cash", reference="")
    overdue = issued_invoice(issue_date=today() - dt.timedelta(days=40), due_date=today() - dt.timedelta(days=10))
    invoice_with_lines()   # draft

    def pks(payment):
        return {i.pk for i in accountant.get(reverse("invoicing:list"), {"payment": payment}).context["invoices"]}

    assert pks("unpaid") == {unpaid.pk, overdue.pk}
    assert pks("paid") == {paid.pk}
    assert pks("overdue") == {overdue.pk}


def test_customer_page_shows_balance_and_statement_link(client_with_perms):
    client = client_with_perms("view_customer", "view_invoice")
    customer = CustomerFactory()
    issued_invoice(customer=customer)
    html = client.get(reverse("customers:detail", args=[customer.pk])).content.decode()
    assert "1150.00" in html
    assert reverse("invoicing:statement", args=[customer.pk]) in html


def test_customer_page_hides_balance_without_invoice_permission(client_with_perms):
    client = client_with_perms("view_customer")
    customer = CustomerFactory()
    issued_invoice(customer=customer)
    assert "1150.00" not in client.get(reverse("customers:detail", args=[customer.pk])).content.decode()


def test_dashboard_receivables(accountant):
    issued_invoice()
    overdue = issued_invoice(issue_date=today() - dt.timedelta(days=40), due_date=today() - dt.timedelta(days=10))
    record_payment(overdue, None, amount=D("150"), date=today(), method="cash", reference="")

    ctx = accountant.get(reverse("home")).context

    assert ctx["receivable_total"] == D("2150.00")
    assert ctx["receivable_overdue"] == D("1000.00")
    assert ctx["collected_this_month"] == D("150.00")


def test_dashboard_hides_receivables_without_permission(viewer_client):
    assert "receivable_total" not in viewer_client.get(reverse("home")).context


def test_sidebar_receivables_link(accountant, ):
    assert RECEIVABLES_URL in accountant.get(reverse("home")).content.decode()


def test_dashboard_collected_ignores_earlier_months(accountant):
    t = today()
    if t.month == 1:  # pragma: no cover - only runs in January
        pytest.skip("needs an earlier month in the same year")
    earlier = t.replace(month=t.month - 1, day=1)
    inv = issued_invoice(issue_date=earlier, due_date=earlier + dt.timedelta(days=30))
    record_payment(inv, None, amount=D("400"), date=earlier, method="cash", reference="")
    assert accountant.get(reverse("home")).context["collected_this_month"] == D("0")
