"""Unit tests: project-wide settings the ERP depends on."""

from django.conf import settings


def test_database_engine_is_postgresql():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_secret_key_is_not_the_generated_insecure_default():
    assert not settings.SECRET_KEY.startswith("django-insecure-")


def test_timezone_is_riyadh_and_tz_aware():
    assert settings.TIME_ZONE == "Asia/Riyadh"
    assert settings.USE_TZ is True


def test_arabic_and_english_are_enabled():
    codes = [code for code, _ in settings.LANGUAGES]
    assert codes == ["en", "ar"]


def test_core_app_is_installed():
    assert "core" in settings.INSTALLED_APPS


def test_hr_and_audit_history_are_installed():
    assert "hr" in settings.INSTALLED_APPS
    assert "simple_history" in settings.INSTALLED_APPS
    assert "simple_history.middleware.HistoryRequestMiddleware" in settings.MIDDLEWARE
