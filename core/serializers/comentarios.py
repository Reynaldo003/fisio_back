from rest_framework import serializers
from core.models import Comentario


class ComentarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comentario
        fields = "__all__"
        read_only_fields = ["aprobado", "creado"]


class ComentarioPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comentario
        fields = ["id", "nombre_completo", "calificacion", "descripcion"]
