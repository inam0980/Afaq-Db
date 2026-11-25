import pytest


@pytest.fixture(autouse=True)
def seller(settings):
    """Seller details as printed on invoices and required by ZATCA (BR-KSA-08/09/37/66)."""
    settings.COMPANY_NAME = "AFAQ ALSIYANAH ALDAWLIYAH EST"
    settings.COMPANY_VAT_NUMBER = "399999999900003"
    settings.COMPANY_CR_NUMBER = "1010101010"
    settings.COMPANY_STREET = "Prince Sultan Road"
    settings.COMPANY_BUILDING_NO = "2322"
    settings.COMPANY_DISTRICT = "Al Murabba"
    settings.COMPANY_CITY = "Riyadh"
    settings.COMPANY_POSTAL_CODE = "12345"
    settings.ZATCA_ZERO_RATE_REASON = "VATEX-SA-33"
    settings.ZATCA_CURVE = "secp256k1"
    return settings
