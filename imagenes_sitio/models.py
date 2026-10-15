import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def ruta_imagen_sitio(instancia, nombre_archivo):
    extension = Path(nombre_archivo).suffix.lower()
    return f"imagenes_sitio/{uuid.uuid4().hex}{extension}"


class ImagenSitio(models.Model):
    GRUPOS = [
        ("inicio", "Inicio"),
        ("convenios", "Convenios"),
        ("marca", "Marca"),
        ("servicios", "Servicios"),
    ]

    clinica = models.ForeignKey(
        "core.Clinica",
        on_delete=models.CASCADE,
        related_name="imagenes_sitio",
    )
    clave = models.CharField(max_length=100)
    grupo = models.CharField(max_length=20, choices=GRUPOS)
    titulo = models.CharField(max_length=120)
    imagen = models.ImageField(upload_to=ruta_imagen_sitio, blank=True, null=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="imagenes_sitio_editadas",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["grupo", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinica", "clave"],
                name="imagenes_sitio_clinica_clave_unica",
            ),
        ]
        indexes = [
            models.Index(fields=["clinica", "grupo", "orden"], name="imagenes_si_clinica_5e583e_idx"),
        ]

    def __str__(self):
        return f"{self.clinica.nombre} - {self.titulo}"
