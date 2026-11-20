from django import forms

from hr.models import Employee


class DateInput(forms.DateInput):
    """HTML5 date picker; needs ISO (YYYY-MM-DD) values to pre-fill."""

    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "first_name",
            "last_name",
            "name_ar",
            "nationality",
            "id_number",
            "id_expiry",
            "passport_no",
            "passport_expiry",
            "date_of_birth",
            "gender",
            "department",
            "job_title",
            "hire_date",
            "termination_date",
            "status",
            "mobile",
            "email",
            "bank_name",
            "iban",
        ]
        widgets = {
            "id_expiry": DateInput(),
            "passport_expiry": DateInput(),
            "date_of_birth": DateInput(),
            "hire_date": DateInput(),
            "termination_date": DateInput(),
            "name_ar": forms.TextInput(attrs={"dir": "rtl"}),
        }
