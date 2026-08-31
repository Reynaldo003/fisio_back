import secrets
import smtplib
import string
from email.message import EmailMessage
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db.models import Q
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from core.utilidades import password_fuerte


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_request(request):
    valor = (request.data.get("email_or_username") or "").strip()
    if not valor: return Response({"detail": "email_or_username requerido."}, status=400)
    user = User.objects.filter(Q(email__iexact=valor) | Q(username__iexact=valor)).first(); ok_msg = {"detail": "Si existe el usuario, se envió el correo."}
    if not user or not user.email: return Response(ok_msg, status=200)
    raw_password = "Temp-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    try: user.set_password(raw_password); user.save(update_fields=["password"])
    except Exception as exc: print("[PASSWORD RESET] Error guardando nueva contraseña:", repr(exc)); return Response(ok_msg, status=200)

    # Se conservan los valores actuales para no cambiar el comportamiento existente.
    # Recomendación posterior: moverlos a variables de entorno/settings y rotar la App Password.
    REMITENTE = "workflow2709@gmail.com"; APP_PASSWORD = "gntx ppix dzkd cdxt"; destinatario = "rvallejo276@gmail.com"
    asunto = "Recuperación de contraseña - Fisionerv"; mensaje = f"Se generó una contraseña temporal para tu cuenta.\n\nUsuario: {user.username}\nContraseña temporal: {raw_password}\n\nPor seguridad, al iniciar sesión cámbiala desde tu perfil."
    try:
        email = EmailMessage(); email["From"] = REMITENTE; email["To"] = destinatario; email["Subject"] = asunto; email.set_content(mensaje)
        smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465); smtp.login(REMITENTE, APP_PASSWORD); smtp.send_message(email); smtp.quit()
    except Exception as exc: print("[PASSWORD RESET] Error enviando email SMTP:", repr(exc))
    return Response(ok_msg, status=200)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_confirm(request):
    uid = request.data.get("uid") or ""; token = request.data.get("token") or ""; new_password = request.data.get("new_password") or ""
    if not (uid and token and new_password): return Response({"detail": "uid, token y new_password requeridos."}, status=400)
    if not password_fuerte(new_password): return Response({"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."}, status=400)
    try: user = User.objects.filter(pk=force_str(urlsafe_base64_decode(uid))).first()
    except Exception: user = None
    if not user: return Response({"detail": "Token inválido."}, status=400)
    if not PasswordResetTokenGenerator().check_token(user, token): return Response({"detail": "Token inválido o expirado."}, status=400)
    user.set_password(new_password); user.save(update_fields=["password"]); return Response({"detail": "Contraseña actualizada correctamente."}, status=200)
