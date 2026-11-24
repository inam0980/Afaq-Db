"""Upload -> preview -> confirm. The cleaned rows wait in the session between
preview and confirm and are validated again on confirm (the database may have
changed meanwhile), then saved in one transaction."""

import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font

from dataimport.forms import UploadForm
from dataimport.importers import IMPORTERS
from dataimport.reading import ImportFileError, read_table

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _session_key(kind):
    return f"dataimport:{kind}"


def _importer(request, kind):
    importer = IMPORTERS.get(kind)
    if importer is None:
        raise Http404
    if not request.user.has_perm(importer.permission):
        raise PermissionDenied
    return importer


@login_required
def index(request):
    allowed = [i for i in IMPORTERS.values() if request.user.has_perm(i.permission)]
    if not allowed:
        raise PermissionDenied
    return render(request, "dataimport/index.html", {"importers": allowed, "nav_section": "import"})


@login_required
def upload(request, kind):
    importer = _importer(request, kind)
    form = UploadForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_table(form.cleaned_data["file"])
        except ImportFileError as exc:
            form.add_error("file", str(exc))
        else:
            report = importer.validate(rows)
            if report.ok:
                request.session[_session_key(kind)] = report.rows
            else:
                request.session.pop(_session_key(kind), None)
    return render(request, "dataimport/upload.html",
                  {"importer": importer, "form": form, "report": report, "nav_section": "import"})


@login_required
@require_POST
def confirm(request, kind):
    importer = _importer(request, kind)
    rows = request.session.pop(_session_key(kind), None)
    if rows is None:
        messages.error(request, _("Nothing to import. Upload a file and check the preview first."))
        return redirect("dataimport:upload", kind)
    report = importer.validate(rows)
    if not report.ok:
        messages.error(request, _("Nothing was imported: the data changed since the preview. "
                                  "Upload the file again to see the problems."))
        return redirect("dataimport:upload", kind)
    count = importer.save(report)
    messages.success(request, ngettext("Imported %(count)s record.", "Imported %(count)s records.", count)
                     % {"count": count})
    return redirect(importer.success_url)


@login_required
def template(request, kind):
    importer = _importer(request, kind)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = kind
    sheet.append(list(importer.columns))
    sheet.append([importer.example.get(c, "") for c in importer.columns])
    for index, column in enumerate(importer.columns, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.font = Font(bold=True)
        letter = cell.column_letter
        sheet.column_dimensions[letter].width = max(14, len(column) + 4)
        # Text format stops Excel turning IDs/mobiles into numbers and dropping zeros.
        sheet.column_dimensions[letter].number_format = "@"
        sheet.cell(row=2, column=index).number_format = "@"
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{kind}-template.xlsx"'
    return response
