from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.utils.translation import ngettext

from security.services import lockout_remaining


class SecureLoginView(LoginView):
    """Our login page: tells a locked-out user how long to wait instead of the
    generic 'wrong password' message."""

    def form_invalid(self, form):
        minutes = lockout_remaining(form.data.get("username", ""), self.request)
        if minutes:
            form.errors.clear()
            form.add_error(None, ValidationError(
                ngettext(
                    "Too many failed attempts. Try again in %(m)s minute.",
                    "Too many failed attempts. Try again in %(m)s minutes.",
                    minutes,
                ) % {"m": minutes},
                code="locked",
            ))
        return super().form_invalid(form)
