# core/auth.py
from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        login = attrs.get("username")
        password = attrs.get("password")

        user = User.objects.filter(Q(username__iexact=login) | Q(email__iexact=login)).first()
        if not user or not user.check_password(password):
            raise AuthenticationFailed("Credenciales inválidas")

        self.user = user
        return super().validate({"username": user.username, "password": password})
