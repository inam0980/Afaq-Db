"""Job costing: cost entries (materials, labour) and profit summaries.

Cost of a job = materials + labour + APPROVED linked expenses (excl. VAT,
because input VAT is recovered). Revenue = the issued invoices of the job
(excl. VAT); until the job is invoiced, its quoted amount.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.money import money
from expenses.models import Expense
from hr.models import Employee
from jobs.models import Job, JobMaterial, LabourEntry
from payroll.calculations import hourly_rate
from payroll.models import SalaryStructure

ZERO = Decimal("0")


def _ensure_costs_editable(job: Job):
    status = Job.objects.filter(pk=job.pk).values_list("status", flat=True).first()
    if status == Job.Status.CANCELLED:
        raise ValidationError(_("Costs of a cancelled job cannot be changed."))


@transaction.atomic
def add_material(job: Job, user, *, description: str, quantity: Decimal, unit_cost: Decimal) -> JobMaterial:
    _ensure_costs_editable(job)
    material = JobMaterial(
        job=job, description=description, quantity=quantity, unit_cost=unit_cost, added_by=user
    )
    material.full_clean(exclude=["added_by"])
    material.save()
    return material


@transaction.atomic
def add_labour(
    job: Job, user, *, employee: Employee, date: dt.date, hours: Decimal, note: str = ""
) -> LabourEntry:
    _ensure_costs_editable(job)
    if not job.technicians.filter(pk=employee.pk).exists():
        raise ValidationError({"employee": _("Only technicians assigned to this job can log hours on it.")})
    if date > timezone.localdate():
        raise ValidationError({"date": _("Hours cannot be logged for a future date.")})
    created_at = Job.objects.values_list("created_at", flat=True).get(pk=job.pk)
    if date < timezone.localtime(created_at).date():
        raise ValidationError({"date": _("The job did not exist yet on that date.")})

    structure = SalaryStructure.objects.current_for(employee, date)
    if structure is None:
        raise ValidationError(
            {"employee": _("%(name)s has no salary on that date, so the cost is unknown.") % {
                "name": employee.full_name}}
        )

    entry = LabourEntry(
        job=job, employee=employee, date=date, hours=hours, note=note, added_by=user,
        hourly_cost=money(hourly_rate(structure.gross_fixed)),
    )
    entry.full_clean(exclude=["added_by", "hourly_cost", "cost"])
    entry.cost = money(entry.hourly_cost * hours)
    entry.save()
    return entry


@transaction.atomic
def delete_cost_entry(entry) -> None:
    _ensure_costs_editable(entry.job)
    entry.delete()


@dataclass(frozen=True)
class JobCosting:
    materials: Decimal
    labour: Decimal
    labour_hours: Decimal
    expenses: Decimal
    total_cost: Decimal
    revenue: Decimal | None
    profit: Decimal | None
    margin_pct: Decimal | None


def _sum(qs, field) -> Decimal:
    return qs.aggregate(s=Sum(field))["s"] or ZERO


def _invoiced_revenue(job: Job) -> Decimal | None:
    """Revenue excl. VAT from the job's issued invoices; None if not invoiced yet."""
    issued = job.invoices.filter(status="issued")
    if not issued.exists():
        return None
    return money(_sum(issued, "subtotal"))


def job_costing(job: Job) -> JobCosting:
    materials = money(_sum(job.materials.all(), "total"))
    labour = money(_sum(job.labour.all(), "cost"))
    hours = money(_sum(job.labour.all(), "hours"))
    expenses = money(_sum(job.expenses.filter(status=Expense.Status.APPROVED), "amount_excl_vat"))
    total = materials + labour + expenses

    revenue = _invoiced_revenue(job)
    if revenue is None and job.quoted_amount is not None:
        revenue = money(job.quoted_amount)
    profit = None if revenue is None else revenue - total
    margin = money(profit / revenue * 100) if revenue else None
    return JobCosting(materials, labour, hours, expenses, total, revenue, profit, margin)


@dataclass(frozen=True)
class ProfitRow:
    job: Job
    costing: JobCosting


@dataclass(frozen=True)
class ProfitReport:
    rows: list
    revenue: Decimal
    total_cost: Decimal
    profit: Decimal


def profitability(year: int, month: int) -> ProfitReport:
    """Completed jobs of a month with their costing and totals."""
    jobs = (
        Job.objects.filter(
            status=Job.Status.COMPLETED, completed_at__year=year, completed_at__month=month
        )
        .select_related("customer")
        .order_by("completed_at")
    )
    rows = [ProfitRow(job, job_costing(job)) for job in jobs]
    revenue = money(sum((r.costing.revenue or ZERO for r in rows), ZERO))
    cost = money(sum((r.costing.total_cost for r in rows), ZERO))
    return ProfitReport(rows, revenue, cost, revenue - cost)
