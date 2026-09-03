from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core.models import MovimientoInsumo, ProductoInsumo, VentaInsumo
from core.permissions import PuedeEditarInsumos, PuedeVerInsumos
from core.serializers.insumos import MovimientoInsumoSerializer, ProductoInsumoSerializer, VentaInsumoSerializer
from core.utilidades import clinica_usuario


def _es_entrada(tipo):
    return tipo in {"compra", "entrada", "ajuste_entrada"}


def _aplicar_stock(producto, tipo, cantidad, inverso=False):
    cantidad = Decimal(cantidad or 0)
    signo = Decimal("1") if _es_entrada(tipo) else Decimal("-1")
    if inverso:
        signo *= -1
    nuevo = Decimal(producto.stock_actual or 0) + signo * cantidad
    if nuevo < 0:
        raise ValidationError({"cantidad": "El movimiento dejaría el inventario con stock negativo."})
    producto.stock_actual = nuevo
    producto.save(update_fields=["stock_actual", "actualizado"])


class ProductoInsumoViewSet(viewsets.ModelViewSet):
    serializer_class = ProductoInsumoSerializer

    def get_permissions(self):
        return [PuedeVerInsumos()] if self.request.method in permissions.SAFE_METHODS else [PuedeEditarInsumos()]

    def get_queryset(self):
        clinica = clinica_usuario(self.request.user)
        return ProductoInsumo.objects.filter(clinica=clinica).order_by("nombre")

    def perform_create(self, serializer):
        clinica = clinica_usuario(self.request.user)
        if not clinica:
            raise ValidationError({"detail": "No existe clínica configurada."})
        serializer.save(clinica=clinica)

    @action(detail=False, methods=["get"], url_path="resumen")
    def resumen(self, request):
        qs = self.get_queryset()
        valor = sum((Decimal(item.stock_actual or 0) * Decimal(item.precio_compra or 0) for item in qs), Decimal("0"))
        return Response({
            "total_productos": qs.filter(activo=True).count(),
            "stock_bajo": sum(1 for item in qs.filter(activo=True) if Decimal(item.stock_actual or 0) <= Decimal(item.stock_minimo or 0)),
            "valor_inventario": valor,
        })


class MovimientoInsumoViewSet(viewsets.ModelViewSet):
    serializer_class = MovimientoInsumoSerializer

    def get_permissions(self):
        return [PuedeVerInsumos()] if self.request.method in permissions.SAFE_METHODS else [PuedeEditarInsumos()]

    def get_queryset(self):
        clinica = clinica_usuario(self.request.user)
        qs = MovimientoInsumo.objects.select_related("producto", "registrado_por").filter(producto__clinica=clinica)
        desde = self.request.query_params.get("desde")
        hasta = self.request.query_params.get("hasta")
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        return qs.order_by("-fecha", "-id")

    @transaction.atomic
    def perform_create(self, serializer):
        movimiento = serializer.save(registrado_por=self.request.user)
        producto = ProductoInsumo.objects.select_for_update().get(pk=movimiento.producto_id)
        _aplicar_stock(producto, movimiento.tipo, movimiento.cantidad)

    @transaction.atomic
    def perform_update(self, serializer):
        anterior = self.get_object()
        producto_anterior = ProductoInsumo.objects.select_for_update().get(pk=anterior.producto_id)
        _aplicar_stock(producto_anterior, anterior.tipo, anterior.cantidad, inverso=True)
        movimiento = serializer.save()
        producto_nuevo = ProductoInsumo.objects.select_for_update().get(pk=movimiento.producto_id)
        _aplicar_stock(producto_nuevo, movimiento.tipo, movimiento.cantidad)

    @transaction.atomic
    def perform_destroy(self, instance):
        producto = ProductoInsumo.objects.select_for_update().get(pk=instance.producto_id)
        _aplicar_stock(producto, instance.tipo, instance.cantidad, inverso=True)
        instance.delete()


class VentaInsumoViewSet(viewsets.ModelViewSet):
    serializer_class = VentaInsumoSerializer

    def get_permissions(self):
        return [PuedeVerInsumos()] if self.request.method in permissions.SAFE_METHODS else [PuedeEditarInsumos()]

    def get_queryset(self):
        clinica = clinica_usuario(self.request.user)
        qs = VentaInsumo.objects.select_related("producto", "paciente", "registrado_por").filter(producto__clinica=clinica)
        fecha_pago = self.request.query_params.get("fecha_pago")
        desde = self.request.query_params.get("desde")
        hasta = self.request.query_params.get("hasta")
        if fecha_pago:
            qs = qs.filter(fecha_pago=fecha_pago)
        if desde:
            qs = qs.filter(fecha_pago__gte=desde)
        if hasta:
            qs = qs.filter(fecha_pago__lte=hasta)
        return qs.order_by("-fecha_pago", "-id")

    @transaction.atomic
    def perform_create(self, serializer):
        producto = ProductoInsumo.objects.select_for_update().get(pk=serializer.validated_data["producto"].pk)
        cantidad = Decimal(serializer.validated_data.get("cantidad") or 0)
        if Decimal(producto.stock_actual or 0) < cantidad:
            raise ValidationError({"cantidad": f"Stock insuficiente. Disponible: {producto.stock_actual}."})
        precio = serializer.validated_data.get("precio_unitario")
        if precio in (None, ""):
            precio = producto.precio_venta
        venta = serializer.save(registrado_por=self.request.user, precio_unitario=precio)
        producto.stock_actual = Decimal(producto.stock_actual or 0) - cantidad
        producto.save(update_fields=["stock_actual", "actualizado"])

    @transaction.atomic
    def perform_update(self, serializer):
        anterior = self.get_object()
        producto_anterior = ProductoInsumo.objects.select_for_update().get(pk=anterior.producto_id)
        producto_anterior.stock_actual = Decimal(producto_anterior.stock_actual or 0) + Decimal(anterior.cantidad or 0)
        producto_anterior.save(update_fields=["stock_actual", "actualizado"])
        venta = serializer.save()
        producto_nuevo = ProductoInsumo.objects.select_for_update().get(pk=venta.producto_id)
        cantidad = Decimal(venta.cantidad or 0)
        if Decimal(producto_nuevo.stock_actual or 0) < cantidad:
            raise ValidationError({"cantidad": f"Stock insuficiente. Disponible: {producto_nuevo.stock_actual}."})
        producto_nuevo.stock_actual = Decimal(producto_nuevo.stock_actual or 0) - cantidad
        producto_nuevo.save(update_fields=["stock_actual", "actualizado"])

    @transaction.atomic
    def perform_destroy(self, instance):
        producto = ProductoInsumo.objects.select_for_update().get(pk=instance.producto_id)
        producto.stock_actual = Decimal(producto.stock_actual or 0) + Decimal(instance.cantidad or 0)
        producto.save(update_fields=["stock_actual", "actualizado"])
        instance.delete()
