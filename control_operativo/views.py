from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.models import Cita, Clinica, Paciente, Pago, Servicio, VentaInsumo
from core.serializers.finanzas import PagoSerializer
from core.utilidades import clinica_usuario, rol_usuario
from .models import BitacoraAgenda, ComisionPago, ComisionVentaInsumo, ConfiguracionFinanciera, MetaPaciente, OrigenPaciente
from .servicios import guardar_bitacora, obtener_configuracion, snapshot_cita


def clinica_de(request):
    clinica = clinica_usuario(request.user)
    if not clinica:
        raise ValidationError({'detail': 'No hay clínica disponible.'})
    return clinica


def exigir_admin(request):
    if not request.user.is_superuser and rol_usuario(request.user) != 'admin':
        raise PermissionDenied('Solo un administrador puede realizar esta operación.')


def exigir_agenda(request):
    if not request.user.is_superuser and rol_usuario(request.user) not in ('admin', 'recepcion', 'fisioterapeuta'):
        raise PermissionDenied('No tienes permiso para consultar estos indicadores.')


def sesiones_payload(paciente):
    conteos = {r['estado']: r['total'] for r in paciente.citas.values('estado').annotate(total=Count('id'))}
    contratadas = getattr(getattr(paciente, 'meta_sesiones', None), 'contratadas', 0)
    hechas = conteos.get('completado', 0)
    return {
        'paciente_id': paciente.id, 'contratadas': contratadas,
        'realizadas': hechas, 'restantes': max(0, contratadas - hechas),
        'total_citas': sum(conteos.values()), 'canceladas': conteos.get('cancelado', 0),
        'agendadas': conteos.get('reservado', 0) + conteos.get('confirmado', 0),
        'confirmadas': conteos.get('confirmado', 0),
        'porcentaje': min(100, round(hechas * 100 / contratadas)) if contratadas else 0,
    }


@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def sesiones_paciente(request, paciente_id):
    paciente = get_object_or_404(Paciente, pk=paciente_id, clinica=clinica_de(request))
    exigir_agenda(request)
    if request.method == 'PUT':
        exigir_admin(request)
        try:
            cantidad = int(request.data.get('contratadas'))
        except (TypeError, ValueError):
            raise ValidationError({'contratadas': 'Indica un número entero válido.'})
        if not 0 <= cantidad <= 500:
            raise ValidationError({'contratadas': 'El número debe estar entre 0 y 500.'})
        MetaPaciente.objects.update_or_create(paciente=paciente, defaults={'contratadas': cantidad})
        paciente.refresh_from_db()
    return Response(sesiones_payload(paciente))


