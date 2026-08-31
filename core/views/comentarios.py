from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from core.models import Comentario
from core.serializers.comentarios import ComentarioPublicSerializer, ComentarioSerializer
from core.utilidades import primera_clinica


class ComentarioViewSet(viewsets.ModelViewSet):
    queryset = Comentario.objects.all()

    def get_permissions(self): return [permissions.AllowAny()] if self.action in ["create", "public_list"] else [permissions.IsAuthenticated()]
    def get_serializer_class(self): return ComentarioPublicSerializer if self.action == "public_list" else ComentarioSerializer
    def perform_create(self, serializer): serializer.save(aprobado=False, clinica=primera_clinica())

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny])
    def public_list(self, request): return Response(ComentarioPublicSerializer(Comentario.objects.filter(aprobado=True).order_by("-creado")[:20], many=True).data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def pending(self, request): return Response(ComentarioSerializer(Comentario.objects.filter(aprobado=False).order_by("-creado"), many=True).data)

    @action(detail=True, methods=["patch"], permission_classes=[permissions.IsAuthenticated])
    def moderate(self, request, pk=None):
        obj = self.get_object(); estado = (request.data.get("estado") or "").lower().strip()
        if estado == "aprobado": obj.aprobado = True; obj.save(update_fields=["aprobado"]); return Response(ComentarioSerializer(obj).data)
        if estado == "rechazado": obj.delete(); return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"detail": "estado inválido. Usa 'aprobado' o 'rechazado'."}, status=400)
