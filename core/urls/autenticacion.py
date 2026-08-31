from django.urls import path
from core.views.autenticacion import password_reset_confirm, password_reset_request

urlpatterns = [
    path("auth/password-reset/", password_reset_request, name="password-reset"),
    path("auth/password-reset-confirm/", password_reset_confirm, name="password-reset-confirm"),
]
