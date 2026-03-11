# core/views.py
from datetime import datetime, timedelta
from io import BytesIO
import unicodedata

from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db import models
from decimal import Decimal
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponse
from email.message import EmailMessage
import smtplib

from rest_framework import permissions, viewsets, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from .models import Paciente, Comentario, Cita, Servicio, Clinica, Pago, StaffProfile,BloqueoHorario
from .serializers import (
    PacienteSerializer,
    ComentarioSerializer,
    ComentarioPublicSerializer,
    CitaSerializer,
    ServicioSerializer,
    UserSerializer,
    CitaCreateSerializer,
    PagoSerializer,
    StaffUserSerializer,
    BloqueoHorarioSerializer,
)
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .permissions import IsAdminUserStrict
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.db.models import Q

# =========================
# Helpers
# =========================
PUBLIC_DEFAULT_PRO_NAME = "l.f.t edgar mauricio medina cruz"


def _normalize_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # quita acentos
    s = " ".join(s.split())
    return s

def _normalize_phone(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _full_name_paciente(paciente: Paciente) -> str:
    return " ".join(
        part.strip()
        for part in [paciente.nombres, paciente.apellido_pat, paciente.apellido_mat]
        if (part or "").strip()
    ).strip()

def _buscar_paciente_publico_similar(*, clinica: Clinica, nombre: str, telefono: str):
    nombre_norm = _normalize_name(nombre)
    telefono_norm = _normalize_phone(telefono)

    if not nombre_norm or not telefono_norm:
        return None

    candidatos = Paciente.objects.filter(clinica=clinica).only(
        "id",
        "nombres",
        "apellido_pat",
        "apellido_mat",
        "telefono",
    )

    for paciente in candidatos:
        tel_actual = _normalize_phone(paciente.telefono)
        if tel_actual != telefono_norm:
            continue

        nombre_completo = _normalize_name(_full_name_paciente(paciente))
        solo_nombres = _normalize_name(paciente.nombres)

        if nombre_completo == nombre_norm or solo_nombres == nombre_norm:
            return paciente

    return None

def _user_role(user):
    if not user or not user.is_authenticated:
        return None

    sp = getattr(user, "staff_profile", None)
    if sp and sp.rol:
        return sp.rol

    if user.is_superuser or user.is_staff:
        return "admin"
    return "colaborador"


def _is_admin_like(role: str) -> bool:
    return role in ("admin",)


def _can_see_all_agendas(role: str) -> bool:
    return role in ("admin", "recepcion")


def _is_professional_role(role: str) -> bool:
    return role in ("fisioterapeuta", "nutriologo", "dentista")


def _first_clinica():
    return Clinica.objects.first()


def _calc_hora_termina(fecha_str, hora_inicio_str, duracion_td):
    dt = datetime.fromisoformat(f"{fecha_str}T{hora_inicio_str}")
    dt_end = dt + (duracion_td or timedelta(minutes=60))
    return dt_end.time()


def _overlaps(startA, endA, startB, endB):
    return startA < endB and startB < endA


def _validar_conflicto_cita(*, profesional_id, fecha, hora_inicio, hora_termina, exclude_id=None):
    qs = Cita.objects.filter(
        profesional_id=profesional_id,
        fecha=fecha,
    ).exclude(estado="cancelado")

    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    for c in qs.only("hora_inicio", "hora_termina"):
        if _overlaps(hora_inicio, hora_termina, c.hora_inicio, c.hora_termina):
            return True
    return False


def _default_public_professional(clinica: Clinica):
    """
    Regresa el usuario profesional default para la agenda pública.
    Reglas:
    1) Buscar un usuario activo con StaffProfile cuyo nombre completo normalizado sea
       "edgar mauricio medina cruz".
    2) Si no existe, fallback a clinica.propietario (como antes).
    """
    target = _normalize_name(PUBLIC_DEFAULT_PRO_NAME)

    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("id")

    # dataset pequeño => lo hacemos en Python para que sea robusto (acentos/espacios)
    for u in qs:
        full = _normalize_name(f"{u.first_name} {u.last_name}")
        if full == target:
            return u

        # fallback extra: si el username ya trae el nombre
        if _normalize_name(u.username) == target:
            return u

    return getattr(clinica, "propietario", None)


# =========================
# Public / Staff endpoints
# =========================
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_team(request):
    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("-id")
    ser = StaffUserSerializer(qs, many=True, context={"request": request})
    return Response(ser.data)


class StaffUserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = StaffUserSerializer
    permission_classes = [IsAdminUserStrict]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return User.objects.filter(staff_profile__isnull=False).order_by("-id")


class ProfesionalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by(
        "first_name", "last_name", "username"
    )
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


class PacienteViewSet(viewsets.ModelViewSet):
    serializer_class = PacienteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = Paciente.objects.all()

        if _is_professional_role(role):
            qs = qs.filter(citas__profesional=self.request.user).distinct()

        return qs


class ComentarioViewSet(viewsets.ModelViewSet):
    queryset = Comentario.objects.all()

    def get_permissions(self):
        if self.action in ["create", "public_list"]:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "public_list":
            return ComentarioPublicSerializer
        return ComentarioSerializer

    def perform_create(self, serializer):
        serializer.save(aprobado=False, clinica=_first_clinica())

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny])
    def public_list(self, request):
        queryset = Comentario.objects.filter(aprobado=True).order_by("-creado")[:20]
        serializer = ComentarioPublicSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def pending(self, request):
        qs = Comentario.objects.filter(aprobado=False).order_by("-creado")
        ser = ComentarioSerializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=["patch"], permission_classes=[permissions.IsAuthenticated])
    def moderate(self, request, pk=None):
        obj = self.get_object()
        estado = (request.data.get("estado") or "").lower().strip()

        if estado == "aprobado":
            obj.aprobado = True
            obj.save(update_fields=["aprobado"])
            return Response(ComentarioSerializer(obj).data)

        if estado == "rechazado":
            obj.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response({"detail": "estado inválido. Usa 'aprobado' o 'rechazado'."}, status=400)

