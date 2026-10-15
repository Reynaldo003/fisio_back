import re
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from .models import ImagenSitio


CLAVES_FIJAS = {
    "inicio": {
        "inicio.hero", "inicio.clinica", "inicio.sala",
        "inicio.quienes.1", "inicio.quienes.2",
        "inicio.quienes.3", "inicio.quienes.4",
    },
    "marca": {
        "marca.icono", "marca.logo_oscuro",
        "marca.logo_claro", "marca.desarrollador",
    },
    "servicios": {"servicios.placeholder"},
}

EXTENSIONES = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


def clave_permitida(grupo, clave):
    if grupo == "convenios":
        return bool(
            re.fullmatch(r"convenios\.logo\.[1-9][0-9]{0,2}", clave)
            or re.fullmatch(r"convenios\.extra\.[0-9a-f]{32}", clave)
        )
    return clave in CLAVES_FIJAS.get(grupo, set())


class ImagenSitioSerializer(serializers.ModelSerializer):
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = ImagenSitio
        fields = [
            "id", "clinica", "clave", "grupo", "titulo", "imagen",
            "imagen_url", "orden", "activo", "creado", "actualizado",
        ]
        read_only_fields = ["id", "clinica", "imagen_url", "creado", "actualizado"]
        extra_kwargs = {
            "clave": {"required": False},
            "imagen": {"required": False, "write_only": True},
        }

    def get_imagen_url(self, objeto):
        if not objeto.imagen:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(objeto.imagen.url) if request else objeto.imagen.url

    def validate_imagen(self, archivo):
        if archivo is None:
            return archivo
        if archivo.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("La imagen no puede superar 5 MB.")

        extension = Path(archivo.name).suffix.lower()
        if extension not in EXTENSIONES:
            raise serializers.ValidationError("Solo se permiten archivos JPG, PNG y WebP.")

        try:
            with Image.open(archivo) as imagen:
                formato = imagen.format
                ancho, alto = imagen.size
                imagen.verify()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise serializers.ValidationError("El archivo no contiene una imagen válida.")
        finally:
            archivo.seek(0)

        if formato != EXTENSIONES[extension]:
            raise serializers.ValidationError("La extensión no corresponde al formato real de la imagen.")
        if ancho > 6000 or alto > 6000:
            raise serializers.ValidationError("La imagen no debe superar 6000 píxeles por lado.")
        return archivo

    def validate(self, datos):
        if self.instance:
            for campo in ("clave", "grupo"):
                if campo in datos and datos[campo] != getattr(self.instance, campo):
                    raise serializers.ValidationError({campo: "No se permite cambiar este campo."})
            if self.instance.clave.startswith("convenios.extra."):
                if "imagen" in datos and not datos["imagen"]:
                    raise serializers.ValidationError({"imagen": "Este convenio necesita una imagen."})
            return datos

        grupo = datos.get("grupo")
        clave = str(datos.get("clave") or "").strip()
        if not grupo:
            raise serializers.ValidationError({"grupo": "Selecciona un grupo."})
        if not clave:
            if grupo != "convenios":
                raise serializers.ValidationError({"clave": "Selecciona una posición del sitio."})
            clave = f"convenios.extra.{uuid.uuid4().hex}"
            datos["clave"] = clave
        if not clave_permitida(grupo, clave):
            raise serializers.ValidationError({"clave": "La posición no pertenece al grupo indicado."})
        if clave.startswith("convenios.extra.") and not datos.get("imagen"):
            raise serializers.ValidationError({"imagen": "Selecciona el logo del convenio."})

        clinica = self.context.get("clinica")
        if clinica and ImagenSitio.objects.filter(clinica=clinica, clave=clave).exists():
            raise serializers.ValidationError({"clave": "Esta posición ya tiene una imagen configurada."})
        return datos


class ImagenSitioPublicaSerializer(serializers.ModelSerializer):
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = ImagenSitio
        fields = ["clave", "grupo", "titulo", "orden", "activo", "imagen_url"]

    def get_imagen_url(self, objeto):
        if not objeto.imagen:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(objeto.imagen.url) if request else objeto.imagen.url