@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def configuracion_financiera(request):
    exigir_admin(request)
    clinica = clinica_de(request)
    config = obtener_configuracion(clinica)
    if request.method == 'PUT':
        try:
            pct_mp = Decimal(str(request.data.get('porcentaje_mercado_pago', config.porcentaje_mercado_pago)))
            pct_rec = Decimal(str(request.data.get('porcentaje_recepcion', config.porcentaje_recepcion)))
        except Exception:
            raise ValidationError({'detail': 'Los porcentajes deben ser números válidos.'})
        if not (0 <= pct_mp <= 100 and 0 <= pct_rec <= 100):
            raise ValidationError({'detail': 'Los porcentajes deben estar entre 0 y 100.'})
        servicio_id = request.data.get('servicio_valoracion', config.servicio_valoracion_id)
        servicio = None
        if servicio_id not in (None, '', 'null'):
            servicio = get_object_or_404(Servicio, pk=servicio_id, clinica=clinica)
        config.porcentaje_mercado_pago = pct_mp
        config.porcentaje_recepcion = pct_rec
        config.servicio_valoracion = servicio
        config.full_clean()
        config.save()
    return Response({
        'porcentaje_mercado_pago': config.porcentaje_mercado_pago,
        'porcentaje_recepcion': config.porcentaje_recepcion,
        'servicio_valoracion': config.servicio_valoracion_id,
        'servicios': list(Servicio.objects.filter(clinica=clinica, activo=True).values('id', 'nombre').order_by('nombre')),
        'aviso': 'Los porcentajes nuevos aplican a pagos futuros; los anteriores conservan su tasa registrada.',
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def resumen_comisiones(request):
    exigir_admin(request)
    clinica = clinica_de(request)
    desde = request.query_params.get('desde') or date.today().replace(day=1).isoformat()
    hasta = request.query_params.get('hasta') or date.today().isoformat()
    try:
        if date.fromisoformat(desde) > date.fromisoformat(hasta):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValidationError({'detail': 'Rango de fechas inválido.'})
    registros = (OrigenPaciente.objects.filter(
        paciente__clinica=clinica, creado__date__range=(desde, hasta),
        rol_registro='recepcion', origen='nuevo')
        .select_related('paciente', 'registrado_por').order_by('-creado'))
    pacientes = [{
        'id': x.paciente_id,
        'nombre': f'{x.paciente.nombres} {x.paciente.apellido_pat} {x.paciente.apellido_mat}'.strip(),
        'recepcionista': x.registrado_por.get_full_name() or x.registrado_por.username,
        'fecha': x.creado.date().isoformat(),
    } for x in registros]
    pagos = (ComisionPago.objects.filter(
        pago__cita__paciente__clinica=clinica, pago__fecha_pago__range=(desde, hasta))
        .select_related('pago__cita__paciente', 'recepcionista'))
    detalle = [{
        'pago': x.pago_id, 'paciente': str(x.pago.cita.paciente), 'fecha': x.pago.fecha_pago,
        'cobrado': x.pago.anticipo, 'porcentaje_mp': x.porcentaje_mp,
        'comision_mp': x.monto_mp, 'porcentaje_recepcion': x.porcentaje_recepcion,
        'comision_recepcion': x.monto_recepcion,
        'recepcionista': x.recepcionista.get_full_name() or x.recepcionista.username if x.recepcionista else None,
    } for x in pagos]
    insumos = ComisionVentaInsumo.objects.filter(venta__producto__clinica=clinica, venta__fecha_pago__range=(desde, hasta))
    total_mp_insumos = insumos.aggregate(total=Sum('monto_mp'))['total'] or Decimal('0')
    return Response({
        'total_pacientes_nuevos': len(pacientes), 'pacientes': pacientes,
        'total_mp': sum((x.monto_mp for x in pagos), Decimal('0')) + total_mp_insumos,
        'total_recepcion': sum((x.monto_recepcion for x in pagos), Decimal('0')),
        'total_mp_insumos': total_mp_insumos,
        'pagos': detalle,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def ocupacion_historica(request):
    exigir_agenda(request)
    clinica = clinica_de(request)
    hoy = date.today()
    fin = hoy - timedelta(days=1)
    # Tres meses aproximados: 90 días completos, evitando el día de hoy incompleto.
    inicio = fin - timedelta(days=89)
    filas = (
        Cita.objects.filter(paciente__clinica=clinica, fecha__range=(inicio, fin))
        .exclude(estado='cancelado')
        .annotate(dia_sql=ExtractWeekDay('fecha'), hora=ExtractHour('hora_inicio'))
        .values('dia_sql', 'hora').annotate(total=Count('id'))
    )
    dias_reales = Counter((inicio + timedelta(days=x)).weekday() for x in range(90))
    acumulado = {((int(f['dia_sql']) + 5) % 7, int(f['hora'])): f['total'] for f in filas}
    maximo = max((total / dias_reales[d] for (d, h), total in acumulado.items() if dias_reales[d]), default=0)
    nombres = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    dias = []
    for dia in range(7):
        horas = []
        for hora in range(8, 21):
            promedio = acumulado.get((dia, hora), 0) / dias_reales[dia]
            horas.append({'hora': f'{hora:02d}:00', 'promedio_citas': round(promedio, 2),
                          'intensidad': round(promedio * 100 / maximo) if maximo else 0})
        dias.append({'dia': dia, 'nombre': nombres[dia], 'ocurrencias': dias_reales[dia],
                     'promedio_diario': round(sum(acumulado.get((dia, h), 0) for h in range(24)) / dias_reales[dia], 2),
                     'horas': horas})
    return Response({'desde': inicio, 'hasta': fin, 'metodo': 'promedio de citas no canceladas por día de la semana y hora, últimos 90 días', 'dias': dias})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def pacientes_inactivos(request):
    exigir_agenda(request)
    clinica = clinica_de(request)
    limite = date.today() - timedelta(days=3)
    pacientes = (Paciente.objects.filter(clinica=clinica, estado_tratamiento='en_tratamiento')
        .annotate(ultima_visita=Max('citas__fecha', filter=Q(citas__estado='completado')))
        .filter(ultima_visita__lt=limite).order_by('ultima_visita')[:50])
    return Response([{'paciente_id': p.id, 'nombre': str(p), 'ultima_visita': p.ultima_visita,
                      'dias_sin_venir': (date.today() - p.ultima_visita).days} for p in pacientes])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def bitacora_agenda(request):
    exigir_admin(request)
    queryset = BitacoraAgenda.objects.filter(clinica=clinica_de(request)).select_related('usuario')
    desde = request.query_params.get('desde')
    hasta = request.query_params.get('hasta')
    if desde:
        queryset = queryset.filter(fecha__date__gte=desde)
    if hasta:
        queryset = queryset.filter(fecha__date__lte=hasta)
    items = queryset[:200]
    return Response([{
        'id': x.pk, 'fecha': x.fecha, 'usuario': (x.usuario.get_full_name() or x.usuario.username) if x.usuario else 'Sitio web',
        'tipo': x.tipo, 'objeto_id': x.objeto_id, 'accion': x.accion,
        'anterior': x.anterior, 'nuevo': x.nuevo, 'descripcion': x.descripcion,
    } for x in items])


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def operaciones_masivas(request):
    exigir_admin(request)
    clinica = clinica_de(request)
    accion = request.data.get('accion')
    ids = request.data.get('cita_ids') or []
    if accion not in ('eliminar', 'cobrar'):
        raise ValidationError({'accion': 'Debe ser eliminar o cobrar.'})
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise ValidationError({'cita_ids': 'Selecciona entre 1 y 100 citas.'})
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        raise ValidationError({'cita_ids': 'Los identificadores deben ser numéricos.'})
    if len(set(ids)) != len(ids):
        raise ValidationError({'cita_ids': 'No se admiten IDs duplicados.'})
    with transaction.atomic():
        citas = list(Cita.objects.select_for_update().filter(pk__in=ids, paciente__clinica=clinica).select_related('paciente', 'servicio'))
        if len(citas) != len(ids):
            raise ValidationError({'cita_ids': 'Hay citas inexistentes o ajenas a la clínica.'})
        if accion == 'eliminar':
            if Pago.objects.filter(cita_id__in=ids).exists():
                raise ValidationError({'detail': 'No se pueden eliminar citas con pagos registrados. Cancélalas o resuelve primero sus pagos.'})
            for cita in citas:
                guardar_bitacora(usuario=request.user, tipo='cita', objeto_id=cita.pk, accion='eliminar', anterior=snapshot_cita(cita))
            Cita.objects.filter(pk__in=ids).delete()
            return Response({'accion': 'eliminar', 'total': len(ids)})
        metodo = request.data.get('metodo_pago')
        if metodo not in ('efectivo', 'tarjeta', 'transferencia', 'otro'):
            raise ValidationError({'metodo_pago': 'Método de pago inválido.'})
        fecha = request.data.get('fecha_pago') or date.today().isoformat()
        try:
            date.fromisoformat(fecha)
        except (TypeError, ValueError):
            raise ValidationError({'fecha_pago': 'Fecha inválida.'})
        pagos = []
        for cita in citas:
            if cita.estado == 'cancelado':
                raise ValidationError({'detail': f'La cita {cita.id} está cancelada.'})
            restante = Decimal(cita.monto_final or cita.precio or 0) - Decimal(cita.anticipo or 0)
            if restante <= 0:
                raise ValidationError({'detail': f'La cita {cita.id} no tiene saldo pendiente.'})
            serializer = PagoSerializer(data={
                'cita': cita.id, 'fecha_pago': fecha, 'comprobante': 'COBRO MASIVO',
                'monto_facturado': str(cita.precio), 'metodo_pago': metodo,
                'descuento_porcentaje': str(cita.descuento_porcentaje), 'anticipo': str(restante),
            })
            serializer.is_valid(raise_exception=True)
            pago = serializer.save()
            pagos.append(pago.id)
            guardar_bitacora(usuario=request.user, tipo='cita', objeto_id=cita.pk, accion='cobro_masivo',
                              nuevo={'pago_id': pago.id, 'importe': str(restante), 'metodo': metodo})
        return Response({'accion': 'cobrar', 'total': len(pagos), 'pagos_ids': pagos})
