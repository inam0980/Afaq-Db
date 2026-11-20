from django.http import JsonResponse
from django.views.decorators.http import require_GET

from core.health import check_database


@require_GET
def health(request):
    if check_database():
        return JsonResponse({"status": "ok", "database": "ok"})
    return JsonResponse({"status": "error", "database": "error"}, status=503)
