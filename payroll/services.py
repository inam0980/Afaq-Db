"""Payroll run workflow: generate -> edit inputs -> approve (lock) -> paid."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from hr.models import Employee
from leave.payroll import leave_deduction_days
from loans.payroll import deduction_limit, deduction_plan, record_repayments
from payroll.calculations import compute_payslip
from payroll.models import ZERO, GosiRate, PayrollLocked, PayrollRun, Payslip, SalaryStructure

FULL_MONTH_DAYS = 30
INPUT_FIELDS = ("overtime_hours", "absence_days", "additions", "deductions", "note")


@dataclass
class GenerationResult:
    created: int = 0
    skipped: list = field(default_factory=list)   # employees without a salary structure


def _ensure_draft(run: PayrollRun):
    if PayrollRun.objects.filter(pk=run.pk).exclude(status=PayrollRun.Status.DRAFT).exists():
        raise PayrollLocked(_("Payroll %(run)s is locked.") % {"run": run})


def eligible_employees(run: PayrollRun):
    return (
        Employee.objects.filter(hire_date__lte=run.period_end)
        .filter(Q(termination_date__isnull=True) | Q(termination_date__gte=run.period_start))
        .order_by("employee_no")
    )


def paid_days(employee: Employee, run: PayrollRun) -> int:
    """Calendar days employed in the month, max 30; a full month counts as 30."""
    start = max(employee.hire_date, run.period_start)
    end = min(employee.termination_date or run.period_end, run.period_end)
    if start == run.period_start and end == run.period_end:
        return FULL_MONTH_DAYS
    return min(max((end - start).days + 1, 0), FULL_MONTH_DAYS)


def missing_structures(run: PayrollRun) -> list:
    has_slip = run.payslips.values("employee_id")
    return [
        emp
        for emp in eligible_employees(run).exclude(pk__in=has_slip)
        if SalaryStructure.objects.current_for(emp, run.period_end) is None
    ]


def recalculate(slip: Payslip) -> Payslip:
    """Fill the payslip's snapshot fields from its inputs. Raises ValidationError."""
    run, emp = slip.run, slip.employee
    structure = SalaryStructure.objects.current_for(emp, run.period_end)
    if structure is None:
        raise ValidationError(_("%(emp)s has no salary structure.") % {"emp": emp})
    rate = GosiRate.for_employee(emp, run.period_end)

    slip.days_not_employed = FULL_MONTH_DAYS - paid_days(emp, run)
    unpaid = Decimal(slip.days_not_employed) + slip.absence_days
    if unpaid > FULL_MONTH_DAYS:
        raise ValidationError(
            {"absence_days": _("Absence plus days not employed (%(d)s) cannot exceed 30.")
             % {"d": slip.days_not_employed}}
        )
    slip.leave_days = leave_deduction_days(emp, run.period_start, run.period_end)
    unpaid = min(unpaid + slip.leave_days, FULL_MONTH_DAYS)
    inputs = {"overtime_hours": slip.overtime_hours, "absence_days": unpaid, "additions": slip.additions}
    try:
        result = compute_payslip(structure, rate, deductions=slip.deductions, **inputs)
    except ValueError as exc:
        raise ValidationError({"deductions": str(exc)}) from exc
    # Loans come last: they only take what the payslip can still pay (loans.payroll).
    room = min(deduction_limit(result.gross_fixed), result.net)
    slip.loan_deduction = sum((amount for _loan, amount in deduction_plan(slip, room)), ZERO)
    if slip.loan_deduction:
        result = compute_payslip(structure, rate, deductions=slip.deductions + slip.loan_deduction, **inputs)

    for name in (
        "basic", "housing", "transport", "other", "gross_fixed", "overtime", "absence",
        "gosi_employee", "gosi_employer", "gross", "total_deductions", "net",
    ):
        setattr(slip, name, getattr(result, name))
    slip.bank_name, slip.iban = emp.bank_name, emp.iban
    return slip


@transaction.atomic
def generate_payslips(run: PayrollRun) -> GenerationResult:
    """Create payslips for eligible employees that don't have one yet."""
    _ensure_draft(run)
    result = GenerationResult()
    existing = set(run.payslips.values_list("employee_id", flat=True))
    for emp in eligible_employees(run).exclude(pk__in=existing):
        if SalaryStructure.objects.current_for(emp, run.period_end) is None:
            result.skipped.append(emp)
            continue
        recalculate(Payslip(run=run, employee=emp)).save()
        result.created += 1
    return result


@transaction.atomic
def regenerate(run: PayrollRun) -> GenerationResult:
    """Add newly eligible employees and recalculate every payslip."""
    result = generate_payslips(run)
    for slip in run.payslips.select_related("employee", "run"):
        recalculate(slip).save()
    return result


@transaction.atomic
def update_payslip_inputs(slip: Payslip, **inputs) -> Payslip:
    _ensure_draft(slip.run)
    unknown = set(inputs) - set(INPUT_FIELDS)
    if unknown:
        raise TypeError(f"Unknown payslip inputs: {sorted(unknown)}")
    for name, value in inputs.items():
        setattr(slip, name, value)
    slip.full_clean(exclude=["run", "employee"])
    recalculate(slip).save()
    return slip


@transaction.atomic
def approve_run(run: PayrollRun, user) -> PayrollRun:
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.is_locked:
        raise PayrollLocked(_("Payroll %(run)s is already %(status)s.") % {
            "run": run, "status": run.get_status_display()})
    if not run.payslips.exists():
        raise ValidationError(_("Cannot approve a payroll with no payslips."))
    for slip in run.payslips.select_related("employee", "run"):
        recalculate(slip).save()
        record_repayments(slip)
    run.status = PayrollRun.Status.APPROVED
    run.approved_by = user
    run.approved_at = timezone.now()
    run.save()
    return run


@transaction.atomic
def mark_paid(run: PayrollRun, user) -> PayrollRun:
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.status != PayrollRun.Status.APPROVED:
        raise ValidationError(_("Only an approved payroll can be marked as paid."))
    run.status = PayrollRun.Status.PAID
    run.paid_at = timezone.now()
    run.save()
    return run
