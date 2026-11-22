from django import forms

from expenses.models import Expense, ExpenseCategory
from hr.forms import DateInput
from jobs.models import Job


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            "date",
            "category",
            "description",
            "vendor_name",
            "vendor_vat_number",
            "invoice_number",
            "total",
            "vat_rate",
            "payment_method",
            "job",
            "receipt",
        ]
        widgets = {
            "date": DateInput(),
            "total": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "vendor_vat_number": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 15}),
            "receipt": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = ExpenseCategory.objects.filter(is_active=True)
        if self.instance.pk:   # keep a now-inactive category selectable on edit
            active = active | ExpenseCategory.objects.filter(pk=self.instance.category_id)
        self.fields["category"].queryset = active.distinct()

        jobs = Job.objects.exclude(status=Job.Status.CANCELLED)
        if self.instance.pk and self.instance.job_id:
            jobs = jobs | Job.objects.filter(pk=self.instance.job_id)
        self.fields["job"].queryset = jobs.select_related("customer").distinct().order_by("-created_at")


class RejectForm(forms.Form):
    reason = forms.CharField(max_length=300)
