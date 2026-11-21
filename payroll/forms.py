from django import forms
from django.utils import timezone

from payroll.models import PayrollRun, Payslip


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = ["year", "month"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["year"].initial = today.year
        self.fields["month"].initial = today.month


class PayslipInputForm(forms.ModelForm):
    class Meta:
        model = Payslip
        fields = ["overtime_hours", "absence_days", "additions", "deductions", "note"]
        widgets = {
            "overtime_hours": forms.NumberInput(attrs={"step": "0.5", "min": "0", "class": "num"}),
            "absence_days": forms.NumberInput(attrs={"step": "0.5", "min": "0", "max": "30", "class": "num"}),
            "additions": forms.NumberInput(attrs={"step": "0.01", "min": "0", "class": "num"}),
            "deductions": forms.NumberInput(attrs={"step": "0.01", "min": "0", "class": "num"}),
        }
