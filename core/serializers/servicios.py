from rest_framework import serializers
from core.models import Servicio


class ServicioSerializer(serializers.ModelSerializer):
    imagen_url = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = Servicio
        fields = "__all__"
        extra_kwargs = {"clinica": {"read_only": True}}

    def get_imagen_url(self, obj):
        if not obj.imagen: return None
        request = self.context.get("request"); return request.build_absolute_uri(obj.imagen.url) if request else obj.imagen.url
