"""Integration tests: VAT return page, CSV download, dashboard and sidebar."""

from decimal import Decimal as D

import pytest
from django.urls import reverse

from invoicing.tests.factories import issued_invoice

pytestmark = pytest.mark.django_db

VAT_URL = reverse("invoicing:vat_return")


@pytest.fixture
def finance(client_with_perms):
    return client_with_perms("view_vat_return", "view_invoice", "view_expense")


def test_requires_permission(client_with_perms):
    client = client_with_perms("view_invoice", "view_expense")
    assert client.get(VAT_URL).status_code == 403


def test_page_shows_boxes_for_selected_period(finance):
    inv = issued_invoice()                                    # issued today, 1000 + 150
    from django.utils import timezone

    t = timezone.localdate()
    period = f"{t.year}-Q{(t.month - 1) // 3 + 1}"
    response = finance.get(VAT_URL, {"period": period})
    html = response.content.decode()

    assert response.status_code == 200
    assert response.context["report"].output_vat == D("150.00")
    assert response.context["period"] == period
    assert "150.00" in html and inv.number in html


def test_default_period_is_current_quarter(finance):
    from django.utils import timezone

    t = timezone.localdate()
    assert finance.get(VAT_URL).context["period"] == f"{t.year}-Q{(t.month - 1) // 3 + 1}"


def test_csv_download(finance):
    issued_invoice()
    response = finance.get(VAT_URL, {"format": "csv"})
    body = response.content.decode("utf-8-sig")
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"] and ".csv" in response["Content-Disposition"]
    assert body.splitlines()[0].startswith("Type,Date,Reference")
    assert "1000.00" in body


def test_sidebar_link_with_permission(finance):
    assert VAT_URL in finance.get(reverse("home")).content.decode()


def test_sidebar_hides_link_without_permission(viewer_client):
    assert VAT_URL not in viewer_client.get(reverse("home")).content.decode()


def test_dashboard_vat_this_quarter(finance):
    issued_invoice()
    ctx = finance.get(reverse("home")).context
    assert ctx["vat_due_this_quarter"] == D("150.00")


def test_dashboard_hides_vat_without_permission(viewer_client):
    assert "vat_due_this_quarter" not in viewer_client.get(reverse("home")).context
