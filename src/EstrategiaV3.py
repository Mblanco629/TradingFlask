"""Optimización de cruces de medias móviles con datos históricos de mercado."""

import math
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.CargaDatos import descargar_datos
else:
    from .CargaDatos import descargar_datos


def _evaluar_parametros(
    precios, periodo_rapido, periodo_lento, inicio_evaluacion=0
):
    """Calcula métricas de una combinación aplicando señales al día siguiente."""
    cierre = precios["Close"].astype(float)
    media_rapida = cierre.rolling(periodo_rapido).mean()
    media_lenta = cierre.rolling(periodo_lento).mean()
    cruce_alcista = (
        (media_rapida > media_lenta)
        & (media_rapida.shift(1) <= media_lenta.shift(1))
    )
    cruce_bajista = (
        (media_rapida < media_lenta)
        & (media_rapida.shift(1) >= media_lenta.shift(1))
    )

    posicion = 0
    posiciones = []
    for compra, venta in zip(cruce_alcista, cruce_bajista):
        if compra:
            posicion = 1
        elif venta:
            posicion = 0
        posiciones.append(posicion)

    posiciones = pd.Series(posiciones, index=precios.index).shift(1).fillna(0)
    cambios_posicion = posiciones.diff().abs().fillna(posiciones.abs())
    retornos = cierre.pct_change().fillna(0) * posiciones - 0.002 * cambios_posicion
    retornos = retornos.iloc[inicio_evaluacion:]
    desviacion = retornos.std(ddof=1)
    ratio_sharpe = (
        float(retornos.mean() / desviacion * math.sqrt(252))
        if pd.notna(desviacion) and desviacion > 0
        else float("-inf")
    )
    rentabilidad = float((1 + retornos).prod() - 1)
    return ratio_sharpe, rentabilidad


def optimizar_parametros(datos):
    """Busca en el 70 % inicial los períodos con mejor ratio de Sharpe."""
    if datos.empty or "Close" not in datos:
        raise ValueError("No hay precios de cierre para optimizar la estrategia.")

    datos = datos.dropna(subset=["Close"]).copy()
    corte = int(len(datos) * 0.7)
    datos_entrenamiento = datos.iloc[:corte]
    if len(datos_entrenamiento) < 21:
        raise ValueError(
            "El período es demasiado corto para optimizar y validar la estrategia. "
            "Selecciona un rango de fechas más amplio."
        )

    periodos_lentos = [
        periodo
        for periodo in range(20, min(150, len(datos_entrenamiento)), 10)
    ]
    if not periodos_lentos:
        raise ValueError(
            "El período es demasiado corto para optimizar las medias móviles."
        )

    mejor = None
    for periodo_lento in periodos_lentos:
        for periodo_rapido in range(5, 40, 5):
            if periodo_rapido >= periodo_lento:
                continue
            sharpe, rentabilidad = _evaluar_parametros(
                datos_entrenamiento, periodo_rapido, periodo_lento
            )
            if mejor is None or sharpe > mejor["sharpe_entrenamiento"]:
                mejor = {
                    "periodo_rapido": periodo_rapido,
                    "periodo_lento": periodo_lento,
                    "sharpe_entrenamiento": sharpe,
                    "rentabilidad_entrenamiento": rentabilidad,
                }

    if mejor is None or not math.isfinite(mejor["sharpe_entrenamiento"]):
        raise ValueError(
            "No se encontraron operaciones válidas para optimizar. "
            "Prueba con otro ticker o un período más amplio."
        )

    sharpe_prueba, rentabilidad_prueba = _evaluar_parametros(
        datos,
        mejor["periodo_rapido"],
        mejor["periodo_lento"],
        inicio_evaluacion=corte,
    )
    mejor["sharpe_prueba"] = (
        sharpe_prueba if math.isfinite(sharpe_prueba) else None
    )
    mejor["rentabilidad_prueba"] = rentabilidad_prueba
    return mejor


def ejecutar_estrategia(ticker, fecha_inicio, fecha_fin):
    """Descarga precios y devuelve los períodos óptimos y sus métricas."""
    datos = descargar_datos(ticker, fecha_inicio, fecha_fin)
    return optimizar_parametros(datos)
