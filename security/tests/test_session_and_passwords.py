"""Idle logout, session settings, password policy, password change, admin."""

import datetime as dt
import importlib

import pytest
from django.conf import settings as django_settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from security.middleware import IDLE_KEY

pytestmark = pytest.mark.django_db

HOME = reverse("home")


# --- idle timeout ----------------------------------------------------------------

def test_activity_is_tracked(admin_client):
    admin_client.get(HOME)
    assert IDLE_KEY in admin_client.session


def test_idle_session_is_logged_out(admin_client, settings):
    admin_client.get(HOME)
    session = admin_client.session
    session[IDLE_KEY] = (timezone.now() - dt.timedelta(minutes=settings.SESSION_IDLE_MINUTES + 1)).timestamp()
    session.save()

    response = admin_client.get(HOME)

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
    assert "_auth_user_id" not in admin_client.session


def test_recent_activity_keeps_the_session(admin_client, settings):
    admin_client.get(HOME)
    session = admin_client.session
    session[IDLE_KEY] = (timezone.now() - dt.timedelta(minutes=settings.SESSION_IDLE_MINUTES - 1)).timestamp()
    session.save()
    assert admin_client.get(HOME).status_code == 200


def test_anonymous_requests_are_untouched(client):
    assert client.get(reverse("login")).status_code == 200
    assert IDLE_KEY not in client.session


def test_session_settings():
    assert django_settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert django_settings.SESSION_COOKIE_AGE == 8 * 60 * 60
    assert django_settings.SESSION_IDLE_MINUTES == 30
    assert django_settings.SESSION_COOKIE_HTTPONLY is True


# --- password policy -------------------------------------------------------------

@pytest.mark.parametrize("weak", ["Ab1", "Abcdef12", "Abcdefg12", "onlyletterslong", "1234567890123", "password123"])
def test_weak_passwords_rejected(weak):
    with pytest.raises(ValidationError):
        validate_password(weak)


@pytest.mark.parametrize("good", ["Demo@12345", "Riyadh2026Afaq"])
def test_good_passwords_accepted(good):
    validate_password(good)


def test_password_change_flow(client, django_user_model):
    user = django_user_model.objects.create_user("sara", password="Old-pass-123")
    client.force_login(user)

    page = client.get(reverse("password_change"))
    assert page.status_code == 200 and "sidebar-nav" in page.content.decode()

    response = client.post(reverse("password_change"), {
        "old_password": "Old-pass-123", "new_password1": "New-pass-456", "new_password2": "New-pass-456",
    })
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200          # "done" page renders
    user.refresh_from_db()
    assert user.check_password("New-pass-456")


def test_password_change_rejects_weak_password(client, django_user_model):
    user = django_user_model.objects.create_user("sara", password="Old-pass-123")
    client.force_login(user)
    response = client.post(reverse("password_change"), {
        "old_password": "Old-pass-123", "new_password1": "short", "new_password2": "short",
    })
    assert response.status_code == 200 and response.context["form"].errors


def test_topbar_links_to_password_change(admin_client):
    assert reverse("password_change") in admin_client.get(HOME).content.decode()


# --- login event admin ---------------------------------------------------------------

def test_login_events_are_read_only_in_admin(admin_client, rf, admin_user):
    from django.contrib.admin.sites import site

    from security.models import LoginEvent

    LoginEvent.objects.create(username="x", ip="1.1.1.1", successful=False)
    assert admin_client.get(reverse("admin:security_loginevent_changelist")).status_code == 200
    request = rf.get("/")
    request.user = admin_user
    model_admin = site._registry[LoginEvent]
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)


# --- production settings ---------------------------------------------------------------

@pytest.fixture
def production_settings(monkeypatch):
    import config.settings as cfg

    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("HTTPS", "True")
    monkeypatch.setenv("ALLOWED_HOSTS", "erp.afaq.local")
    monkeypatch.setenv("ADMIN_URL", "manage-7f3k/")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    reloaded = importlib.reload(cfg)
    yield reloaded
    monkeypatch.undo()
    importlib.reload(cfg)


def test_https_settings(production_settings):
    s = production_settings
    assert s.SECURE_SSL_REDIRECT and s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE
    assert s.SECURE_HSTS_SECONDS >= 31536000
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.CSRF_TRUSTED_ORIGINS == ["https://erp.afaq.local"]
    assert s.ADMIN_URL == "manage-7f3k/"
    assert s.MAILERS["default"]["BACKEND"] == "django.core.mail.backends.smtp.EmailBackend"
    assert s.MAILERS["default"]["OPTIONS"]["host"] == "smtp.example.com"


def test_development_defaults_are_not_https():
    import config.settings as cfg

    assert cfg.SECURE_SSL_REDIRECT is False
    assert cfg.ADMIN_URL == "admin/"
    assert cfg.MAILERS["default"]["BACKEND"] == "django.core.mail.backends.console.EmailBackend"


def test_always_on_headers():
    assert django_settings.X_FRAME_OPTIONS == "DENY"
    assert django_settings.SECURE_REFERRER_POLICY == "same-origin"
    assert django_settings.SECURE_CONTENT_TYPE_NOSNIFF is True


def test_deploy_check_passes_with_production_settings(production_settings, settings):
    for name in ("DEBUG", "SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE",
                 "SECURE_HSTS_SECONDS", "SECURE_HSTS_INCLUDE_SUBDOMAINS", "SECURE_HSTS_PRELOAD",
                 "SECURE_PROXY_SSL_HEADER", "ALLOWED_HOSTS", "MAILERS"):
        setattr(settings, name, getattr(production_settings, name))
    call_command("check", "--deploy", "--fail-level", "WARNING")
