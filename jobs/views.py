from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from hr.models import Employee
from jobs.forms import JobForm
from jobs.models import Job
from jobs.services import change_status


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
    return render(request, "jobs/job_detail.html", {"job": job, "statuses": Job.Status})


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
