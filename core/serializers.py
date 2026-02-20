# core/serializers.py
from django.contrib.auth.models import User
from django.db.models import Sum
from rest_framework import serializers
from .models import Clinica, Paciente, Comentario, Cita, Servicio, Pago, StaffProfile, BloqueoHorario

class StaffUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    rol = serializers.CharField(write_only=True, required=False)
    telefono = serializers.CharField(write_only=True, required=False, allow_blank=True)
    descripcion = serializers.CharField(write_only=True, required=False, allow_blank=True)
    foto = serializers.ImageField(write_only=True, required=False, allow_null=True)

    rol_out = serializers.SerializerMethodField(read_only=True)
    telefono_out = serializers.SerializerMethodField(read_only=True)
    descripcion_out = serializers.SerializerMethodField(read_only=True)
    foto_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "rol",
            "telefono",
            "descripcion",
            "foto",
            "rol_out",
            "telefono_out",
            "descripcion_out",
            "foto_url",
        ]

    def get_foto_url(self, obj):
        request = self.context.get("request")
        profile = getattr(obj, "staff_profile", None)
        if not profile or not profile.foto:
            return None
        return request.build_absolute_uri(profile.foto.url) if request else profile.foto.url

    def get_rol_out(self, obj):
        p = getattr(obj, "staff_profile", None)
        return p.rol if p else None

    def get_telefono_out(self, obj):
        p = getattr(obj, "staff_profile", None)
        return p.telefono if p else ""

    def get_descripcion_out(self, obj):
        p = getattr(obj, "staff_profile", None)
        return p.descripcion if p else ""

    def validate(self, attrs):
        if len(attrs.get("password", "")) < 6:
            raise serializers.ValidationError({"password": "La contraseña debe tener al menos 6 caracteres."})
        if not attrs.get("email"):
            raise serializers.ValidationError({"email": "Email requerido."})
        if not attrs.get("username"):
            raise serializers.ValidationError({"username": "Usuario requerido."})
        return attrs

    def create(self, validated_data):
        rol = validated_data.pop("rol", "fisioterapeuta")
        telefono = validated_data.pop("telefono", "")
        descripcion = validated_data.pop("descripcion", "")
        foto = validated_data.pop("foto", None)
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)

        if rol == "admin":
            user.is_staff = True

        user.save()

        StaffProfile.objects.create(
            user=user,
            rol=rol,
            telefono=telefono,
            descripcion=descripcion,
            foto=foto,
        )
        return user


class UserSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "email", "rol"]

    def get_full_name(self, obj):
        return (obj.get_full_name() or "").strip() or obj.username

    def get_rol(self, obj):
        sp = getattr(obj, "staff_profile", None)
        if sp and sp.rol:
            return sp.rol
        if obj.is_superuser or obj.is_staff:
            return "admin"
        return "colaborador"

class PacienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paciente
        fields = "__all__"


class PacienteInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paciente
        fields = [
            "nombres",
            "apellido_pat",
            "apellido_mat",
            "fecha_nac",
            "genero",
            "telefono",
            "correo",
            "molestia",
            "notas",
        ]


class ComentarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comentario
        fields = "__all__"
        read_only_fields = ["aprobado", "creado"]


class ComentarioPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comentario
        fields = ["id", "nombre_completo", "calificacion", "descripcion"]


class ServicioSerializer(serializers.ModelSerializer):
    imagen_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Servicio
        fields = "__all__"

    def get_imagen_url(self, obj):
        request = self.context.get("request")
        if not obj.imagen:
            return None
        url = obj.imagen.url
        return request.build_absolute_uri(url) if request else url
        #return request.build_absolute_uri(obj.imagen.url) if request else obj.imagen.url



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
        full = f"{p.nombres} {p.apellido_pat} {p.apellido_mat or ''}".strip()
        return full

    def get_profesional_nombre(self, obj):
        u = obj.profesional
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return full or u.username


# core/serializers.py  (solo la parte del CitaCreateSerializer)
class CitaCreateSerializer(serializers.ModelSerializer):
    paciente = PacienteInlineSerializer()

    class Meta:
        model = Cita
        fields = [
            "paciente",
            "servicio",
            "profesional",
            "fecha",
            "hora_inicio",
            "hora_termina",
            "precio",
            "metodo_pago",
            "estado",
            "notas",

            # ✅ IMPORTANTES para pagos
            "pagado",
            "descuento_porcentaje",
            "anticipo",
            "monto_final",
        ]

    def create(self, validated_data):
        paciente_data = validated_data.pop("paciente")
        telefono = paciente_data.get("telefono")
        correo = paciente_data.get("correo")
        clinica = self.context["clinica"]

        paciente, _ = Paciente.objects.get_or_create(
            clinica=clinica,
            telefono=telefono,
            defaults={
                "nombres": paciente_data.get("nombres", ""),
                "apellido_pat": paciente_data.get("apellido_pat", ""),
                "apellido_mat": paciente_data.get("apellido_mat", ""),
                "fecha_nac": paciente_data.get("fecha_nac"),
                "genero": paciente_data.get("genero", ""),
                "correo": correo or "",
                "molestia": paciente_data.get("molestia", ""),
                "notas": paciente_data.get("notas", ""),
            },
        )
        return Cita.objects.create(paciente=paciente, **validated_data)

