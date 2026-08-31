#backend/core/urls/pacientes.py
from rest_framework.routers import DefaultRouter
from core.views.pacientes import PacienteViewSet

router = DefaultRouter(); router.register("pacientes", PacienteViewSet, basename="pacientes")
urlpatterns = router.urls
