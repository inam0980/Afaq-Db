import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class LettersAndDigitsValidator:
    """Require at least one letter and one digit."""

    def validate(self, password, user=None):
        if not (re.search(r"[^\W\d_]", password) and re.search(r"\d", password)):
            raise ValidationError(
                _("Your password must contain both letters and numbers."), code="password_no_mix"
            )

    def get_help_text(self):
        return _("Your password must contain both letters and numbers.")
