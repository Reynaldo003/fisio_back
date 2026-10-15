from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Cita, Pago, VentaInsumo
from .servicios import sincronizar_comisiones_cita, sincronizar_comision_pago, sincronizar_comision_insumo


@receiver(post_save, sender=Pago, dispatch_uid='control_comision_pago')
def al_guardar_pago(sender, instance, **kwargs):
    sincronizar_comision_pago(instance)


@receiver(post_save, sender=Cita, dispatch_uid='control_comision_cita')
def al_guardar_cita(sender, instance, **kwargs):
    # Si primero se pagó y después se marcó asistida, se actualiza la comisión.
    if instance.estado == 'completado':
        sincronizar_comisiones_cita(instance)


@receiver(post_save, sender=VentaInsumo, dispatch_uid='control_comision_insumo')
def al_guardar_venta_insumo(sender, instance, **kwargs):
    sincronizar_comision_insumo(instance)