class PagoSerializer(serializers.ModelSerializer):
    paciente_nombre = serializers.SerializerMethodField(read_only=True)
    servicio_nombre = serializers.CharField(source="cita.servicio.nombre", read_only=True)

    profesional_id = serializers.IntegerField(source="cita.profesional_id", read_only=True)
    profesional_nombre = serializers.SerializerMethodField(read_only=True)

    fecha_cita = serializers.DateField(source="cita.fecha", read_only=True)
    restante = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = Pago
        fields = [
            "id",
            "cita",
            "fecha_pago",
            "comprobante",
            "monto_facturado",
            "metodo_pago",
            "descuento_porcentaje",
            "anticipo",
            "restante",

            # extras para Ventas
            "paciente_nombre",
            "servicio_nombre",
            "profesional_id",
            "profesional_nombre",
            "fecha_cita",
        ]
        extra_kwargs = {
            "comprobante": {"required": False, "allow_blank": True},
            "descuento_porcentaje": {"required": False},
            "anticipo": {"required": False},
        }

    def get_paciente_nombre(self, obj):
        p = obj.cita.paciente
        return f"{p.nombres} {p.apellido_pat} {p.apellido_mat or ''}".strip()

    def get_profesional_nombre(self, obj):
        u = obj.cita.profesional
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return full or u.username

    def _calcular_saldos(
        self,
        *,
        cita,
        monto_facturado,
        descuento_porcentaje,
        anticipo_nuevo,
        excluir=None,
    ):
        from decimal import Decimal

        monto = Decimal(monto_facturado or 0)
        desc_pct = Decimal(descuento_porcentaje or 0)
        anticipo_nuevo = Decimal(anticipo_nuevo or 0)

        desc_amount = (monto * desc_pct) / Decimal("100")
        total_con_descuento = max(monto - desc_amount, Decimal("0"))

        qs_prev = cita.pagos.all()
        if excluir is not None:
            qs_prev = qs_prev.exclude(pk=excluir.pk)

        total_pagado_prev = qs_prev.aggregate(total=Sum("anticipo")).get("total") or Decimal("0")
        total_pagado_actual = total_pagado_prev + anticipo_nuevo
        restante = max(total_con_descuento - total_pagado_actual, Decimal("0"))

        return restante, total_con_descuento, total_pagado_actual

    def _actualizar_campos_cita(
        self,
        *,
        cita,
        descuento_porcentaje,
        total_con_descuento,
        total_pagado_actual,
        restante,
    ):
        cita.descuento_porcentaje = descuento_porcentaje
        cita.monto_final = total_con_descuento
        cita.anticipo = total_pagado_actual
        cita.pagado = restante <= 0
        cita.save(
            update_fields=[
                "descuento_porcentaje",
                "monto_final",
                "anticipo",
                "pagado",
                "actualizado",
            ]
        )

    def create(self, validated_data):
        cita = validated_data["cita"]

        monto_facturado = validated_data.get("monto_facturado") or cita.precio
        descuento_porcentaje = validated_data.get("descuento_porcentaje", cita.descuento_porcentaje)
        anticipo = validated_data.get("anticipo") or 0

        restante, total_con_descuento, total_pagado_actual = self._calcular_saldos(
            cita=cita,
            monto_facturado=monto_facturado,
            descuento_porcentaje=descuento_porcentaje,
            anticipo_nuevo=anticipo,
        )

        validated_data["monto_facturado"] = monto_facturado
        validated_data["descuento_porcentaje"] = descuento_porcentaje
        validated_data["restante"] = restante

        pago = super().create(validated_data)

        self._actualizar_campos_cita(
            cita=cita,
            descuento_porcentaje=descuento_porcentaje,
            total_con_descuento=total_con_descuento,
            total_pagado_actual=total_pagado_actual,
            restante=restante,
        )

        return pago

    def update(self, instance, validated_data):
        cita = instance.cita

        monto_facturado = validated_data.get("monto_facturado", instance.monto_facturado)
        descuento_porcentaje = validated_data.get("descuento_porcentaje", instance.descuento_porcentaje)
        anticipo = validated_data.get("anticipo", instance.anticipo)

        restante, total_con_descuento, total_pagado_actual = self._calcular_saldos(
            cita=cita,
            monto_facturado=monto_facturado,
            descuento_porcentaje=descuento_porcentaje,
            anticipo_nuevo=anticipo,
            excluir=instance,
        )

        validated_data["restante"] = restante

        pago = super().update(instance, validated_data)

        self._actualizar_campos_cita(
            cita=cita,
            descuento_porcentaje=descuento_porcentaje,
            total_con_descuento=total_con_descuento,
            total_pagado_actual=total_pagado_actual,
            restante=restante,
        )

        return pago


class BloqueoHorarioSerializer(serializers.ModelSerializer):
    profesional_nombre = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BloqueoHorario
        fields = ["id", "profesional", "profesional_nombre", "fecha", "hora_inicio", "hora_termina", "motivo", "creado"]

    def get_profesional_nombre(self, obj):
        u = obj.profesional
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return full or u.username