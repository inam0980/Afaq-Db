from django import forms
from django.utils.translation import gettext_lazy as _

from dataimport.reading import EXTENSIONS, MAX_BYTES


class UploadForm(forms.Form):
    file = forms.FileField(
        label=_("File"),
        help_text=_("Excel (.xlsx) or CSV, up to 2 MB. Use the template so the column names match."),
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(EXTENSIONS)}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_BYTES:
            raise forms.ValidationError(_("The file is larger than 2 MB."))
        return uploaded
