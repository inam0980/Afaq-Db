"""Login protection: lockout after repeated failures, audit log of every attempt."""

import datetime as dt

import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from security.models import LoginEvent
from security.services import (
    IP_FAILURE_LIMIT,
    LOCKOUT_MINUTES,
    USERNAME_FAILURE_LIMIT,
    lockout_remaining,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-pass-123"
LOGIN = reverse("login")


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ahmed", password=PASSWORD)


def attempt(client, username, password, ip="10.0.0.5"):
    return client.post(LOGIN, {"username": username, "password": password}, REMOTE_ADDR=ip,
                       HTTP_USER_AGENT="pytest-browser")


def fail(client, username="ahmed", times=1, ip="10.0.0.5"):
    for _ in range(times):
        attempt(client, username, "wrong", ip=ip)


# --- audit log -------------------------------------------------------------------

def test_failed_and_successful_logins_are_recorded(client, user):
    fail(client)
    attempt(client, "ahmed", PASSWORD)

    failed, ok = LoginEvent.objects.order_by("created_at")
    assert (failed.successful, failed.username, failed.ip, failed.user) == (False, "ahmed", "10.0.0.5", None)
    assert (ok.successful, ok.user, ok.user_agent) == (True, user, "pytest-browser")


def test_username_is_stored_lower_case(client, user):
    fail(client, username="AHMED")
    assert LoginEvent.objects.get().username == "ahmed"


# --- lockout by username ---------------------------------------------------------

def test_account_locks_after_too_many_failures(client, user):
    fail(client, times=USERNAME_FAILURE_LIMIT)

    response = attempt(client, "ahmed", PASSWORD)

    assert response.status_code == 200                       # login page again, not a redirect
    assert "_auth_user_id" not in client.session
    assert "Too many failed attempts" in response.content.decode()


def test_one_failure_less_than_the_limit_still_allows_login(client, user):
    fail(client, times=USERNAME_FAILURE_LIMIT - 1)
    response = attempt(client, "ahmed", PASSWORD)
    assert response.status_code == 302


def test_lock_is_case_insensitive(client, user):
    fail(client, username="Ahmed", times=USERNAME_FAILURE_LIMIT)
    assert attempt(client, "ahmed", PASSWORD).status_code == 200


def test_lock_expires(client, user):
    fail(client, times=USERNAME_FAILURE_LIMIT)
    LoginEvent.objects.update(created_at=timezone.now() - dt.timedelta(minutes=LOCKOUT_MINUTES + 1))
    assert attempt(client, "ahmed", PASSWORD).status_code == 302


def test_successful_login_resets_the_count(client, user):
    fail(client, times=USERNAME_FAILURE_LIMIT - 1)
    assert attempt(client, "ahmed", PASSWORD).status_code == 302
    Client().logout()
    other = Client()
    fail(other, times=USERNAME_FAILURE_LIMIT - 1)
    assert attempt(other, "ahmed", PASSWORD).status_code == 302


def test_lockout_remaining_minutes(user, rf):
    for _ in range(USERNAME_FAILURE_LIMIT):
        LoginEvent.objects.create(username="ahmed", ip="1.1.1.1", successful=False)
    request = rf.get("/", REMOTE_ADDR="1.1.1.1")
    assert 0 < lockout_remaining("ahmed", request) <= LOCKOUT_MINUTES
    assert lockout_remaining("someone-else", rf.get("/", REMOTE_ADDR="9.9.9.9")) == 0


# --- lockout by IP -------------------------------------------------------------------

def test_ip_locks_after_many_failures_across_usernames(client, user, django_user_model):
    django_user_model.objects.create_user("sara", password=PASSWORD)
    for i in range(IP_FAILURE_LIMIT):
        attempt(client, f"guess{i}", "wrong", ip="10.9.9.9")

    assert attempt(client, "sara", PASSWORD, ip="10.9.9.9").status_code == 200
    assert attempt(Client(), "sara", PASSWORD, ip="10.1.1.1").status_code == 302   # other IP fine


# --- applies everywhere authentication happens --------------------------------------

def test_lock_also_blocks_the_admin_login(client, user):
    user.is_staff = True
    user.save()
    fail(client, times=USERNAME_FAILURE_LIMIT)
    response = client.post(reverse("admin:login"), {"username": "ahmed", "password": PASSWORD},
                           REMOTE_ADDR="10.0.0.5")
    assert "_auth_user_id" not in client.session
    assert response.status_code == 200


def test_authenticate_without_request_still_works(user):
    assert authenticate(username="ahmed", password=PASSWORD) == user


def test_failed_authenticate_without_request_is_recorded_without_ip(user):
    assert authenticate(username="ahmed", password="wrong") is None
    event = LoginEvent.objects.get()
    assert (event.successful, event.ip, event.user_agent) == (False, "", "")


def test_login_event_str():
    e = LoginEvent.objects.create(username="ahmed", ip="1.1.1.1", successful=False)
    assert str(e).startswith("ahmed FAILED ")


def test_lock_check_ignores_username_case(user, rf):
    for _ in range(USERNAME_FAILURE_LIMIT):
        LoginEvent.objects.create(username="ahmed", ip="1.1.1.1", successful=False)
    assert lockout_remaining("AHMED", rf.get("/", REMOTE_ADDR="2.2.2.2")) > 0


def test_real_client_ip_is_taken_from_the_proxy_header(rf):
    from security.services import client_ip

    behind_nginx = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="10.20.30.40")
    assert client_ip(behind_nginx) == "10.20.30.40"
    assert client_ip(rf.get("/", REMOTE_ADDR="10.0.0.9")) == "10.0.0.9"


def test_policy_is_five_failures_per_user_and_twenty_per_ip(client, user, django_user_model):
    # Literal numbers on purpose: the agreed policy must not drift silently.
    fail(client, times=5)
    assert attempt(client, "ahmed", PASSWORD).status_code == 200            # 5th failure locks

    django_user_model.objects.create_user("sara", password=PASSWORD)
    other = Client()
    for i in range(20):
        attempt(other, f"guess{i}", "wrong", ip="10.7.7.7")
    assert attempt(other, "sara", PASSWORD, ip="10.7.7.7").status_code == 200   # 20th failure locks the IP
    assert LOCKOUT_MINUTES == 15
