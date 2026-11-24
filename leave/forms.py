from django import forms

from hr.forms import DateInput
from hr.models import Employee
from leave.models import LeaveRequest, LeaveType


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["employee", "leave_type", "start_date", "end_date", "reason", "attachment"]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "attachment": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.active().order_by("first_name")
        self.fields["employee"].label_from_instance = lambda e: f"{e.full_name} ({e.employee_no})"
        self.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True)
