"""Integration tests: loan pages, approval, payslip line, sidebar."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse

from hr.tests.factories import EmployeeFactory
from loans.models import Loan
from loans.tests.factories import make_loan

pytestmark = pytest.mark.django_db

LIST_URL = reverse("loans:list")
CREATE_URL = reverse("loans:create")
HR_PERMS = ("view_loan", "add_loan", "view_employee")


@pytest.fixture
def hr_clerk(client_with_perms):
    return client_with_perms(*HR_PERMS)


@pytest.fixture
def approver(django_user_model):
    from django.contrib.auth.models import Permission
    from django.test import Client

    user = django_user_model.objects.create_user("boss", password="Test-pass-123")
    user.user_permissions.add(*Permission.objects.filter(codename__in=[*HR_PERMS, "approve_loan"]))
    c = Client()
    c.force_login(user)
    return c


def url(name, loan):
    return reverse(f"loans:{name}", args=[loan.pk])


def test_list_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_list_shows_loans_with_balance_and_filters(hr_clerk):
    a = make_loan(amount="3000", reason="Rent")
    b = make_loan(status=Loan.Status.PENDING, amount="999")
    html = hr_clerk.get(LIST_URL).content.decode()
    assert a.employee.full_name in html and b.employee.full_name in html
    assert "3000.00" in html
    pending = hr_clerk.get(LIST_URL, {"status": "pending"}).context["loans"]
    assert list(pending) == [b]
    assert list(hr_clerk.get(LIST_URL, {"employee": a.employee.pk}).context["loans"]) == [a]
    assert len(hr_clerk.get(LIST_URL, {"status": "bogus", "employee": "x"}).context["loans"]) == 2


def test_create_loan(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    response = hr_clerk.post(CREATE_URL, {
        "employee": emp.pk, "kind": "loan", "amount": "3000", "installment": "500",
        "first_month": "2026-12-01", "reason": "Car repair",
    })
    loan = Loan.objects.get()
    assert response.status_code == 302 and response["Location"] == loan.get_absolute_url()
    assert (loan.status, loan.amount, loan.first_month) == (Loan.Status.PENDING, D("3000"), dt.date(2026, 12, 1))


def test_create_shows_validation_errors(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    response = hr_clerk.post(CREATE_URL, {
        "employee": emp.pk, "kind": "loan", "amount": "300", "installment": "500", "first_month": "2026-12-01",
    })
    assert response.status_code == 200 and not Loan.objects.exists()
    assert response.context["form"].errors


def test_create_preselects_employee(hr_clerk):
    emp = EmployeeFactory()
    response = hr_clerk.get(CREATE_URL, {"employee": emp.pk})
    assert response.context["form"].initial["employee"] == str(emp.pk)


def test_create_requires_add_permission(client_with_perms):
    c = client_with_perms("view_loan")
    assert c.get(CREATE_URL).status_code == 403


def test_detail_shows_schedule_and_no_buttons_for_clerk(hr_clerk):
    loan = make_loan(status=Loan.Status.PENDING, amount="3000", installment="700",
                     first_month=dt.date(2026, 11, 1))
    html = hr_clerk.get(url("detail", loan)).content.decode()
    assert "Nov 2026" in html and "Mar 2027" in html            # first and last deduction month
    assert url("approve", loan) not in html


def test_approver_sees_buttons_and_approves(approver):
    loan = make_loan(status=Loan.Status.PENDING)
    assert url("approve", loan) in approver.get(url("detail", loan)).content.decode()
    response = approver.post(url("approve", loan), {"note": "fine"})
    assert response.status_code == 302
    loan.refresh_from_db()
    assert loan.status == Loan.Status.APPROVED


def test_approver_rejects_with_reason(approver):
    loan = make_loan(status=Loan.Status.PENDING)
    approver.post(url("reject", loan), {"note": "too much"})
    loan.refresh_from_db()
    assert (loan.status, loan.decision_note) == (Loan.Status.REJECTED, "too much")


def test_decision_errors_are_shown(approver):
    loan = make_loan(status=Loan.Status.PENDING)
    response = approver.post(url("reject", loan), {"note": ""}, follow=True)
    assert any(m.level_tag == "error" for m in response.context["messages"])
    loan.refresh_from_db()
    assert loan.status == Loan.Status.PENDING


def test_approve_needs_post(approver):
    loan = make_loan(status=Loan.Status.PENDING)
    assert approver.get(url("approve", loan)).status_code == 405


def test_clerk_cannot_approve(hr_clerk):
    loan = make_loan(status=Loan.Status.PENDING)
    assert hr_clerk.post(url("approve", loan)).status_code == 403
    assert hr_clerk.post(url("reject", loan), {"note": "x"}).status_code == 403


def test_detail_lists_repayments(hr_clerk):
    from loans.models import LoanRepayment
    from payroll.models import Payslip
    from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

    loan = make_loan(amount="3000")
    SalaryStructureFactory(employee=loan.employee)
    slip = Payslip.objects.create(run=PayrollRunFactory(year=2026, month=1), employee=loan.employee)
    LoanRepayment.objects.create(loan=loan, payslip=slip, amount=D("500"))
    html = hr_clerk.get(url("detail", loan)).content.decode()
    assert "2026-01" in html and "2500.00" in html                # repayment and outstanding


def test_payslip_shows_loan_line(client_with_perms):
    from payroll import services
    from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    SalaryStructureFactory(employee=emp)
    make_loan(emp, installment="500")
    run = PayrollRunFactory(year=2026, month=1)
    services.generate_payslips(run)
    slip = run.payslips.get()
    c = client_with_perms("view_payrollrun", "view_payslip")
    html = c.get(reverse("payroll:payslip_detail", args=[slip.pk])).content.decode()
    assert "Loan / advance repayment" in html and "500.00" in html


def test_sidebar_link(hr_clerk):
    assert LIST_URL in hr_clerk.get(reverse("home")).content.decode()


def test_sidebar_hides_link_without_permission(viewer_client):
    assert LIST_URL not in viewer_client.get(reverse("home")).content.decode()


def test_form_explains_the_deduction_cap(hr_clerk, settings):
    settings.LOAN_MAX_DEDUCTION_PERCENT = 15
    assert "at most 15% of the monthly wage" in hr_clerk.get(CREATE_URL).content.decode()


def test_admin_shows_loan_with_read_only_repayments(admin_client):
    loan = make_loan()
    response = admin_client.get(reverse("admin:loans_loan_change", args=[loan.pk]))
    assert response.status_code == 200
    from loans.admin import RepaymentInline
    from loans.models import Loan as LoanModel

    from django.contrib import admin as django_admin

    inline = RepaymentInline(LoanModel, django_admin.site)
    assert inline.has_add_permission(None) is False
