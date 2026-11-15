from django.contrib.auth import views as auth_views
from django.db import connection
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from .forms import LoginForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@require_GET
def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")
