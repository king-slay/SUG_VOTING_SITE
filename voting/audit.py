from .models import AuditLog


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log(request, action, detail="", reg_number=""):
    user = request.user if request.user.is_authenticated else None
    AuditLog.objects.create(
        action=action,
        detail=detail,
        reg_number=reg_number,
        user=user,
        ip_address=client_ip(request),
    )
