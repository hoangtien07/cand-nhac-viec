from django.shortcuts import render


def forbidden(request, exception=None):
    msg = str(exception) if exception and str(exception) else "Bạn không có quyền thực hiện thao tác này."
    return render(request, "errors/403.html", {"message": msg}, status=403)


def not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)
