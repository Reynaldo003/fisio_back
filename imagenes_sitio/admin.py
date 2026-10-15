from django.contrib import admin

from .models import ImagenSitio


@admin.register(ImagenSitio)
class ImagenSitioAdmin(admin.ModelAdmin):
    list_display = ("clave", "titulo", "grupo", "clinica", "orden", "activo", "actualizado")
    list_filter = ("grupo", "clinica", "activo")
    search_fields = ("clave", "titulo")
    readonly_fields = ("creado", "actualizado")
