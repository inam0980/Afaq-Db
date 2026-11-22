from django import forms
from django.forms import inlineformset_factory

from customers.models import Customer
from hr.forms import DateInput
from invoicing.models import Invoice, InvoiceLine
from jobs.models import Job


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["customer", "job", "issue_date", "due_date", "notes"]
        widgets = {
            "issue_date": DateInput(),
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        customers = Customer.objects.active()
        jobs = Job.objects.exclude(status=Job.Status.CANCELLED)
        if self.instance.pk:
            customers = customers | Customer.objects.filter(pk=self.instance.customer_id)
        self.fields["customer"].queryset = customers.distinct()
        self.fields["job"].queryset = jobs.select_related("customer").order_by("-created_at")

    def clean(self):
        cleaned = super().clean()
        job, customer = cleaned.get("job"), cleaned.get("customer")
        if job and customer and job.customer_id != customer.pk:
            self.add_error("job", "This job belongs to a different customer.")
        return cleaned


class LineForm(forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ["description", "quantity", "unit_price", "vat_rate"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "class": "num"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "class": "num"}),
        }


LineFormSet = inlineformset_factory(
    Invoice, InvoiceLine, form=LineForm, extra=1, can_delete=True, min_num=1, validate_min=True
)
