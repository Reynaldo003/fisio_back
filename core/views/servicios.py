from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from core.models import Servicio
from core.permissions import IsAdminUserStrict
from core.serializers.servicios import ServicioSerializer
from core.utilidades import primera_clinica


class ServicioViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Servicio.objects.filter(activo=True); serializer_class = ServicioSerializer; permission_classes = [permissions.AllowAny]
    def get_serializer_context(self): ctx = super().get_serializer_context(); ctx["request"] = self.request; return ctx


class ServicioAdminViewSet(viewsets.ModelViewSet):
    serializer_class = ServicioSerializer; permission_classes = [IsAdminUserStrict]; parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get_queryset(self): return Servicio.objects.all().order_by("-id")
    def perform_create(self, serializer):
        clinica = primera_clinica()
        if not clinica: raise ValidationError({"detail": "No existe clínica configurada."})
        serializer.save(clinica=clinica)
