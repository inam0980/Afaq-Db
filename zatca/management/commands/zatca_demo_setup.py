"""Create an offline DEMO e-invoicing unit (self-signed certificate) for testing
and client demos. Real invoices need onboarding with ZATCA (OTP) instead."""

from django.core.management.base import BaseCommand

from zatca.services import setup_demo_egs


class Command(BaseCommand):
    help = "Set up a demo ZATCA e-invoicing unit (self-signed, not valid with ZATCA)."

    def handle(self, *args, **options):
        egs = setup_demo_egs()
        self.stdout.write(self.style.SUCCESS(f"ZATCA unit ready: {egs}"))
        if egs.is_demo:
            self.stdout.write("This is a demo unit: its certificate is self-signed and ZATCA will not accept it.")
