from django import forms
from django.utils.translation import gettext_lazy as _

from hr.models import Employee
from loans.models import Loan


class LoanForm(forms.Form):
    employee = forms.ModelChoiceField(label=_("Employee"), queryset=Employee.objects.none())
    kind = forms.ChoiceField(label=_("Type"), choices=Loan.Kind.choices, initial=Loan.Kind.LOAN)
    amount = forms.DecimalField(label=_("Amount"), max_digits=12, decimal_places=2, min_value=0.01)
    installment = forms.DecimalField(
        label=_("Monthly installment"), max_digits=12, decimal_places=2, min_value=0.01, required=False,
        help_text=_("Leave empty for an advance repaid in one payroll."),
    )
    first_month = forms.DateField(
        label=_("First deduction month"), widget=forms.DateInput(attrs={"type": "date"}),
        help_text=_("Any day in the month; deductions start with that month's payroll."),
    )
    reason = forms.CharField(label=_("Reason"), max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.active().order_by("first_name", "last_name")
