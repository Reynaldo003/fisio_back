from pathlib import Path

from rest_framework import serializers

from core.models import DocumentoPaciente, Paciente, RegistroClinico
from core.utilidades import puede_ver_contacto_paciente


class PacienteInlineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    uuid = serializers.UUIDField(required=False)

    class Meta:
        model = Paciente
        fields = ["id", "uuid", "nombres", "apellido_pat", "apellido_mat", "fecha_nac", "genero", "telefono", "correo", "molestia", "notas"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")

        if request and not puede_ver_contacto_paciente(request.user):
            data.pop("telefono", None)
            data.pop("correo", None)

        return data


class PacienteListadoSerializer(serializers.ModelSerializer):
    foto_url = serializers.SerializerMethodField()
    clinica_nombre = serializers.CharField(source="clinica.nombre", read_only=True)
    ultimo_servicio = serializers.CharField(read_only=True, allow_null=True)
    ultima_cita_fecha = serializers.DateField(read_only=True, allow_null=True)
    total_citas = serializers.IntegerField(read_only=True)

    class Meta:
        model = Paciente
        fields = [
            "id", "uuid", "clinica", "clinica_nombre", "nombres", "apellido_pat", "apellido_mat", "fecha_nac", "genero",
            "telefono", "correo", "molestia", "notas", "foto_url", "registro", "estado_tratamiento", "fecha_alta",
            "ultimo_servicio", "ultima_cita_fecha", "total_citas",
        ]

    def get_foto_url(self, obj):
        if not obj.foto:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.foto.url) if request else obj.foto.url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")

        if request and not puede_ver_contacto_paciente(request.user):
            data.pop("telefono", None)
            data.pop("correo", None)

        return data


class PacienteSerializer(PacienteListadoSerializer):
    class Meta(PacienteListadoSerializer.Meta):
        read_only_fields = ["id", "uuid", "registro", "ultimo_servicio", "ultima_cita_fecha", "total_citas", "foto_url", "clinica_nombre"]


class DocumentoPacienteSerializer(serializers.ModelSerializer):
    archivo_url = serializers.SerializerMethodField()
    tamano = serializers.SerializerMethodField()
    subido_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoPaciente
        fields = ["id", "paciente", "archivo", "archivo_url", "nombre_original", "tipo", "descripcion", "tamano", "subido_por", "subido_por_nombre", "creado"]
        read_only_fields = ["id", "paciente", "archivo_url", "nombre_original", "tamano", "subido_por", "subido_por_nombre", "creado"]
        extra_kwargs = {"archivo": {"write_only": True}}

    def validate_archivo(self, archivo):
        permitidas = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp"}
        ext = Path(archivo.name).suffix.lower()
        if ext not in permitidas:
            raise serializers.ValidationError("Formato no permitido. Usa PDF, Word, JPG, PNG o WEBP.")
        if archivo.size > 15 * 1024 * 1024:
            raise serializers.ValidationError("El archivo no puede superar 15 MB.")
        return archivo

    def get_archivo_url(self, obj):
        if not obj.archivo:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.archivo.url) if request else obj.archivo.url

    def get_tamano(self, obj):
        try:
            return obj.archivo.size
        except Exception:
            return 0

    def get_subido_por_nombre(self, obj):
        if not obj.subido_por:
            return None
        return (obj.subido_por.get_full_name() or "").strip() or obj.subido_por.username


class RegistroClinicoSerializer(serializers.ModelSerializer):
    profesional_nombre = serializers.SerializerMethodField()

    class Meta:
        model = RegistroClinico
        fields = ["id", "paciente", "fecha", "titulo", "descripcion", "profesional", "profesional_nombre", "creado", "actualizado"]
        read_only_fields = ["id", "paciente", "profesional", "profesional_nombre", "creado", "actualizado"]

    def get_profesional_nombre(self, obj):
        if not obj.profesional:
            return None
        return (obj.profesional.get_full_name() or "").strip() or obj.profesional.username
