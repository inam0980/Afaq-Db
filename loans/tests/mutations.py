"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

M = "loans/models.py"
P = "loans/payroll.py"
S = "loans/services.py"
V = "loans/views.py"
PS = "payroll/services.py"
T = "loans/templates/loans/loan_detail.html"
B = "templates/base.html"

MUTATIONS = [
    # --- model ---
    ("First month not normalised", M, "            self.first_month = self.first_month.replace(day=1)", "            pass"),
    ("Installment above amount allowed", M,
     "        if self.amount and self.installment and self.installment > self.amount:", "        if False:"),
    ("Repaid ignores repayments", M, '        return self.repayments.aggregate(t=Sum("amount"))["t"] or ZERO', "        return ZERO"),
    ("Pending counted as settled", M,
     "        return self.status == self.Status.APPROVED and self.outstanding <= 0", "        return self.outstanding <= 0"),
    ("Months rounded down", M, "        return math.ceil(self.amount / self.installment)",
     "        return int(self.amount / self.installment)"),
    ("Last month off by one", M, "        index = self.first_month.month - 1 + self.months - 1",
     "        index = self.first_month.month - 1 + self.months"),
    ("Active includes pending", M, "        return self.filter(status=Loan.Status.APPROVED).annotate(",
     "        return self.annotate("),
    ("Active includes repaid", M, '        ).filter(amount__gt=models.F("_repaid"))', "        )"),
    # --- payroll deductions ---
    ("No cap", P, "    return money(gross_fixed * Decimal(settings.LOAN_MAX_DEDUCTION_PERCENT) / 100)",
     "    return money(gross_fixed)"),
    ("Pending loans deducted", P,
     "        employee=slip.employee, status=Loan.Status.APPROVED, first_month__lte=run.period_start",
     "        employee=slip.employee, first_month__lte=run.period_start"),
    ("Deducted before first month", P,
     "        employee=slip.employee, status=Loan.Status.APPROVED, first_month__lte=run.period_start",
     "        employee=slip.employee, status=Loan.Status.APPROVED"),
    ("Newest loan first", P, '    ).order_by("first_month", "pk")', '    ).order_by("-first_month", "-pk")'),
    ("Cap ignored across loans", P, "            room -= take", "            pass"),
    ("Balance ignored (over-collect)", P,
     "        take = min(loan.installment, loan.amount - repaid, room)", "        take = min(loan.installment, room)"),
    ("Draft run's own repayments double counted", P,
     '        repaid = (LoanRepayment.objects.filter(loan=loan).exclude(payslip__run=run)',
     '        repaid = (LoanRepayment.objects.filter(loan=loan)'),
    ("Repayments never recorded", P,
     "        LoanRepayment.objects.create(loan=loan, payslip=slip, amount=amount)", "        pass"),
    ("Payroll ignores loans", PS,
     "    if slip.loan_deduction:\n        result = compute_payslip(", "    if False:\n        result = compute_payslip("),
    ("Loan can make net negative", PS, "    room = min(deduction_limit(result.gross_fixed), result.net)",
     "    room = deduction_limit(result.gross_fixed)"),
    ("Approval does not record repayments", PS, "        recalculate(slip).save()\n        record_repayments(slip)\n",
     "        recalculate(slip).save()\n"),
    # --- workflow ---
    ("Terminated employee gets a loan", S, "    if employee.status == Employee.Status.TERMINATED:", "    if False:"),
    ("Loan without installment", S, "        if kind != Loan.Kind.ADVANCE:", "        if False:"),
    ("Loan not validated", S, "    loan.full_clean()\n    loan.save()", "    loan.save()"),
    ("Decided twice", S, "        if current.status != Loan.Status.PENDING:", "        if False:"),
    ("Approve own request", S, "    if loan.requested_by_id == user.pk:", "    if False:"),
    ("Reject without reason", S, "    if not note.strip():", "    if False:"),
    ("Approve sets wrong status", S, "    return _decide(loan, user, Loan.Status.APPROVED, note.strip())",
     "    return _decide(loan, user, Loan.Status.REJECTED, note.strip())"),
    ("Decider not recorded", S,
     "        current.status, current.decided_by, current.decided_at = status, user, timezone.now()",
     "        current.status, current.decided_at = status, timezone.now()"),
    # --- views ---
    ("Status filter ignored", V, "    if f[\"status\"] in Loan.Status.values:\n        qs = qs.filter(status=f[\"status\"])",
     "    if False:\n        qs = qs.filter(status=f[\"status\"])"),
    ("Employee filter ignored", V, '    if f["employee"].isdigit():\n        qs = qs.filter(employee_id=int(f["employee"]))',
     '    if False:\n        qs = qs.filter(employee_id=int(f["employee"]))'),
    ("Create errors swallowed", V, "            form.add_error(None, exc)", "            raise"),
    ("Decision errors crash", V, "    except ValidationError as exc:\n        messages.error", "    except KeyError as exc:\n        messages.error"),
    ("Clerk can approve", V,
     '@login_required\n@require_POST\n@permission_required("loans.approve_loan", raise_exception=True)\ndef loan_approve',
     "@login_required\n@require_POST\ndef loan_approve"),
    ("Approve by GET", V, '@login_required\n@require_POST\n@permission_required("loans.approve_loan", raise_exception=True)\ndef loan_approve',
     '@login_required\n@permission_required("loans.approve_loan", raise_exception=True)\ndef loan_approve'),
    ("Buttons for everyone", V,
     '        "can_decide": request.user.has_perm("loans.approve_loan") and loan.status == Loan.Status.PENDING,',
     '        "can_decide": True,'),
    ("Repayments hidden", T, "  {% if repayments %}\n  <table", "  {% if False %}\n  <table"),
    ("Sidebar link for everyone", B, "      {% if perms.loans.view_loan %}\n", "      {% if True %}\n"),
]
