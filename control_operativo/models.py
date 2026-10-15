from django.conf import settings
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from decimal import Decimal


class ConfiguracionFinanciera(models.Model):
    clinica = models.OneToOneField('core.Clinica', on_delete=models.CASCADE, related_name='configuracion_financiera')
    porcentaje_mercado_pago = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.50'), validators=[MinValueValidator(0), MaxValueValidator(100)])
    porcentaje_recepcion = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(0), MaxValueValidator(100)])
    servicio_valoracion = models.ForeignKey('core.Servicio', on_delete=models.SET_NULL, null=True, blank=True)
    actualizado = models.DateTimeField(auto_now=True)


class MetaPaciente(models.Model):
    paciente = models.OneToOneField('core.Paciente', on_delete=models.CASCADE, related_name='meta_sesiones')
    contratadas = models.PositiveIntegerField(default=0)
    actualizado = models.DateTimeField(auto_now=True)


class OrigenPaciente(models.Model):
    ORIGENES = [('nuevo', 'Paciente directo'), ('recomendado', 'Recomendación'), ('otro', 'Otro')]
    paciente = models.OneToOneField('core.Paciente', on_delete=models.CASCADE, related_name='atribucion')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    origen = models.CharField(max_length=20, choices=ORIGENES, default='nuevo')
    rol_registro = models.CharField(max_length=30, blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)


class OrigenCita(models.Model):
    cita = models.OneToOneField('core.Cita', on_delete=models.CASCADE, related_name='atribucion')
    agendada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    rol_al_agendar = models.CharField(max_length=30, blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)


class ComisionPago(models.Model):
    pago = models.OneToOneField('core.Pago', on_delete=models.CASCADE, related_name='comisiones')
    porcentaje_mp = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    monto_mp = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    porcentaje_recepcion = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    servicio_valoracion_snapshot = models.PositiveIntegerField(null=True, blank=True)
    monto_recepcion = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    recepcionista = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actualizado = models.DateTimeField(auto_now=True)


class ComisionVentaInsumo(models.Model):
    venta = models.OneToOneField('core.VentaInsumo', on_delete=models.CASCADE, related_name='comision_terminal')
    porcentaje_mp = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    monto_mp = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    actualizado = models.DateTimeField(auto_now=True)


class BitacoraAgenda(models.Model):
    clinica = models.ForeignKey('core.Clinica', on_delete=models.CASCADE, null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    tipo = models.CharField(max_length=20, default='cita')
    objeto_id = models.PositiveIntegerField()
    accion = models.CharField(max_length=25)
    anterior = models.JSONField(default=dict, blank=True)
    nuevo = models.JSONField(default=dict, blank=True)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-fecha', '-id']
        indexes = [models.Index(fields=['tipo', 'objeto_id', '-fecha'])]
