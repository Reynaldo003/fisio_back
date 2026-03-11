# core/models.py
import uuid
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User

class StaffProfile(models.Model):
    ROLE_CHOICES = [
        ("fisioterapeuta", "Fisioterapeuta"),
        ("nutriologo", "Nutriólogo"),
        ("dentista", "Dentista"),
        ("recepcion", "Recepción"),
        ("admin", "Administrador"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    rol = models.CharField(max_length=20, choices=ROLE_CHOICES, default="fisioterapeuta")
    telefono = models.CharField(max_length=30, blank=True, default="")
    descripcion = models.TextField(blank=True, default="")
    foto = models.ImageField(upload_to="staff/", blank=True, null=True)

    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.rol})"


class Clinica(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=255)
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clinicas",
    )

    def __str__(self):
        return self.nombre


class PerfilUsuario(models.Model):
    ROLES = [
        ("admin", "Administrador"),
        ("colaborador", "Colaborador"),
        ("recepcion", "Recepcionista"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
    )
    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="perfiles",
        null=True,
        blank=True,
    )
    rol = models.CharField(max_length=20, choices=ROLES, default="colaborador")

    titulo = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    foto = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.rol})"


class HorarioDisponible(models.Model):
    DIA_SEMANA = [
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miércoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sábado"),
        (6, "Domingo"),
    ]

    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="horarios",
    )
    dia = models.PositiveSmallIntegerField(choices=DIA_SEMANA)
    hora_apertura = models.TimeField()
    hora_cierre = models.TimeField()

    class Meta:
        unique_together = ("clinica", "dia")

    def __str__(self):
        return f"{self.get_dia_display()} {self.hora_apertura}-{self.hora_cierre}"


class Servicio(models.Model):
    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="servicios",
    )
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=150)
    duracion = models.DurationField()
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    activo = models.BooleanField(default=True)
    imagen = models.ImageField(upload_to="servicios/", blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.clinica.nombre})"

class Paciente(models.Model):
    ESTADO_TRATAMIENTO = [
        ("en_tratamiento", "En tratamiento"),
        ("alta", "Dado de alta"),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="pacientes",
    )
    nombres = models.CharField(max_length=70)
    apellido_pat = models.CharField(max_length=40)
    apellido_mat = models.CharField(max_length=40, blank=True)
    fecha_nac = models.DateField(null=True, blank=True)
    genero = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=20, blank=True, default="")
    correo = models.EmailField(max_length=100, blank=True)
    molestia = models.CharField(max_length=100, blank=True)
    notas = models.CharField(max_length=200, blank=True)
    registro = models.DateField(auto_now_add=True)

    estado_tratamiento = models.CharField(
        max_length=20,
        choices=ESTADO_TRATAMIENTO,
        default="en_tratamiento",
    )
    fecha_alta = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["clinica", "telefono"]),
            models.Index(fields=["clinica", "apellido_pat", "apellido_mat"]),
            models.Index(fields=["clinica", "nombres"]),
        ]
        ordering = ["-id"]

    def __str__(self):
        return f"{self.nombres} {self.apellido_pat}".strip()

class Comentario(models.Model):
    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="comentarios",
    )
    descripcion = models.TextField()
    calificacion = models.IntegerField()
    aprobado = models.BooleanField(default=False)
    nombre_completo = models.CharField(max_length=100)
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre_completo} ({self.calificacion})"


class Cita(models.Model):
    ESTADOS = [
        ("reservado", "Reservado"),
        ("confirmado", "Confirmado"),
        ("completado", "Completado"),
        ("cancelado", "Cancelado"),
    ]

    METODOS_PAGO = [
        ("efectivo", "Efectivo"),
        ("tarjeta", "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("otro", "Otro"),
    ]

    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.CASCADE,
        related_name="citas",
    )
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.PROTECT,
        related_name="citas",
    )
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="citas_atendidas",
    )

    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_termina = models.TimeField()

    precio = models.DecimalField(max_digits=8, decimal_places=2)
    pagado = models.BooleanField(default=False)

    metodo_pago = models.CharField(
        max_length=20,
        choices=METODOS_PAGO,
        blank=True,
    )
    descuento_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    anticipo = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Suma de todos los abonos registrados.",
    )
    monto_final = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Total de la cita después de descuentos.",
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="reservado",
    )
    notas = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-hora_inicio"]

    def __str__(self):
        return f"{self.paciente} - {self.fecha} {self.hora_inicio}"


class Pago(models.Model):
    cita = models.ForeignKey(
        Cita,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    fecha_pago = models.DateField()
    comprobante = models.CharField(max_length=100, blank=True)
    monto_facturado = models.DecimalField(max_digits=8, decimal_places=2)
    metodo_pago = models.CharField(
        max_length=20,
        choices=Cita.METODOS_PAGO,
    )
    descuento_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    anticipo = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
    )
    restante = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_pago", "-id"]

    def __str__(self):
        return f"Pago #{self.id} - Cita {self.cita_id}"

class BloqueoHorario(models.Model):
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bloqueos_horario",
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_termina = models.TimeField()
    motivo = models.CharField(max_length=200, blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-hora_inicio"]

    def __str__(self):
        return f"Bloqueo {self.fecha} {self.hora_inicio}-{self.hora_termina} ({self.profesional_id})"
