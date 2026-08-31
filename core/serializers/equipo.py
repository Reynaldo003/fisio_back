from django.contrib.auth.models import User
from rest_framework import serializers
from core.models import StaffProfile


class StaffUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True); rol = serializers.CharField(write_only=True, required=False); telefono = serializers.CharField(write_only=True, required=False, allow_blank=True)
    descripcion = serializers.CharField(write_only=True, required=False, allow_blank=True); foto = serializers.ImageField(write_only=True, required=False, allow_null=True)
    rol_out = serializers.SerializerMethodField(read_only=True); telefono_out = serializers.SerializerMethodField(read_only=True); descripcion_out = serializers.SerializerMethodField(read_only=True); foto_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "password", "rol", "telefono", "descripcion", "foto", "rol_out", "telefono_out", "descripcion_out", "foto_url"]

    def get_foto_url(self, obj):
        request = self.context.get("request"); profile = getattr(obj, "staff_profile", None)
        if not profile or not profile.foto: return None
        return request.build_absolute_uri(profile.foto.url) if request else profile.foto.url

    def get_rol_out(self, obj):
        profile = getattr(obj, "staff_profile", None); return profile.rol if profile else None

    def get_telefono_out(self, obj):
        profile = getattr(obj, "staff_profile", None); return profile.telefono if profile else ""

    def get_descripcion_out(self, obj):
        profile = getattr(obj, "staff_profile", None); return profile.descripcion if profile else ""

    def validate(self, attrs):
        if len(attrs.get("password", "")) < 6: raise serializers.ValidationError({"password": "La contraseña debe tener al menos 6 caracteres."})
        if not attrs.get("email"): raise serializers.ValidationError({"email": "Email requerido."})
        if not attrs.get("username"): raise serializers.ValidationError({"username": "Usuario requerido."})
        return attrs

    def create(self, validated_data):
        rol = validated_data.pop("rol", "fisioterapeuta"); telefono = validated_data.pop("telefono", ""); descripcion = validated_data.pop("descripcion", ""); foto = validated_data.pop("foto", None); password = validated_data.pop("password")
        user = User(**validated_data); user.set_password(password); user.is_staff = rol == "admin" or user.is_staff; user.save()
        StaffProfile.objects.create(user=user, rol=rol, telefono=telefono, descripcion=descripcion, foto=foto)
        return user


class UserSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField(); full_name = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "email", "rol"]

    def get_full_name(self, obj): return (obj.get_full_name() or "").strip() or obj.username
    def get_rol(self, obj):
        profile = getattr(obj, "staff_profile", None)
        if profile and profile.rol: return profile.rol
        if obj.is_superuser or obj.is_staff: return "admin"
        return "colaborador"
