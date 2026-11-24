import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.utils.translation import gettext as _

IDLE_KEY = "_last_activity"


class IdleTimeoutMiddleware:
    """Log a user out after SESSION_IDLE_MINUTES without any request
    (e.g. a computer left unlocked in the office)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = time.time()
            last = request.session.get(IDLE_KEY)
            limit = settings.SESSION_IDLE_MINUTES * 60
            if last is not None and now - last > limit:
                logout(request)
                messages.info(
                    request,
                    _("You were signed out after %(m)s minutes without activity.")
                    % {"m": settings.SESSION_IDLE_MINUTES},
                )
                return redirect_to_login(request.get_full_path())
            request.session[IDLE_KEY] = now
        return self.get_response(request)
