"""Unit tests: database health check logic, isolated from a real DB."""

from unittest import mock

from django.db import OperationalError

from core.health import check_database


def test_check_database_returns_true_when_query_succeeds():
    fake_cursor = mock.MagicMock()
    fake_cursor.__enter__.return_value.fetchone.return_value = (1,)

    with mock.patch("core.health.connection") as fake_conn:
        fake_conn.cursor.return_value = fake_cursor
        assert check_database() is True


def test_check_database_returns_false_when_db_is_down():
    with mock.patch("core.health.connection") as fake_conn:
        fake_conn.cursor.side_effect = OperationalError("connection refused")
        assert check_database() is False


def test_check_database_returns_false_on_unexpected_result():
    fake_cursor = mock.MagicMock()
    fake_cursor.__enter__.return_value.fetchone.return_value = None

    with mock.patch("core.health.connection") as fake_conn:
        fake_conn.cursor.return_value = fake_cursor
        assert check_database() is False
