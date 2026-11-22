from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from customers.models import Customer
from hr.forms import DateInput
from hr.models import Employee
from jobs.models import Job


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            "customer", "service_type", "title", "description", "site_address",
            "priority", "scheduled_date", "technicians", "quoted_amount",
        ]
        widgets = {
            "scheduled_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "technicians": forms.CheckboxSelectMultiple,
            "quoted_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    SECTIONS = [
        (_("Job"), "briefcase", ["customer", "service_type", "title", "description", "priority", "quoted_amount"]),
        (_("Where & when"), "calendar", ["site_address", "scheduled_date"]),
        (_("Technicians"), "users", ["technicians"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        customers = Customer.objects.active()
        technicians = Employee.objects.active()
        if self.instance.pk:   # keep current (possibly inactive) selections valid on edit
            customers = customers | Customer.objects.filter(pk=self.instance.customer_id)
            technicians = technicians | self.instance.technicians.all()
        self.fields["customer"].queryset = customers.distinct()
        self.fields["technicians"].queryset = technicians.distinct().order_by("first_name")

    def sections(self):
        return [(t, i, [self[n] for n in names]) for t, i, names in self.SECTIONS]


class MaterialForm(forms.Form):
    description = forms.CharField(max_length=150, label=_("Material"))
    quantity = forms.DecimalField(min_value=Decimal("0.01"), max_digits=10, decimal_places=2, label=_("Qty"))
    unit_cost = forms.DecimalField(min_value=Decimal("0"), max_digits=12, decimal_places=2, label=_("Unit cost"))


class LabourForm(forms.Form):
    employee = forms.ModelChoiceField(queryset=Employee.objects.none(), label=_("Technician"))
    date = forms.DateField(widget=DateInput(), label=_("Date"))
    hours = forms.DecimalField(min_value=Decimal("0.01"), max_value=Decimal("24"), max_digits=5,
                               decimal_places=2, label=_("Hours"))
    note = forms.CharField(max_length=200, required=False, label=_("Note"))

    def __init__(self, *args, job, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = job.technicians.order_by("first_name")
        self.fields["employee"].label_from_instance = lambda e: e.full_name
