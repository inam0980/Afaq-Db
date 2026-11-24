"""Integration: the dashboard warns administrators when backups stop running."""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from backups import services

pytestmark = pytest.mark.django_db

HOME = reverse("home")


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_user("boss", password="x", is_staff=True)
    client.force_login(user)
    return client


def test_staff_warned_when_never_backed_up(staff_client):
    html = staff_client.get(HOME).content.decode()
    assert "No backup has been made yet" in html


def test_staff_warned_when_backup_is_old(staff_client, fake_pg, settings):
    settings.BACKUP_WARN_HOURS = 36
    services.create_backup(now=timezone.now() - dt.timedelta(days=3))
    html = staff_client.get(HOME).content.decode()
    assert "The last backup is" in html and "No backup has been made yet" not in html


def test_no_warning_with_a_fresh_backup(staff_client, fake_pg):
    services.create_backup()
    html = staff_client.get(HOME).content.decode()
    assert "backup-warning" not in html


def test_ordinary_users_never_see_it(viewer_client):
    assert "backup-warning" not in viewer_client.get(HOME).content.decode()
