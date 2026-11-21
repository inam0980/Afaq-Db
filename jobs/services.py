"""Job status workflow. All status changes go through change_status()."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from hr.models import Employee
from jobs.models import Job

S = Job.Status


@transaction.atomic
def change_status(job: Job, new_status: str, reason: str = "") -> Job:
    job = Job.objects.select_for_update().get(pk=job.pk)

    if new_status not in S.values:
        raise ValidationError(_("Unknown status."))
    if new_status not in job.next_statuses:
        raise ValidationError(
            _("A %(current)s job cannot be moved to %(target)s.")
            % {"current": job.get_status_display(), "target": S(new_status).label}
        )

    if new_status == S.SCHEDULED and not job.scheduled_date:
        raise ValidationError(_("Set a scheduled date first."))

    if new_status == S.IN_PROGRESS:
        if not job.technicians.exclude(status=Employee.Status.TERMINATED).exists():
            raise ValidationError(_("Assign at least one active technician before starting."))
        job.started_at = timezone.now()

    if new_status == S.COMPLETED:
        job.completed_at = timezone.now()

    if new_status == S.CANCELLED:
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError(_("Give a reason for cancelling."))
        job.cancel_reason = reason

    job.status = new_status
    job.save()
    return job
