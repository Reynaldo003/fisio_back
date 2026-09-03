from django.contrib.auth.models import User
from rest_framework import serializers

from core.models import RolPersonalizado, StaffProfile
from core.utilidades import INTERFACES_SISTEMA, interfaces_usuario, permisos_usuario, rol_usuario


class RolPersonalizadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolPersonalizado
        fields = [
            "id", "slug", "nombre", "descripcion", "puede_ver_agenda", "puede_ver_pacientes",
            "puede_ver_contacto_paciente", "puede_ver_montos", "puede_modificar_montos", "puede_ver_finanzas",
            "puede_ver_servicios", "puede_ver_comentarios", "puede_ver_equipo", "puede_editar_equipo",
            "puede_ver_insumos", "puede_editar_insumos", "puede_ver_perfil", "interfaces", "activo", "creado", "actualizado",
        ]
        read_only_fields = ["id", "creado", "actualizado"]

    def validate_interfaces(self, value):
        invalidas = [item for item in value if item not in INTERFACES_SISTEMA]
        if invalidas:
            raise serializers.ValidationError(f"Interfaces inválidas: {', '.join(invalidas)}")
        return list(dict.fromkeys(value))


class StaffUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    rol = serializers.CharField(write_only=True, required=False)
    rol_personalizado = serializers.PrimaryKeyRelatedField(queryset=RolPersonalizado.objects.filter(activo=True), write_only=True, required=False, allow_null=True)
    telefono = serializers.CharField(write_only=True, required=False, allow_blank=True)
    descripcion = serializers.CharField(write_only=True, required=False, allow_blank=True)
    foto = serializers.ImageField(write_only=True, required=False, allow_null=True)
    usar_interfaces_override = serializers.BooleanField(write_only=True, required=False)
    interfaces_override = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)

    rol_out = serializers.SerializerMethodField(read_only=True)
    rol_base_out = serializers.SerializerMethodField(read_only=True)
    rol_personalizado_out = serializers.SerializerMethodField(read_only=True)
    telefono_out = serializers.SerializerMethodField(read_only=True)
    descripcion_out = serializers.SerializerMethodField(read_only=True)
    foto_url = serializers.SerializerMethodField(read_only=True)
    interfaces_out = serializers.SerializerMethodField(read_only=True)
    interfaces_override_out = serializers.SerializerMethodField(read_only=True)
    usar_interfaces_override_out = serializers.SerializerMethodField(read_only=True)
    permisos_out = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email", "password", "rol", "rol_personalizado",
            "telefono", "descripcion", "foto", "usar_interfaces_override", "interfaces_override", "rol_out", "rol_base_out",
            "rol_personalizado_out", "telefono_out", "descripcion_out", "foto_url", "interfaces_out", "interfaces_override_out",
            "usar_interfaces_override_out", "permisos_out", "is_active",
        ]

    def get_profile(self, obj):
        return getattr(obj, "staff_profile", None)

    def get_foto_url(self, obj):
        request = self.context.get("request")
        profile = self.get_profile(obj)
        if not profile or not profile.foto:
            return None
        return request.build_absolute_uri(profile.foto.url) if request else profile.foto.url

    def get_rol_out(self, obj):
        return rol_usuario(obj)

    def get_rol_base_out(self, obj):
        profile = self.get_profile(obj)
        return profile.rol if profile else None

    def get_rol_personalizado_out(self, obj):
        profile = self.get_profile(obj)
        if not profile or not profile.rol_personalizado_id:
            return None
        rol = profile.rol_personalizado
        return {"id": rol.id, "slug": rol.slug, "nombre": rol.nombre}

    def get_telefono_out(self, obj):
        profile = self.get_profile(obj)
        return profile.telefono if profile else ""

    def get_descripcion_out(self, obj):
        profile = self.get_profile(obj)
        return profile.descripcion if profile else ""

    def get_interfaces_out(self, obj):
        return interfaces_usuario(obj)

    def get_interfaces_override_out(self, obj):
        profile = self.get_profile(obj)
        return list(profile.interfaces_override or []) if profile else []

    def get_usar_interfaces_override_out(self, obj):
        profile = self.get_profile(obj)
        return bool(profile.usar_interfaces_override) if profile else False

    def get_permisos_out(self, obj):
        return permisos_usuario(obj)

    def validate(self, attrs):
        if self.instance is None:
            password = attrs.get("password") or ""
            if len(password) < 6:
                raise serializers.ValidationError({"password": "La contraseña debe tener al menos 6 caracteres."})
            if not attrs.get("email"):
                raise serializers.ValidationError({"email": "Email requerido."})
            if not attrs.get("username"):
                raise serializers.ValidationError({"username": "Usuario requerido."})
        interfaces = attrs.get("interfaces_override")
        if interfaces is not None:
            invalidas = [item for item in interfaces if item not in INTERFACES_SISTEMA]
            if invalidas:
                raise serializers.ValidationError({"interfaces_override": f"Interfaces inválidas: {', '.join(invalidas)}"})
        rol = attrs.get("rol")
        rol_personalizado = attrs.get("rol_personalizado")
        if rol == "personalizado" and not rol_personalizado and not getattr(getattr(self.instance, "staff_profile", None), "rol_personalizado_id", None):
            raise serializers.ValidationError({"rol_personalizado": "Selecciona un rol personalizado."})
        return attrs

    def _extraer_profile(self, validated_data):
        keys = ["rol", "rol_personalizado", "telefono", "descripcion", "foto", "usar_interfaces_override", "interfaces_override"]
        return {key: validated_data.pop(key) for key in keys if key in validated_data}

    def _guardar_profile(self, user, extra):
        profile, _ = StaffProfile.objects.get_or_create(user=user)
        for key in ["rol", "telefono", "descripcion", "foto", "usar_interfaces_override", "interfaces_override"]:
            if key in extra:
                setattr(profile, key, extra[key])
        if "rol_personalizado" in extra:
            profile.rol_personalizado = extra["rol_personalizado"]
        if profile.rol != "personalizado":
            profile.rol_personalizado = None
        profile.save()
        user.is_staff = bool(user.is_superuser or profile.rol == "admin")
        user.save(update_fields=["is_staff"])

    def create(self, validated_data):
        extra = self._extraer_profile(validated_data)
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        self._guardar_profile(user, extra)
        return user

    def update(self, instance, validated_data):
        extra = self._extraer_profile(validated_data)
        password = validated_data.pop("password", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        self._guardar_profile(instance, extra)
        return instance


class UserSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    permisos = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "email", "rol", "permisos"]

    def get_full_name(self, obj):
        return (obj.get_full_name() or "").strip() or obj.username

    def get_rol(self, obj):
        return rol_usuario(obj)

    def get_permisos(self, obj):
        return permisos_usuario(obj)
