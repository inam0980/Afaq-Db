from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class LoginEvent(models.Model):
    """Every login attempt, successful or not. Used for lockout and as an audit log."""

    username = models.CharField(_("username"), max_length=150, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ip = models.CharField(_("IP address"), max_length=45, db_index=True, blank=True)
    user_agent = models.CharField(_("browser"), max_length=300, blank=True)
    successful = models.BooleanField(_("successful"))
    created_at = models.DateTimeField(_("time"), auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("login event")
        verbose_name_plural = _("login events")

    def __str__(self):
        return f"{self.username} {'ok' if self.successful else 'FAILED'} {self.created_at:%Y-%m-%d %H:%M}"
