from datetime import date, datetime, timedelta

from django.db.models import Count, Sum, F, Case, When, DecimalField, Value
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.models import Paciente, Cita, Pago


def _parse_date(s, default=None):
    if not s:
        return default
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return default


def _get_trunc(group):
    if group == "day":
        return TruncDay
    if group == "week":
        return TruncWeek
    if group == "year":
        return TruncYear
    return TruncMonth


def _iso(d):
    if d is None:
        return None
    try:
        return d.date().isoformat()
    except Exception:
        return d.isoformat()


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def estadisticas(request):
    today = date.today()

    default_from = today.replace(day=1)
    default_to = today

    from_q = _parse_date(request.query_params.get("from"), default_from)
    to_q = _parse_date(request.query_params.get("to"), default_to)

    if from_q > to_q:
        from_q, to_q = to_q, from_q

    group = (request.query_params.get("group") or "month").strip().lower()
    if group not in ("day", "week", "month", "year"):
        group = "month"

    profesional_id = request.query_params.get("profesional")
    try:
        profesional_id = int(profesional_id) if profesional_id else None
    except Exception:
        profesional_id = None

    trunc = _get_trunc(group)

    # Citas: siguen por fecha de cita
    citas_base = Cita.objects.filter(fecha__range=(from_q, to_q))

    # ✅ Pagos: ahora sí por fecha de pago
    pagos_base = Pago.objects.filter(fecha_pago__range=(from_q, to_q))

    pacientes_base = Paciente.objects.all()

    if profesional_id:
        citas_base = citas_base.filter(profesional_id=profesional_id)
        pagos_base = pagos_base.filter(cita__profesional_id=profesional_id)

    attendance_series = (
        citas_base.filter(estado="completado")
        .annotate(period=trunc("fecha"))
        .values("period")
        .annotate(total=Count("id"))
        .order_by("period")
    )

    status_breakdown = (
        citas_base.values("estado")
        .annotate(count=Count("id"))
        .order_by("estado")
    )

    # ✅ Ventas por periodo usando fecha_pago
    sales_series = (
        pagos_base.annotate(period=trunc("fecha_pago"))
        .values("period")
        .annotate(total_pagos=Count("id"), total_cobrado=Sum("anticipo"))
        .order_by("period")
    )

    payments_by_method = (
        pagos_base.values("metodo_pago")
        .annotate(
            total=Sum("anticipo"),
            count=Count("id"),
        )
        .order_by("-total")
    )

    revenue_by_service = (
        pagos_base.values("cita__servicio__nombre")
        .annotate(total=Sum("anticipo"), count=Count("id"))
        .order_by("-total")
    )

    # ✅ Ingreso mensual por fecha_pago
    monthly_income = (
        pagos_base.annotate(period=TruncMonth("fecha_pago"))
        .values("period")
        .annotate(total=Sum("anticipo"))
        .order_by("period")
    )

    patient_status_totals = (
        pacientes_base.values("estado_tratamiento")
        .annotate(count=Count("id"))
        .order_by("estado_tratamiento")
    )

    patients_alta_series = (
        pacientes_base.filter(estado_tratamiento="alta", fecha_alta__range=(from_q, to_q))
        .annotate(period=trunc("fecha_alta"))
        .values("period")
        .annotate(total=Count("id"))
        .order_by("period")
    )

    total_cobrado = pagos_base.aggregate(t=Sum("anticipo")).get("t") or 0
    total_pagos = pagos_base.count()
    total_asistencias = citas_base.filter(estado="completado").count()
    total_citas = citas_base.count()
    pacientes_nuevos = pacientes_base.filter(registro__range=(from_q, to_q)).count()

    return Response(
        {
            "range": {"from": from_q.isoformat(), "to": to_q.isoformat()},
            "group": group,
            "profesional": profesional_id,
            "attendance_series": list(attendance_series),
            "sales_series": list(sales_series),
            "monthly_income": list(monthly_income),
            "status_breakdown": list(status_breakdown),
            "payments_by_method": list(payments_by_method),
            "revenue_by_service": list(revenue_by_service),
            "patient_status_totals": list(patient_status_totals),
            "patients_alta_series": list(patients_alta_series),
            "kpis": {
                "total_cobrado": float(total_cobrado),
                "total_pagos": total_pagos,
                "total_asistencias": total_asistencias,
                "total_citas": total_citas,
                "pacientes_nuevos": pacientes_nuevos,
            },
        }
    )