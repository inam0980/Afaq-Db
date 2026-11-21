"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

M = "jobs/models.py"
S = "jobs/services.py"
V = "jobs/views.py"
F = "jobs/forms.py"
DASH = "core/views.py"
BASE = "templates/base.html"

MUTATIONS = [
    # --- model ---
    ("Job number without zero padding", M, 'return f"JOB-{value:05d}"', 'return f"JOB-{value}"'),
    ("Location ignores site address", M,
     "return self.site_address or self.customer.address_line", "return self.customer.address_line"),
    ("Negative quote allowed", M,
     'validators=[MinValueValidator(Decimal("0"))],\n    )\n    cancel_reason',
     "validators=[],\n    )\n    cancel_reason"),
    ("Completed job still editable", M,
     "return self.status not in self.FINAL_STATUSES", "return self.status != self.Status.CANCELLED"),
    ("Open jobs include completed", M,
     "OPEN_STATUSES = (Status.NEW, Status.SCHEDULED, Status.IN_PROGRESS)",
     "OPEN_STATUSES = (Status.NEW, Status.SCHEDULED, Status.IN_PROGRESS, Status.COMPLETED)"),
    ("New job can jump to completed", M,
     "Status.NEW: (Status.SCHEDULED, Status.IN_PROGRESS, Status.CANCELLED),",
     "Status.NEW: (Status.SCHEDULED, Status.IN_PROGRESS, Status.COMPLETED, Status.CANCELLED),"),
    ("Completed job can be cancelled", M,
     "        Status.COMPLETED: (),", "        Status.COMPLETED: (Status.CANCELLED,),"),
    ("Search ignores customer name", M, "                | Q(customer__name__icontains=term)\n", ""),
    # --- services ---
    ("Unknown status accepted", S,
     "    if new_status not in S.values:\n        raise", "    if False:\n        raise"),
    ("Transitions not enforced", S,
     "    if new_status not in job.next_statuses:", "    if False:"),
    ("Schedule without a date", S,
     "    if new_status == S.SCHEDULED and not job.scheduled_date:", "    if False:"),
    ("Start without technician", S,
     "        if not job.technicians.exclude(status=Employee.Status.TERMINATED).exists():",
     "        if False:"),
    ("Terminated technician counts", S,
     "job.technicians.exclude(status=Employee.Status.TERMINATED).exists()", "job.technicians.exists()"),
    ("started_at not recorded", S, "        job.started_at = timezone.now()\n", ""),
    ("completed_at not recorded", S, "        job.completed_at = timezone.now()\n", ""),
    ("Cancel without reason", S, "        if not reason:", "        if False:"),
    # --- views & forms ---
    ("List shows closed jobs by default", V, "    else:\n        qs = qs.open()", "    else:\n        pass"),
    ("Technician filter ignored", V,
     "        qs = qs.filter(technicians__pk=int(f[\"technician\"]))", "        pass"),
    ("Creator not recorded", V, "        job.created_by = request.user\n", "        job.created_by_id = 1\n"),
    ("Technicians not saved on create", V, "        form.save_m2m()\n", ""),
    ("Completed job editable", V,
     "    if not job.is_editable:\n        return render", "    if False:\n        return render"),
    ("Status change needs only view permission", V,
     '@permission_required("jobs.change_job", raise_exception=True)\ndef job_status',
     '@permission_required("jobs.view_job", raise_exception=True)\ndef job_status'),
    ("Status change via GET", V,
     "@require_POST\n@login_required\n@permission_required(\"jobs.change_job\", raise_exception=True)\ndef job_status",
     "@login_required\n@permission_required(\"jobs.change_job\", raise_exception=True)\ndef job_status"),
    ("Status errors not shown", V,
     "        messages.error(request, \" \".join(exc.messages))", "        pass"),
    ("Terminated staff offered as technicians", F,
     "        technicians = Employee.objects.active()\n", "        technicians = Employee.objects.all()\n"),
    # --- dashboard & sidebar ---
    ("Dashboard jobs card without permission", DASH,
     'context["show_jobs"] = user.has_perm("jobs.view_job")', 'context["show_jobs"] = True'),
    ("Urgent count includes normal jobs", DASH,
     "urgent_jobs=open_jobs.filter(priority=Job.Priority.URGENT).count(),", "urgent_jobs=open_jobs.count(),"),
    ("Completed-this-month counts all months", DASH,
     "                completed_at__month=today.month,\n", ""),
    ("Sidebar Jobs link without permission", BASE,
     "      {% if perms.jobs.view_job %}\n", "      {% if True %}\n"),
    ("Sidebar Customers link without permission", BASE,
     "      {% if perms.customers.view_customer %}\n", "      {% if True %}\n"),
]