# core/views.py (fragmento: dentro de CitaViewSet)
from rest_framework.exceptions import ValidationError

class CitaViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = Cita.objects.select_related("paciente", "servicio", "profesional").order_by("fecha", "hora_inicio")
        if _is_professional_role(role):
            qs = qs.filter(profesional=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            data = self.request.data
            if isinstance(data.get("paciente"), dict):
                return CitaCreateSerializer
        return CitaSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["clinica"] = _first_clinica()
        return ctx

    def perform_create(self, serializer):
        data = self.request.data
        role = _user_role(self.request.user)

        servicio_id = data.get("servicio") or data.get("servicio_id")
        servicio = Servicio.objects.filter(id=servicio_id).first()

        fecha = data.get("fecha")
        hora_inicio = data.get("hora_inicio")
        hora_termina = data.get("hora_termina")

        if hora_inicio and len(hora_inicio) == 5:
            hora_inicio = f"{hora_inicio}:00"
        if hora_termina and len(hora_termina) == 5:
            hora_termina = f"{hora_termina}:00"

        if not hora_termina and servicio and fecha and hora_inicio:
            ht = _calc_hora_termina(fecha, hora_inicio, servicio.duracion)
            hora_termina = ht.strftime("%H:%M:%S")

        profesional_id_payload = data.get("profesional")
        if _can_see_all_agendas(role) and profesional_id_payload:
            profesional_id = int(profesional_id_payload)
        else:
            profesional_id = self.request.user.id

        profesional_obj = User.objects.filter(id=profesional_id).first()
        if not profesional_obj:
            raise ValidationError({"profesional": "Profesional inválido."})

        # ✅ HORA COMPARTIDA: NO VALIDAR CONFLICTO (permitimos múltiples citas en el mismo rango)
        serializer.save(profesional=profesional_obj)

    def perform_update(self, serializer):
        data = self.request.data
        role = _user_role(self.request.user)

        profesional_id_payload = data.get("profesional")
        if _can_see_all_agendas(role) and profesional_id_payload:
            profesional_obj = User.objects.filter(id=int(profesional_id_payload)).first()
            if not profesional_obj:
                raise ValidationError({"profesional": "Profesional inválido."})
            serializer.save(profesional=profesional_obj)
            return

        # profesional no admin-like: no permitir cambiar profesional
        serializer.save()

    def update(self, request, *args, **kwargs):
        partial = True
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            self.perform_update(serializer)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except Exception as exc:
            print("[CITAS] Error al eliminar cita:", repr(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServicioViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Servicio.objects.filter(activo=True)
    serializer_class = ServicioSerializer
    permission_classes = [permissions.AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


class PagoViewSet(viewsets.ModelViewSet):
    queryset = (
        Pago.objects.select_related("cita", "cita__paciente", "cita__servicio", "cita__profesional")
        .all()
        .order_by("-fecha_pago", "-id")
    )
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = super().get_queryset()

        if _is_professional_role(role):
            qs = qs.filter(cita__profesional=self.request.user)

        cita_id = self.request.query_params.get("cita")
        if cita_id:
            qs = qs.filter(cita_id=cita_id)

        return qs

    def _recalcular_cita(self, cita):
        from decimal import Decimal
        from django.db.models import Sum

        pagos_qs = cita.pagos.all()

        total_pagado = pagos_qs.aggregate(total=Sum("anticipo")).get("total") or Decimal("0")

        pago_base = pagos_qs.order_by("-fecha_pago", "-id").first()

        if pago_base:
            monto_facturado = Decimal(pago_base.monto_facturado or 0)
            descuento_porcentaje = Decimal(pago_base.descuento_porcentaje or 0)
        else:
            monto_facturado = Decimal(cita.monto_final or cita.precio or 0)
            descuento_porcentaje = Decimal(cita.descuento_porcentaje or 0)

        descuento_monto = (monto_facturado * descuento_porcentaje) / Decimal("100")
        total_con_descuento = max(monto_facturado - descuento_monto, Decimal("0"))
        restante = max(total_con_descuento - total_pagado, Decimal("0"))

        cita.descuento_porcentaje = descuento_porcentaje
        cita.monto_final = total_con_descuento
        cita.anticipo = total_pagado
        cita.pagado = restante <= 0 and total_con_descuento > 0
        cita.save(
            update_fields=[
                "descuento_porcentaje",
                "monto_final",
                "anticipo",
                "pagado",
                "actualizado",
            ]
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        cita = getattr(instance, "cita", None)

        instance.delete()

        if cita:
            try:
                self._recalcular_cita(cita)
            except Exception as exc:
                print("[PAGOS] Error recalculando cita tras eliminar pago:", repr(exc))

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="ticket", permission_classes=[IsAuthenticated])
    def ticket_pdf(self, request, pk=None):
        pago = self.get_object()
        cita = pago.cita
        clinica = _first_clinica()

        RFC_FIJO = "MECE000513F74"

        def media_path(filename: str):
            try:
                return (settings.MEDIA_ROOT / filename) if hasattr(settings, "MEDIA_ROOT") else None
            except Exception:
                return None

        logo_path = media_path("fisionerv.png")
        qr_path = media_path("qr.png")

        def up(s: str) -> str:
            return (s or "").strip().upper()

        def safe_str(s) -> str:
            return (s or "").strip()

        def money(x) -> str:
            try:
                v = Decimal(x or 0)
                return f"$ {v:,.2f}".upper()
            except Exception:
                return "$ 0.00"

        def split_chunks(text: str, width_chars: int):
            t = up(text)
            if not t:
                return []
            out = []
            while len(t) > width_chars:
                out.append(t[:width_chars])
                t = t[width_chars:]
            if t:
                out.append(t)
            return out

        def draw_center(c, y, text, font="Helvetica", size=8.5):
            c.setFont(font, size)
            t = up(text)
            w = c.stringWidth(t, font, size)
            x = (ticket_width - w) / 2
            c.drawString(max(2 * mm, x), y, t)

        def draw_lr(c, y, left, right, font="Helvetica", size=8.5):
            c.setFont(font, size)
            l = up(left)
            r = up(right)

            x_left = 4 * mm
            x_right = ticket_width - 4 * mm

            c.drawString(x_left, y, l)

            rw = c.stringWidth(r, font, size)
            c.drawString(x_right - rw, y, r)

        negocio = safe_str(getattr(clinica, "nombre", "")) or "FISIONERV"
        direccion = safe_str(getattr(clinica, "direccion", "")) or "DIRECCION NO CONFIGURADA"

        paciente = cita.paciente
        paciente_nombre = f"{paciente.nombres} {paciente.apellido_pat} {paciente.apellido_mat or ''}".strip()

        prof = cita.profesional
        prof_nombre = (f"{prof.first_name or ''} {prof.last_name or ''}".strip() or prof.username)

        costo_servicio = Decimal(cita.precio or 0)
        monto_facturado = Decimal(cita.monto_final or 0) if Decimal(cita.monto_final or 0) > 0 else Decimal(pago.monto_facturado or 0)

        descuento_pct = Decimal(cita.descuento_porcentaje or 0)
        base_desc = Decimal(pago.monto_facturado or costo_servicio)
        descuento_monto = (base_desc * descuento_pct) / Decimal("100")

        total_a_pagar = Decimal(cita.monto_final or 0)
        if total_a_pagar <= 0:
            total_a_pagar = max(base_desc - descuento_monto, Decimal("0"))

        pagos_qs = cita.pagos.all()
        total_pagado = pagos_qs.aggregate(total=models.Sum("anticipo")).get("total") or Decimal("0")
        restante = max(total_a_pagar - Decimal(total_pagado), Decimal("0"))

        by_method = (
            pagos_qs.values("metodo_pago")
            .annotate(total=models.Sum("anticipo"))
            .order_by("metodo_pago")
        )

        #now = timezone.localtime(timezone.now())
        now = timezone.now()
        fecha_emision = now.strftime("%Y-%m-%d")
        hora_emision = now.strftime("%H:%M:%S")

        venta_no = f"{cita.id}"
        ticket_no = f"{pago.id}"

        servicio_nombre = safe_str(getattr(cita.servicio, "nombre", "")) or "SERVICIO"

        ticket_width = 80 * mm
        line_h = 4.0 * mm
        top_pad = 8 * mm
        bottom_pad = 8 * mm

        sep = "-" * 32

        header_lines = []
        header_lines.append(up(negocio))
        header_lines.append(up(f"RFC: {RFC_FIJO}"))
        header_lines += split_chunks(direccion, 32)

        ticket_info_lines = [
            up(f"VENTA: {venta_no}  TICKET: {ticket_no}"),
            up(f"EMISION: {fecha_emision} {hora_emision}"),
        ]

        cliente_lines = [up("CLIENTE")] + split_chunks(paciente_nombre, 32)
        prof_lines = [up("PROFESIONAL")] + split_chunks(prof_nombre, 32)

        pagos_lines = []
        if by_method:
            for row in by_method:
                mp = (row.get("metodo_pago") or "otro").strip()
                mp_label = {
                    "efectivo": "EFECTIVO",
                    "tarjeta": "TARJETA",
                    "transferencia": "TRANSFERENCIA",
                    "otro": "OTRO",
                }.get(mp, up(mp))
                pagos_lines.append(mp_label)
        else:
            pagos_lines.append("SIN PAGOS REGISTRADOS")

        footer_lines = [
            up(sep),
            up("GRACIAS POR SU PREFERENCIA"),
            up("DOCUMENTO GENERADO POR EL SISTEMA"),
        ]

        qr_h = 0
        qr_w = 0
        has_qr = False
        if qr_path:
            try:
                import os
                if os.path.exists(str(qr_path)):
                    has_qr = True
                    qr_w = 18 * mm
                    qr_h = 18 * mm
            except Exception:
                has_qr = False

        logo_h = 0
        has_logo = False
        if logo_path:
            try:
                import os
                if os.path.exists(str(logo_path)):
                    has_logo = True
                    logo_h = 18 * mm
            except Exception:
                has_logo = False

        total_text_lines = (
            len(header_lines)
            + 1
            + len(ticket_info_lines)
            + 1
            + len(cliente_lines)
            + len(prof_lines)
            + 1
            + 1
            + 1
            + 1
            + 3
            + 1
            + 3
            + 1
            + 1
            + max(1, len(pagos_lines))
            + len(footer_lines)
        )

        height = top_pad + bottom_pad + (total_text_lines * line_h) + logo_h + (qr_h if has_qr else 0) + (6 * mm)

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(ticket_width, height))

        y = height - top_pad

        if has_logo:
            try:
                img = ImageReader(str(logo_path))
                draw_w = 60 * mm
                draw_h = 18 * mm
                x = (ticket_width - draw_w) / 2
                c.drawImage(img, x, y - draw_h, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
                y -= (draw_h + 3 * mm)
            except Exception:
                pass

        c.setFont("Helvetica", 8.5)

        draw_center(c, y, negocio, "Helvetica-Bold", 9)
        y -= line_h

        draw_center(c, y, f"RFC: {RFC_FIJO}", "Helvetica", 8.5)
        y -= line_h

        for line in split_chunks(direccion, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, f"VENTA: {venta_no}  TICKET: {ticket_no}", "Helvetica", 8.5)
        y -= line_h
        draw_center(c, y, f"EMISION: {fecha_emision} {hora_emision}", "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, "CLIENTE", "Helvetica-Bold", 8.5)
        y -= line_h
        for line in split_chunks(paciente_nombre, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        y -= (1 * mm)

        draw_center(c, y, "PROFESIONAL", "Helvetica-Bold", 8.5)
        y -= line_h
        for line in split_chunks(prof_nombre, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, "DETALLE", "Helvetica-Bold", 8.5)
        y -= line_h

        for line in split_chunks(servicio_nombre[:64], 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_lr(c, y, "COSTO", money(costo_servicio))
        y -= line_h
        draw_lr(c, y, f"DESC ({descuento_pct}%)", f"-{money(descuento_monto)}")
        y -= line_h
        draw_lr(c, y, "MONTO FACTURADO", money(monto_facturado))
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_lr(c, y, "TOTAL A PAGAR", money(total_a_pagar))
        y -= line_h
        draw_lr(c, y, "COBRADO", money(total_pagado))
        y -= line_h
        draw_lr(c, y, "RESTANTE", money(restante))
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, "PAGOS POR METODO", "Helvetica-Bold", 8.5)
        y -= line_h

        if by_method:
            for row in by_method:
                mp = (row.get("metodo_pago") or "otro").strip()
                tot = row.get("total") or 0
                mp_label = {
                    "efectivo": "EFECTIVO",
                    "tarjeta": "TARJETA",
                    "transferencia": "TRANSFERENCIA",
                    "otro": "OTRO",
                }.get(mp, up(mp))

                draw_lr(c, y, mp_label, money(tot))
                y -= line_h
        else:
            draw_center(c, y, "SIN PAGOS REGISTRADOS", "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, "GRACIAS POR SU PREFERENCIA", "Helvetica-Bold", 8.5)
        y -= line_h
        draw_center(c, y, "DOCUMENTO GENERADO POR EL SISTEMA", "Helvetica", 8.0)
        y -= line_h

        if has_qr:
            try:
                img_qr = ImageReader(str(qr_path))
                x_qr = ticket_width - 4 * mm - qr_w
                y_qr = 4 * mm
                c.drawImage(img_qr, x_qr, y_qr, width=qr_w, height=qr_h, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass

        c.showPage()
        c.save()

        pdf = buffer.getvalue()
        buffer.close()

        filename = f"TICKET_VENTA_{venta_no}_PAGO_{ticket_no}.PDF"
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    @action(detail=False, methods=["delete"], url_path=r"by-cita/(?P<cita_id>\d+)")
    def delete_by_cita(self, request, cita_id=None):
        """
        DELETE /api/pagos/by-cita/<cita_id>/
        Borra TODOS los pagos de la cita, pero NO borra la cita.
        """
        cita = Cita.objects.filter(id=cita_id).first()
        if not cita:
            return Response(status=status.HTTP_204_NO_CONTENT)

        try:
            cita.pagos.all().delete()
            self._recalcular_cita(cita)
        except Exception as exc:
            print("[PAGOS] Error borrando pagos por cita:", repr(exc))
            return Response({"detail": "No se pudo eliminar."}, status=400)

        return Response(status=status.HTTP_204_NO_CONTENT)
        
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_agenda(request):
    fecha = request.query_params.get("fecha")
    if not fecha:
        return Response({"detail": "fecha requerida"}, status=400)

    clinica = _first_clinica()
    if not clinica:
        return Response({"detail": "No existe clínica configurada."}, status=400)

    profesional = _default_public_professional(clinica)
    if not profesional:
        return Response({"detail": "No hay profesional configurado."}, status=400)

    qs_citas = (
        Cita.objects.filter(fecha=fecha, profesional=profesional)
        .exclude(estado="cancelado")
        .only("hora_inicio", "hora_termina")
    )

    qs_bloq = (
        BloqueoHorario.objects.filter(fecha=fecha, profesional=profesional)
        .only("hora_inicio", "hora_termina")
    )

    data = []
    for c in qs_citas:
        data.append(
            {
                "hora_inicio": c.hora_inicio.strftime("%H:%M:%S"),
                "hora_termina": c.hora_termina.strftime("%H:%M:%S"),
                "kind": "cita",
            }
        )
    for b in qs_bloq:
        data.append(
            {
                "hora_inicio": b.hora_inicio.strftime("%H:%M:%S"),
                "hora_termina": b.hora_termina.strftime("%H:%M:%S"),
                "kind": "bloqueo",
            }
        )

    return Response(data)

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def public_create_cita(request):
    clinica = _first_clinica()
    if not clinica:
        return Response({"detail": "No existe clínica configurada."}, status=400)

    nombre = (request.data.get("nombre") or "").strip()
    telefono = (request.data.get("telefono") or "").strip()
    servicio_id = request.data.get("servicio_id")
    fecha = request.data.get("fecha")
    hora_inicio = request.data.get("hora_inicio")

    if not (nombre and telefono and servicio_id and fecha and hora_inicio):
        return Response({"detail": "Faltan campos requeridos."}, status=400)

    servicio = Servicio.objects.filter(id=servicio_id, activo=True).first()
    if not servicio:
        return Response({"detail": "Servicio inválido."}, status=400)

    hora_inicio_full = f"{hora_inicio}:00" if len(hora_inicio) == 5 else hora_inicio

    paciente = _buscar_paciente_publico_similar(
        clinica=clinica,
        nombre=nombre,
        telefono=telefono,
    )

    if not paciente:
        paciente = Paciente.objects.create(
            clinica=clinica,
            nombres=nombre,
            apellido_pat="",
            apellido_mat="",
            fecha_nac=None,
            genero="",
            telefono=telefono,
            correo="",
            molestia="",
            notas="",
        )

    profesional = _default_public_professional(clinica)
    if not profesional:
        return Response({"detail": "No hay profesional configurado."}, status=400)

    hora_termina = _calc_hora_termina(
        fecha,
        hora_inicio_full,
        servicio.duracion,
    ).strftime("%H:%M:%S")

    hi = datetime.strptime(hora_inicio_full, "%H:%M:%S").time()
    ht = datetime.strptime(hora_termina, "%H:%M:%S").time()

    if _validar_conflicto_cita(
        profesional_id=profesional.id,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
        exclude_id=None,
    ):
        return Response({"detail": "Horario ya ocupado."}, status=409)

    bloqs = BloqueoHorario.objects.filter(
        fecha=fecha,
        profesional=profesional,
    ).only("hora_inicio", "hora_termina")

    for b in bloqs:
        if _overlaps(hi, ht, b.hora_inicio, b.hora_termina):
            return Response({"detail": "Horario no disponible."}, status=409)

    cita = Cita.objects.create(
        paciente=paciente,
        servicio=servicio,
        profesional=profesional,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
        precio=servicio.precio,
        estado="reservado",
        pagado=False,
    )

    return Response(CitaSerializer(cita).data, status=201)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    role = _user_role(u)
    full_name = (u.get_full_name() or "").strip() or u.username
    return Response(
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": full_name,
            "rol": role,
        }
    )

class BloqueoHorarioViewSet(viewsets.ModelViewSet):
    queryset = BloqueoHorario.objects.select_related("profesional").all()
    serializer_class = BloqueoHorarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = super().get_queryset()

        # Profesional solo ve sus bloqueos
        if _is_professional_role(role):
            qs = qs.filter(profesional=self.request.user)

        return qs

class ServicioAdminViewSet(viewsets.ModelViewSet):
    serializer_class = ServicioSerializer
    permission_classes = [IsAdminUserStrict]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        # Admin ve todo (activos e inactivos)
        return Servicio.objects.all().order_by("-id")

    def perform_create(self, serializer):
        clinica = _first_clinica()
        if not clinica:
            raise ValidationError({"detail": "No existe clínica configurada."})
        serializer.save(clinica=clinica)

import re
from rest_framework.parsers import MultiPartParser, FormParser

def _password_fuerte(pw: str) -> bool:
    if not pw or len(pw) < 8:
        return False
    if not re.search(r"[A-Z]", pw):
        return False
    if not re.search(r"[a-z]", pw):
        return False
    if not re.search(r"[0-9]", pw):
        return False
    if not re.search(r"[^A-Za-z0-9]", pw):
        return False
    return True

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def me_update(request):
    """
    Actualiza datos del usuario en sesión:
    - username, first_name, last_name, email
    - foto (StaffProfile)
    - cambio de contraseña opcional:
        requiere current_password + new_password fuerte
    """
    u = request.user

    username = (request.data.get("username") or "").strip()
    first_name = (request.data.get("first_name") or "").strip()
    last_name = (request.data.get("last_name") or "").strip()
    email = (request.data.get("email") or "").strip()

    if not username:
        return Response({"detail": "username requerido."}, status=400)
    if not email:
        return Response({"detail": "email requerido."}, status=400)

    # ✅ si manda new_password, aplicar validación fuerte
    new_password = request.data.get("new_password") or ""
    current_password = request.data.get("current_password") or ""

    if new_password:
        if not current_password:
            return Response({"detail": "Escribe tu contraseña actual para cambiarla."}, status=400)
        if not u.check_password(current_password):
            return Response({"detail": "La contraseña actual es incorrecta."}, status=400)
        if not _password_fuerte(new_password):
            return Response(
                {"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."},
                status=400,
            )
        u.set_password(new_password)

    u.username = username
    u.first_name = first_name
    u.last_name = last_name
    u.email = email
    u.save()

    # ✅ foto en StaffProfile (si existe)
    foto = request.FILES.get("foto", None)
    sp = getattr(u, "staff_profile", None)
    if sp and foto:
        sp.foto = foto
        sp.save(update_fields=["foto"])

    role = _user_role(u)
    full_name = (u.get_full_name() or "").strip() or u.username

    # devolvemos lo que usa tu front
    return Response(
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "full_name": full_name,
            "rol": role,
            "foto_url": (request.build_absolute_uri(sp.foto.url) if (sp and sp.foto) else None),
        }
    )
# =========================
# Password Reset (public)
# =========================

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_request(request):
    """
    POST { email_or_username }
    - Siempre responde 200 (aunque no exista) para no filtrar usuarios.
    - Si existe usuario con email válido, genera una contraseña temporal,
      la guarda y envía correo usando Gmail (SMTP).
    """
    val = (request.data.get("email_or_username") or "").strip()
    if not val:
        return Response({"detail": "email_or_username requerido."}, status=400)

    user = User.objects.filter(Q(email__iexact=val) | Q(username__iexact=val)).first()

    ok_msg = {"detail": "Si existe el usuario, se envió el correo."}
    if not user or not user.email:
        return Response(ok_msg, status=200)

    # 1) Generar password temporal
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    raw_password = "Temp-" + "".join(secrets.choice(alphabet) for _ in range(10))

    try:
        user.set_password(raw_password)
        user.save(update_fields=["password"])
    except Exception as exc:
        print("[PASSWORD RESET] Error guardando nueva contraseña:", repr(exc))
        return Response(ok_msg, status=200)

    # 2) Enviar correo por Gmail (SMTP)
    REMITENTE = "workflow2709@gmail.com"  # ✅ constante
    APP_PASSWORD = "gntx ppix dzkd cdxt"  # ✅ constante (App Password)

    destinatario = "rvallejo276@gmail.com"  # ✅ solo desde BD
    asunto = "Recuperación de contraseña - Fisionerv"
    mensaje = (
        "Se generó una contraseña temporal para tu cuenta.\n\n"
        f"Usuario: {user.username}\n"
        f"Contraseña temporal: {raw_password}\n\n"
        "Por seguridad, al iniciar sesión cámbiala desde tu perfil."
    )

    try:
        email = EmailMessage()
        email["From"] = REMITENTE
        email["To"] = destinatario
        email["Subject"] = asunto
        email.set_content(mensaje)

        smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp.login(REMITENTE, APP_PASSWORD)
        smtp.send_message(email)
        smtp.quit()
    except Exception as exc:
        print("[PASSWORD RESET] Error enviando email SMTP:", repr(exc))

    return Response(ok_msg, status=200)

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_confirm(request):
    uid = request.data.get("uid") or ""
    token = request.data.get("token") or ""
    new_password = request.data.get("new_password") or ""

    if not (uid and token and new_password):
        return Response({"detail": "uid, token y new_password requeridos."}, status=400)

    if not _password_fuerte(new_password):
        return Response(
            {"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."},
            status=400,
        )

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.filter(pk=user_id).first()
    except Exception:
        user = None

    if not user:
        return Response({"detail": "Token inválido."}, status=400)

    token_gen = PasswordResetTokenGenerator()
    if not token_gen.check_token(user, token):
        return Response({"detail": "Token inválido o expirado."}, status=400)

    user.set_password(new_password)
    user.save(update_fields=["password"])

    return Response({"detail": "Contraseña actualizada correctamente."}, status=200)