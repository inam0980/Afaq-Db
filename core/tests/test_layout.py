"""Integration tests: app shell (sidebar, active item, fonts, auth layout)."""

import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def sidebar(html: str) -> str:
    match = re.search(r'<nav class="sidebar-nav".*?</nav>', html, re.S)
    assert match, "sidebar missing"
    return match.group(0)


def test_sidebar_links_follow_permissions(viewer_client):
    nav = sidebar(viewer_client.get(reverse("home")).content.decode())

    assert reverse("home") in nav
    assert reverse("hr:employee_list") in nav
    assert reverse("hr:expiring_documents") in nav
    assert reverse("payroll:run_list") not in nav
    assert reverse("admin:index") not in nav


def test_sidebar_shows_payroll_and_admin_when_allowed(admin_client):
    nav = sidebar(admin_client.get(reverse("home")).content.decode())
    assert reverse("payroll:run_list") in nav
    assert reverse("admin:index") in nav


@pytest.mark.parametrize(
    "url_name, active_href",
    [
        ("home", "home"),
        ("hr:employee_list", "hr:employee_list"),
        ("hr:employee_create", "hr:employee_list"),
        ("hr:expiring_documents", "hr:expiring_documents"),
        ("payroll:run_list", "payroll:run_list"),
    ],
)
def test_current_section_is_marked_active(admin_client, url_name, active_href):
    nav = sidebar(admin_client.get(reverse(url_name)).content.decode())
    active = re.findall(r'<a [^>]*aria-current="page"[^>]*>', nav)

    assert len(active) == 1
    assert f'href="{reverse(active_href)}"' in active[0]


def test_fonts_are_served_locally(viewer_client):
    html = viewer_client.get(reverse("home")).content.decode()
    assert "fonts.googleapis.com" not in html
    assert "css/app.css" in html


def test_login_page_uses_auth_layout_without_sidebar(client):
    html = client.get(reverse("login")).content.decode()
    assert 'class="sidebar-nav"' not in html
    assert 'class="auth-card"' in html


def test_header_shows_user_initials(client, django_user_model):
    user = django_user_model.objects.create_user(
        "ahmed", password="Test-pass-123", first_name="Ahmed", last_name="Khan"
    )
    client.force_login(user)
    html = client.get(reverse("home")).content.decode()
    assert ">AK<" in html


def test_navigation_without_resolved_url_marks_nothing_active(rf):
    from core.context_processors import navigation

    request = rf.get("/no-such-page/")   # RequestFactory: no resolver_match
    assert navigation(request) == {"nav_section": ""}


def test_404_page_does_not_crash_the_layout(viewer_client):
    assert viewer_client.get("/no-such-page/").status_code == 404


def test_salary_page_highlights_employees_section(admin_client):
    from hr.tests.factories import EmployeeFactory

    emp = EmployeeFactory()
    nav = sidebar(admin_client.get(reverse("payroll:employee_salary", args=[emp.pk])).content.decode())
    active = re.findall(r'<a [^>]*aria-current="page"[^>]*>', nav)
    assert len(active) == 1
    assert f'href="{reverse("hr:employee_list")}"' in active[0]


def test_sidebar_hides_employees_without_permission(no_perm_client):
    nav = sidebar(no_perm_client.get(reverse("home")).content.decode())
    assert reverse("hr:employee_list") not in nav
    assert reverse("hr:expiring_documents") not in nav


def test_every_font_referenced_in_css_exists():
    from pathlib import Path

    from django.contrib.staticfiles import finders

    css_path = Path(finders.find("css/app.css"))
    urls = re.findall(r'url\("([^"]+)"\)', css_path.read_text(encoding="utf-8"))
    assert urls, "no fonts referenced"
    for url in urls:
        assert (css_path.parent / url).resolve().is_file(), url


@pytest.mark.parametrize("url_name", ["home", "login"])
def test_stylesheet_url_is_cache_busted(admin_client, client, url_name):
    c = client if url_name == "login" else admin_client
    html = c.get(reverse(url_name)).content.decode()
    assert re.search(r'href="/static/css/app\.css\?v=[0-9a-f]{10}"', html)
