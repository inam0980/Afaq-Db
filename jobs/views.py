import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from hr.models import Employee
from jobs import costing
from jobs.forms import JobForm, LabourForm, MaterialForm
from jobs.models import Job, JobMaterial, LabourEntry
from jobs.services import change_status

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@login_required
@permission_required("jobs.view_job", raise_exception=True)
def job_list(request):
    qs = Job.objects.select_related("customer").prefetch_related("technicians")
    f = {k: request.GET.get(k, "") for k in ("status", "service", "priority", "technician", "q")}

    if f["status"] == "all":
        pass
    elif f["status"] in Job.Status.values:
        qs = qs.filter(status=f["status"])
    else:
        qs = qs.open()
    if f["service"] in Job.ServiceType.values:
        qs = qs.filter(service_type=f["service"])
    if f["priority"] in Job.Priority.values:
        qs = qs.filter(priority=f["priority"])
    if f["technician"].isdigit():
        qs = qs.filter(technicians__pk=int(f["technician"]))
    qs = qs.search(f["q"].strip())

    return render(
        request,
        "jobs/job_list.html",
        {
            "jobs": qs.distinct(),
            "f": f,
            "statuses": Job.Status.choices,
            "services": Job.ServiceType.choices,
            "technicians": Employee.objects.active().order_by("first_name"),
        },
    )


@login_required
@permission_required("jobs.view_job", raise_exception=True)
def job_detail(request, pk):
    job = get_object_or_404(Job.objects.select_related("customer", "created_by"), pk=pk)
    can_see_costs = request.user.has_perm("jobs.view_job_costing")
    return render(
        request,
        "jobs/job_detail.html",
        {
            "job": job,
            "statuses": Job.Status,
            "costing": costing.job_costing(job) if can_see_costs else None,
            "materials": job.materials.select_related("added_by"),
            "labour": job.labour.select_related("employee"),
            "linked_expenses": job.expenses.select_related("category") if can_see_costs else [],
            "material_form": MaterialForm(),
            "labour_form": LabourForm(job=job, initial={"date": timezone.localdate()}),
        },
    )


@login_required
@permission_required("jobs.add_job", raise_exception=True)
def job_create(request):
    form = JobForm(request.POST or None, initial={"customer": request.GET.get("customer")})
    if request.method == "POST" and form.is_valid():
        job = form.save(commit=False)
        job.created_by = request.user
        job.save()
        form.save_m2m()
        messages.success(request, _("Job %(no)s created.") % {"no": job.number})
        return redirect(job)
    return render(request, "jobs/job_form.html", {"form": form, "job": None})


@login_required
@permission_required("jobs.change_job", raise_exception=True)
def job_update(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if not job.is_editable:
        return render(request, "jobs/not_editable.html", {"job": job}, status=409)
    form = JobForm(request.POST or None, instance=job)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Job %(no)s updated.") % {"no": job.number})
        return redirect(job)
    return render(request, "jobs/job_form.html", {"form": form, "job": job})


@require_POST
@login_required
@permission_required("jobs.change_job", raise_exception=True)
def job_status(request, pk):
    job = get_object_or_404(Job, pk=pk)
    try:
        job = change_status(job, request.POST.get("status", ""), reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("Job %(no)s is now %(status)s.") % {
            "no": job.number, "status": job.get_status_display()})
    return redirect(job)


# --- costing ---------------------------------------------------------------------

def _form_error_message(form) -> str:
    return " ".join(f"{form.fields[f].label}: {' '.join(e)}" if f in form.fields else " ".join(e)
                    for f, e in form.errors.items())


def _cost_action(request, job, action, success):
    try:
        action()
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, success)
    return redirect(job)


@require_POST
@login_required
@permission_required("jobs.change_job", raise_exception=True)
def add_material(request, pk):
    job = get_object_or_404(Job, pk=pk)
    form = MaterialForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect(job)
    return _cost_action(
        request, job, lambda: costing.add_material(job, request.user, **form.cleaned_data),
        _("Material added."),
    )


@require_POST
@login_required
@permission_required("jobs.change_job", raise_exception=True)
def add_labour(request, pk):
    job = get_object_or_404(Job, pk=pk)
    form = LabourForm(request.POST, job=job)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect(job)
    return _cost_action(
        request, job, lambda: costing.add_labour(job, request.user, **form.cleaned_data),
        _("Hours logged."),
    )


@require_POST
@login_required
@permission_required("jobs.change_job", raise_exception=True)
def delete_material(request, pk):
    entry = get_object_or_404(JobMaterial.objects.select_related("job"), pk=pk)
    return _cost_action(request, entry.job, lambda: costing.delete_cost_entry(entry), _("Material removed."))


@require_POST
@login_required
@permission_required("jobs.change_job", raise_exception=True)
def delete_labour(request, pk):
    entry = get_object_or_404(LabourEntry.objects.select_related("job"), pk=pk)
    return _cost_action(request, entry.job, lambda: costing.delete_cost_entry(entry), _("Hours removed."))


def _parse_month(raw, today):
    match = _MONTH_RE.match(raw or "")
    if match and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)), int(match.group(2))
    return today.year, today.month


@login_required
@permission_required("jobs.view_job_costing", raise_exception=True)
def profitability_report(request):
    period = _parse_month(request.GET.get("month"), timezone.localdate())
    return render(
        request,
        "jobs/profitability.html",
        {"report": costing.profitability(*period), "period": period, "month_value": "%04d-%02d" % period},
    )
