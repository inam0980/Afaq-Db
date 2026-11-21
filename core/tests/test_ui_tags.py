"""Unit tests: UI template helpers."""

import datetime as dt

import pytest
from django.template import Context, Template
from django.utils import timezone

from core.templatetags.ui import days_left, expiry_tone, initials


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Ahmed Khan", "AK"),
        ("sara", "S"),
        ("Mohammed bin Salman Al Saud", "MS"),   # first + last word
        ("  ahmed   khan  ", "AK"),
        ("أحمد خان", "أخ"),
        ("", "?"),
        (None, "?"),
    ],
)
def test_initials(name, expected):
    assert initials(name) == expected


def test_icon_tag_renders_inline_svg():
    html = Template('{% load ui %}{% icon "users" %}').render(Context())
    assert html.startswith("<svg")
    assert 'aria-hidden="true"' in html


def test_icon_tag_unknown_name_fails_loudly():
    with pytest.raises(Exception):
        Template('{% load ui %}{% icon "does-not-exist" %}').render(Context())


# --- expiry helpers -------------------------------------------------------------

def _in(days):
    return timezone.localdate() + dt.timedelta(days=days)


def test_days_left():
    assert days_left(_in(10)) == 10
    assert days_left(_in(0)) == 0
    assert days_left(_in(-3)) == -3
    assert days_left(None) is None


@pytest.mark.parametrize(
    "days, tone",
    [(-1, "expired"), (0, "soon"), (30, "soon"), (31, "ok")],
)
def test_expiry_tone(days, tone):
    assert expiry_tone(_in(days)) == tone


def test_expiry_tone_for_missing_date():
    assert expiry_tone(None) == "none"


def test_absolute():
    from core.templatetags.ui import absolute

    assert absolute(-3) == 3
    assert absolute(4) == 4


# --- cache-busted static assets ---------------------------------------------------

def test_asset_url_has_content_version(tmp_path, monkeypatch):
    from core.templatetags import ui

    f = tmp_path / "app.css"
    f.write_bytes(b"body{color:red}")
    monkeypatch.setattr(ui.finders, "find", lambda path: str(f))

    url = ui.asset("css/app.css")

    assert url.startswith("/static/css/app.css?v=")
    assert len(url.split("?v=")[1]) == 10


def test_asset_version_changes_when_file_changes(tmp_path, monkeypatch):
    import os

    from core.templatetags import ui

    f = tmp_path / "app.css"
    f.write_bytes(b"body{color:red}")
    monkeypatch.setattr(ui.finders, "find", lambda path: str(f))
    first = ui.asset("css/app.css")

    f.write_bytes(b"body{color:blue}")
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))   # new mtime

    assert ui.asset("css/app.css") != first


def test_asset_for_missing_file_falls_back_to_plain_url(monkeypatch):
    from core.templatetags import ui

    monkeypatch.setattr(ui.finders, "find", lambda path: None)
    assert ui.asset("css/missing.css") == "/static/css/missing.css"
