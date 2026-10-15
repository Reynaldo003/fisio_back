from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
from django.utils import timezone
from core.models import Cita, Pago, VentaInsumo
from core.utilidades import primera_clinica
from .models import BitacoraAgenda, ComisionPago, ComisionVentaInsumo, ConfiguracionFinanciera, OrigenPaciente


def obtener_configuracion(clinica=None):
    clinica = clinica or primera_clinica()
    if not clinica:
        return None
    config, _ = ConfiguracionFinanciera.objects.get_or_create(clinica=clinica)
    return config


def dinero(valor):
    return (Decimal(str(valor or 0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def snapshot_cita(cita):
    return {
        'id': cita.pk, 'paciente_id': cita.paciente_id, 'servicio_id': cita.servicio_id,
        'profesional_id': cita.profesional_id, 'fecha': str(cita.fecha),
        'hora_inicio': str(cita.hora_inicio), 'hora_termina': str(cita.hora_termina),
        'estado': cita.estado, 'precio': str(cita.precio), 'notas': cita.notas,
    }


def guardar_bitacora(*, usuario, tipo, objeto_id, accion, anterior=None, nuevo=None, descripcion=''):
    clinica = Cita.objects.filter(pk=objeto_id).values_list('paciente__clinica_id', flat=True).first() if tipo == 'cita' else None
    if not clinica:
        primera = primera_clinica()
        clinica = primera.id if primera else None
    return BitacoraAgenda.objects.create(
        clinica_id=clinica,
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
        tipo=tipo, objeto_id=objeto_id, accion=accion,
        anterior=anterior or {}, nuevo=nuevo or {}, descripcion=descripcion[:200],
    )


def es_primera_valoracion(cita, servicio_id):
    # Configurar el servicio de valoración evita depender de nombres escritos a mano.
    if not servicio_id:
        return False
    if cita.servicio_id != servicio_id or cita.estado != 'completado':
        return False
    primera = (
        Cita.objects.filter(paciente_id=cita.paciente_id, servicio_id=servicio_id, estado='completado')
        .order_by('fecha', 'hora_inicio', 'id').values_list('id', flat=True).first()
    )
    return primera == cita.pk


def sincronizar_comision_pago(pago):
    cita = pago.cita
    config = obtener_configuracion(cita.paciente.clinica)
    if not config:
        return
    # Los porcentajes se fijan al primer registro de cada pago para conservar el historial.
    registro, creado = ComisionPago.objects.get_or_create(
        pago=pago,
        defaults={'porcentaje_mp': config.porcentaje_mercado_pago,
                  'porcentaje_recepcion': config.porcentaje_recepcion,
                  'servicio_valoracion_snapshot': config.servicio_valoracion_id},
    )
    if creado:
        registro.porcentaje_mp = config.porcentaje_mercado_pago
        registro.porcentaje_recepcion = config.porcentaje_recepcion
        registro.servicio_valoracion_snapshot = config.servicio_valoracion_id
    registro.monto_mp = dinero(pago.anticipo * registro.porcentaje_mp / 100) if pago.metodo_pago == 'tarjeta' else Decimal('0.00')
    origen = OrigenPaciente.objects.filter(paciente_id=cita.paciente_id).select_related('registrado_por').first()
    receptor = None
    reserva = getattr(cita, 'atribucion', None)
    if origen and origen.origen == 'nuevo' and origen.registrado_por_id and es_primera_valoracion(cita, registro.servicio_valoracion_snapshot):
        if (origen.rol_registro == 'recepcion' and reserva and reserva.rol_al_agendar == 'recepcion'
                and reserva.agendada_por_id == origen.registrado_por_id):
            receptor = origen.registrado_por
    registro.recepcionista = receptor
    registro.monto_recepcion = dinero(pago.anticipo * registro.porcentaje_recepcion / 100) if receptor else Decimal('0.00')
    registro.save()


def sincronizar_comisiones_cita(cita):
    for pago in Pago.objects.filter(cita=cita).select_related('cita__paciente'):
        sincronizar_comision_pago(pago)


def sincronizar_comision_insumo(venta):
    config = obtener_configuracion(venta.producto.clinica)
    if not config:
        return
    registro, _ = ComisionVentaInsumo.objects.get_or_create(
        venta=venta, defaults={'porcentaje_mp': config.porcentaje_mercado_pago},
    )
    monto_venta = Decimal(venta.cantidad) * Decimal(venta.precio_unitario)
    registro.monto_mp = dinero(monto_venta * registro.porcentaje_mp / 100) if venta.metodo_pago == 'tarjeta' else Decimal('0')
    registro.save(update_fields=['monto_mp', 'actualizado'])
