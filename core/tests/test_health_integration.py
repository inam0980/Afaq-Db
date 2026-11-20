"""Integration tests: URL -> view -> real PostgreSQL test database."""

from unittest import mock

import pytest
from django.db import OperationalError, connection
from django.urls import reverse


@pytest.mark.django_db
def test_tests_run_against_real_postgresql():
    assert connection.vendor == "postgresql"


@pytest.mark.django_db
def test_health_endpoint_reports_ok_with_real_db(client):
    response = client.get(reverse("core:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_health_endpoint_returns_503_when_db_is_down(client):
    with mock.patch(
        "core.health.connection.cursor",
        side_effect=OperationalError("connection refused"),
    ):
        response = client.get(reverse("core:health"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}


@pytest.mark.django_db
def test_health_endpoint_rejects_post(client):
    response = client.post(reverse("core:health"))

    assert response.status_code == 405
