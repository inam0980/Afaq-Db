"""Brute-force protection.

A username is locked after USERNAME_FAILURE_LIMIT failed logins within
LOCKOUT_MINUTES (counted since its last successful login); an IP address is
locked after IP_FAILURE_LIMIT failures within the same window, whatever the
usernames tried. Locks lift LOCKOUT_MINUTES after the latest failure.
"""

import datetime as dt
import math

from django.db.models import Max
from django.utils import timezone

from security.models import LoginEvent

USERNAME_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 20
LOCKOUT_MINUTES = 15


def client_ip(request) -> str:
    # Behind Nginx the real address arrives in X-Real-IP (set by our proxy config).
    if request is None:
        return ""
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def record(username: str, request, *, successful: bool, user=None) -> LoginEvent:
    return LoginEvent.objects.create(
        username=(username or "").strip().lower()[:150],
        user=user,
        ip=client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else "")[:300],
        successful=successful,
    )


def _remaining(failures, limit: int, now) -> int:
    agg = failures.aggregate(n=Max("created_at"))
    if failures.count() < limit:
        return 0
    unlock_at = agg["n"] + dt.timedelta(minutes=LOCKOUT_MINUTES)
    return max(0, math.ceil((unlock_at - now).total_seconds() / 60))


def lockout_remaining(username: str, request) -> int:
    """Minutes until this username/IP may try again; 0 if not locked."""
    now = timezone.now()
    window_start = now - dt.timedelta(minutes=LOCKOUT_MINUTES)
    username = (username or "").strip().lower()

    last_success = (
        LoginEvent.objects.filter(username=username, successful=True).aggregate(t=Max("created_at"))["t"]
    )
    since = max(window_start, last_success) if last_success else window_start
    by_user = LoginEvent.objects.filter(username=username, successful=False, created_at__gt=since)

    ip = client_ip(request)
    by_ip = LoginEvent.objects.filter(ip=ip, successful=False, created_at__gt=window_start) if ip else None

    return max(
        _remaining(by_user, USERNAME_FAILURE_LIMIT, now),
        _remaining(by_ip, IP_FAILURE_LIMIT, now) if by_ip is not None else 0,
    )
