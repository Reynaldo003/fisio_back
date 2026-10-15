from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from core.utilidades import clinica_usuario, primera_clinica

from .models import ImagenSitio
from .permissions import PuedeAdministrarImagenes
from .serializers import ImagenSitioPublicaSerializer, ImagenSitioSerializer


def clinica_administrador(request):
    clinica = clinica_usuario(request.user) or primera_clinica()
    if not clinica:
        raise ValidationError({"detail": "No existe una clínica configurada."})
    return clinica


class ImagenesPublicasView(ListAPIView):
    serializer_class = ImagenSitioPublicaSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None

    def get_queryset(self):
        clinica = primera_clinica()
        if not clinica:
            return ImagenSitio.objects.none()
        # Se incluyen las ocultas: React necesita saber que debe ocultar el respaldo.
        return ImagenSitio.objects.filter(clinica=clinica)


class ImagenesAdminView(ListCreateAPIView):
    serializer_class = ImagenSitioSerializer
    permission_classes = [IsAuthenticated, PuedeAdministrarImagenes]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    def get_queryset(self):
        return ImagenSitio.objects.filter(clinica=clinica_administrador(self.request))

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["clinica"] = clinica_administrador(self.request)
        return contexto

    def perform_create(self, serializer):
        serializer.save(
            clinica=clinica_administrador(self.request),
            actualizado_por=self.request.user,
        )


class ImagenesDetalleAdminView(RetrieveUpdateDestroyAPIView):
    serializer_class = ImagenSitioSerializer
    permission_classes = [IsAuthenticated, PuedeAdministrarImagenes]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return ImagenSitio.objects.filter(clinica=clinica_administrador(self.request))

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["clinica"] = clinica_administrador(self.request)
        return contexto

    def perform_update(self, serializer):
        imagen_anterior = serializer.instance.imagen
        ruta_anterior = imagen_anterior.name if imagen_anterior else ""
        registro = serializer.save(actualizado_por=self.request.user)
        ruta_nueva = registro.imagen.name if registro.imagen else ""
        if ruta_anterior and ruta_anterior != ruta_nueva:
            almacenamiento = imagen_anterior.storage
            transaction.on_commit(lambda: almacenamiento.delete(ruta_anterior))

    def perform_destroy(self, instance):
        imagen_anterior = instance.imagen
        ruta = imagen_anterior.name if imagen_anterior else ""
        instance.delete()
        if ruta:
            almacenamiento = imagen_anterior.storage
            transaction.on_commit(lambda: almacenamiento.delete(ruta))
