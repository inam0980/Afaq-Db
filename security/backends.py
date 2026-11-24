from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

from security.services import lockout_remaining


class LockoutModelBackend(ModelBackend):
    """ModelBackend that refuses locked usernames/IPs everywhere Django
    authenticates (our login page and the admin login alike)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is not None and username and lockout_remaining(username, request) > 0:
            raise PermissionDenied   # authenticate() stops and fires user_login_failed
        return super().authenticate(request, username=username, password=password, **kwargs)
