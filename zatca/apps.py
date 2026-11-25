from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ZatcaConfig(AppConfig):
    name = "zatca"
    verbose_name = _("ZATCA e-invoicing")
