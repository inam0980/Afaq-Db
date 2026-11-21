from django import forms
from django.utils.translation import gettext_lazy as _

from customers.models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "name", "name_ar", "kind", "mobile", "email", "vat_number",
            "building_number", "street", "district", "city", "postal_code", "is_active",
        ]
        widgets = {
            "name_ar": forms.TextInput(attrs={"dir": "rtl"}),
            "vat_number": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 15}),
            "postal_code": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 5}),
            "building_number": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 4}),
        }

    SECTIONS = [
        (_("Customer"), "users", ["name", "name_ar", "kind", "mobile", "email", "vat_number", "is_active"]),
        (_("National address"), "building", ["building_number", "street", "district", "city", "postal_code"]),
    ]

    def sections(self):
        return [(t, i, [self[n] for n in names]) for t, i, names in self.SECTIONS]
