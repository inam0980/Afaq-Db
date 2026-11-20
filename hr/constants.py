from django.utils.translation import gettext_lazy as _

SAUDI = "SA"

# ISO 3166-1 alpha-2 codes for the nationalities most common in the Saudi
# workforce. Add more here as needed; codes are stored, labels are translated.
NATIONALITY_CHOICES = [
    ("SA", _("Saudi Arabia")),
    ("BD", _("Bangladesh")),
    ("EG", _("Egypt")),
    ("ET", _("Ethiopia")),
    ("ID", _("Indonesia")),
    ("IN", _("India")),
    ("JO", _("Jordan")),
    ("KE", _("Kenya")),
    ("LK", _("Sri Lanka")),
    ("NP", _("Nepal")),
    ("PH", _("Philippines")),
    ("PK", _("Pakistan")),
    ("SD", _("Sudan")),
    ("SY", _("Syria")),
    ("UG", _("Uganda")),
    ("YE", _("Yemen")),
    ("XX", _("Other")),
]
