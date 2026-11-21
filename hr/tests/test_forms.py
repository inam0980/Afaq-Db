"""Unit tests: EmployeeForm rendering (no database)."""

import datetime as dt

import pytest
from django.utils import translation

from hr.forms import EmployeeForm
from hr.tests.factories import EmployeeFactory


@pytest.mark.parametrize("lang", ["en", "ar", "en-gb", "de"])
def test_date_inputs_always_render_iso_even_in_other_locales(lang):
    # Browsers' <input type="date"> accept only YYYY-MM-DD. en-gb / de would
    # otherwise localize to 01/02/2022 / 01.02.2022 and the field shows empty.
    emp = EmployeeFactory.build(hire_date=dt.date(2022, 2, 1))

    with translation.override(lang):
        html = str(EmployeeForm(instance=emp)["hire_date"])

    assert 'type="date"' in html
    assert 'value="2022-02-01"' in html
