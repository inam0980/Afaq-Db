"""Template context shared by every page."""

# (namespace, url_name) -> sidebar section; namespace alone is the fallback.
_SECTIONS = {
    (None, "home"): "home",
    ("hr", "expiring_documents"): "expiring",
    ("hr", None): "employees",
    ("payroll", "employee_salary"): "employees",
    ("payroll", None): "payroll",
    ("expenses", None): "expenses",
    ("jobs", "profitability"): "profitability",
    ("jobs", None): "jobs",
    ("customers", None): "customers",
    ("invoicing", None): "invoices",
}


def navigation(request):
    match = getattr(request, "resolver_match", None)
    if match is None:
        return {"nav_section": ""}
    namespace = match.namespace or None
    section = _SECTIONS.get((namespace, match.url_name)) or _SECTIONS.get((namespace, None), "")
    return {"nav_section": section}
