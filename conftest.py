"""Shared pytest fixtures for the whole project."""

import pytest
from django.contrib.auth.models import Permission


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    # PBKDF2 is deliberately slow; tests only need *a* hash. Never used in production.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def _user_with_perms(django_user_model, username, codenames):
    user = django_user_model.objects.create_user(username=username, password="Test-pass-123")
    perms = Permission.objects.filter(codename__in=codenames)
    assert perms.count() == len(codenames), "unknown permission codename"
    user.user_permissions.add(*perms)
    return user


@pytest.fixture
def hr_user(django_user_model):
    return _user_with_perms(
        django_user_model, "hr_manager", ["view_employee", "add_employee", "change_employee"]
    )


@pytest.fixture
def hr_client(client, hr_user):
    client.force_login(hr_user)
    return client


@pytest.fixture
def viewer_client(client, django_user_model):
    client.force_login(_user_with_perms(django_user_model, "viewer", ["view_employee"]))
    return client


@pytest.fixture
def client_with_perms(client, django_user_model):
    """Return a function: client_with_perms("view_employee", ...) -> logged-in client."""

    def make(*codenames):
        client.force_login(_user_with_perms(django_user_model, "custom_user", list(codenames)))
        return client

    return make


@pytest.fixture
def no_perm_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("nobody", password="Test-pass-123"))
    return client
