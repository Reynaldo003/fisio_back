from rest_framework import serializers

from core.models import BloqueoHorario, Cita, Paciente
from core.utilidades import puede_ver_dinero

from .pacientes import PacienteInlineSerializer


CAMPOS_MONETARIOS = {
    "precio",
    "metodo_pago",
    "descuento_porcentaje",
    "anticipo",
    "monto_final",
}


def ocultar_dinero_segun_rol(serializer, data):
    request = serializer.context.get("request")
    if not request:
        return data

    if puede_ver_dinero(request.user):
        return data

    for field in CAMPOS_MONETARIOS:
        data.pop(field, None)

    return data


class CitaSerializer(serializers.ModelSerializer):
    paciente_nombre = serializers.SerializerMethodField()
    servicio_nombre = serializers.CharField(source="servicio.nombre", read_only=True)
    profesional_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Cita
        fields = "__all__"
        read_only_fields = ["creado", "actualizado"]

    def get_paciente_nombre(self, obj):
        p = obj.paciente
        return f"{p.nombres} {p.apellido_pat} {p.apellido_mat or ''}".strip()

    def get_profesional_nombre(self, obj):
        u = obj.profesional
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return full or u.username

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return ocultar_dinero_segun_rol(self, data)


class CitaCreateSerializer(serializers.ModelSerializer):
    paciente = PacienteInlineSerializer()
    paciente_id = serializers.IntegerField(required=False, write_only=True)
    paciente_uuid = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = Cita
        fields = [
            "paciente",
            "paciente_id",
            "paciente_uuid",
            "servicio",
            "profesional",
            "fecha",
            "hora_inicio",
            "hora_termina",
            "precio",
            "metodo_pago",
            "estado",
            "notas",
            "pagado",
            "descuento_porcentaje",
            "anticipo",
            "monto_final",
        ]

    def _resolver_paciente_existente(self, clinica, paciente_data):
        paciente_id = self.initial_data.get("paciente_id") or paciente_data.get("id")
        paciente_uuid = self.initial_data.get("paciente_uuid") or paciente_data.get("uuid")

        if paciente_id:
            return Paciente.objects.filter(clinica=clinica, id=paciente_id).first()

        if paciente_uuid:
            return Paciente.objects.filter(clinica=clinica, uuid=paciente_uuid).first()

        return None

    def create(self, validated_data):
        paciente_data = validated_data.pop("paciente", {})
        clinica = self.context["clinica"]
        paciente = self._resolver_paciente_existente(clinica, paciente_data)

        if not paciente:
            paciente = Paciente.objects.create(
                clinica=clinica,
                nombres=paciente_data.get("nombres", "").strip(),
                apellido_pat=paciente_data.get("apellido_pat", "").strip(),
                apellido_mat=paciente_data.get("apellido_mat", "").strip(),
                fecha_nac=paciente_data.get("fecha_nac"),
                genero=paciente_data.get("genero", "").strip(),
                telefono=paciente_data.get("telefono", "").strip(),
                correo=paciente_data.get("correo", "").strip(),
                molestia=paciente_data.get("molestia", "").strip(),
                notas=paciente_data.get("notas", "").strip(),
            )

        return Cita.objects.create(paciente=paciente, **validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return ocultar_dinero_segun_rol(self, data)


class BloqueoHorarioSerializer(serializers.ModelSerializer):
    profesional_nombre = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BloqueoHorario
        fields = [
            "id",
            "profesional",
            "profesional_nombre",
            "fecha",
            "hora_inicio",
            "hora_termina",
            "motivo",
            "creado",
        ]

    def get_profesional_nombre(self, obj):
        u = obj.profesional
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return full or u.username


