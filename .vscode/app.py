# Token de GITHUB Carpeta PythonFlask para despliegue en VPS.




"""Aplicación web Flask para herramientas de análisis bursátil.

Sirve la portada y el backtest de ``EstrategiaV2`` mediante las plantillas de
``templates/`` y los recursos de ``static/``, ubicados en la raíz del proyecto.
"""

from datetime import date, datetime, timedelta

from flask import Flask, render_template, request

from EstrategiaV2 import ejecutar_estrategia
from CargaDatos import calcular_indicadores, descargar_datos

app = Flask(__name__, template_folder="../templates", static_folder="../static")

@app.route("/")
def portada():
    """Muestra la portada con enlaces a las herramientas disponibles."""
    return render_template("inicio.html")


@app.route("/indicadores-tecnicos", methods=["GET", "POST"])
def indicadores_tecnicos():
    """Muestra los datos de mercado y los indicadores para una fecha elegida."""
    valores = {
        "ticker": request.form.get("ticker", "SAN.MC").strip(),
        "fecha": request.form.get("fecha", ""),
    }
    error = None
    resultado = None
    hoy = date.today()

    if request.method == "POST":
        if not valores["ticker"]:
            error = "Introduce un ticker."
        else:
            try:
                fecha_consulta = datetime.strptime(
                    valores["fecha"], "%Y-%m-%d"
                ).date()
                if fecha_consulta > hoy:
                    error = "La fecha no puede ser posterior a hoy."
            except ValueError:
                error = "Introduce una fecha válida."

        if error is None:
            try:
                fecha_inicio = fecha_consulta - timedelta(days=400)
                fecha_fin = fecha_consulta + timedelta(days=1)
                datos = descargar_datos(
                    valores["ticker"],
                    fecha_inicio.isoformat(),
                    fecha_fin.isoformat(),
                )
                filas_fecha = datos.loc[datos.index.date == fecha_consulta]
                if filas_fecha.empty:
                    error = (
                        "No hay datos de mercado para ese ticker en la fecha "
                        "seleccionada. Comprueba que sea una sesión bursátil."
                    )
                elif len(datos) < 200:
                    error = (
                        "No hay suficiente histórico anterior para calcular "
                        "todos los indicadores en esa fecha."
                    )
                else:
                    datos_con_indicadores = calcular_indicadores(datos)
                    fila = datos_con_indicadores.loc[
                        datos_con_indicadores.index.date == fecha_consulta
                    ]
                    if fila.empty:
                        error = (
                            "No hay suficiente histórico anterior para calcular "
                            "todos los indicadores en esa fecha."
                        )
                    else:
                        valores_fila = fila.iloc[-1]
                        resultado = {
                            "ticker": valores["ticker"],
                            "fecha": fecha_consulta.isoformat(),
                            "datos": {
                                "Apertura": float(valores_fila["Open"]),
                                "Máximo": float(valores_fila["High"]),
                                "Mínimo": float(valores_fila["Low"]),
                                "Cierre": float(valores_fila["Close"]),
                                "Volumen": float(valores_fila["Volume"]),
                                "Media móvil corta (50)": float(
                                    valores_fila["SMA_corta"]
                                ),
                                "Media móvil larga (200)": float(
                                    valores_fila["SMA_larga"]
                                ),
                                "Volatilidad (20)": float(
                                    valores_fila["Volatilidad"]
                                ),
                                "RSI (14)": float(valores_fila["RSI"]),
                                "Banda Bollinger inferior (20, 2)": float(
                                    valores_fila["Bollinger_Inferior"]
                                ),
                                "Banda Bollinger media (20)": float(
                                    valores_fila["Bollinger_Media"]
                                ),
                                "Banda Bollinger superior (20, 2)": float(
                                    valores_fila["Bollinger_Superior"]
                                ),
                                "Volumen medio (20 sesiones)": float(
                                    valores_fila["Volumen_Medio_20"]
                                ),
                            },
                        }
            except ValueError as exc:
                error = str(exc)

    return render_template(
        "indicadores.html",
        valores=valores,
        error=error,
        resultado=resultado,
        hoy=hoy.isoformat(),
    )


@app.route("/estrategia-v2", methods=["GET", "POST"])
def estrategia_v2():
    """Muestra el formulario y procesa solicitudes de backtesting.

    En solicitudes POST valida el ticker, las fechas, los umbrales RSI y de
    probabilidad (entre 0 y 100), y los períodos de las medias móviles. Si los
    datos son válidos, ejecuta la estrategia y prepara sus métricas y gráfico.
    El formulario, los errores y los resultados se renderizan en ``index.html``.
    """
    valores = {
        "ticker": request.form.get("ticker", "SAN.MC").strip(),
        "fecha_inicio": request.form.get("fecha_inicio", ""),
        "fecha_fin": request.form.get("fecha_fin", ""),
        "rsi_entrada": request.form.get("rsi_entrada", "30"),
        "rsi_salida": request.form.get("rsi_salida", "70"),
        "probabilidad_minima": request.form.get("probabilidad_minima", "50"),
        "probabilidad_maxima_venta": request.form.get(
            "probabilidad_maxima_venta", "30"
        ),
        "periodo_media_corta": request.form.get("periodo_media_corta", "50"),
        "periodo_media_larga": request.form.get("periodo_media_larga", "200"),
    }
    error = None
    resultado = None

    if request.method == "POST":
        rsi_entrada = 30.0
        rsi_salida = 70.0
        if not valores["ticker"]:
            error = "Introduce un ticker."
        else:
            try:
                fecha_inicio = datetime.strptime(
                    valores["fecha_inicio"], "%Y-%m-%d"
                ).date()
                fecha_fin = datetime.strptime(
                    valores["fecha_fin"], "%Y-%m-%d"
                ).date()
                if fecha_inicio >= fecha_fin:
                    error = "La fecha de inicio debe ser anterior a la fecha de fin."
            except ValueError:
                error = "Introduce fechas válidas."

        if error is None:
            try:
                rsi_entrada = float(valores["rsi_entrada"])
                rsi_salida = float(valores["rsi_salida"])
                probabilidad_minima = float(valores["probabilidad_minima"])
                probabilidad_maxima_venta = float(
                    valores["probabilidad_maxima_venta"]
                )
                periodo_media_corta = int(valores["periodo_media_corta"])
                periodo_media_larga = int(valores["periodo_media_larga"])
                if not 0 <= rsi_entrada <= 100 or not 0 <= rsi_salida <= 100:
                    error = "Los valores RSI deben estar entre 0 y 100."
                elif rsi_entrada >= rsi_salida:
                    error = "El RSI de entrada debe ser menor que el RSI de salida."
                elif not 0 <= probabilidad_minima <= 100:
                    error = "La probabilidad de subida debe estar entre 0 y 100."
                elif not 0 <= probabilidad_maxima_venta <= 100:
                    error = (
                        "La probabilidad máxima de subida para vender "
                        "debe estar entre 0 y 100."
                    )
                elif periodo_media_corta < 1 or periodo_media_larga < 1:
                    error = "Los períodos de las medias móviles deben ser positivos."
                elif periodo_media_corta >= periodo_media_larga:
                    error = (
                        "El período de la media corta debe ser menor que "
                        "el de la media larga."
                    )
            except ValueError:
                error = (
                    "Introduce valores numéricos válidos para RSI, probabilidad "
                    "y períodos de las medias móviles."
                )

        if error is None:
            try:
                (
                    grafico, rentabilidad_mercado, rentabilidad_estrategia,
                    probabilidad_subida, ultima_senal_trading,
                ) = (
                    ejecutar_estrategia(
                        valores["ticker"],
                        valores["fecha_inicio"],
                        valores["fecha_fin"],
                        rsi_entrada,
                        rsi_salida,
                        probabilidad_minima / 100,
                        probabilidad_maxima_venta / 100,
                        periodo_media_corta,
                        periodo_media_larga,
                    )
                )
                resultado = {
                    "grafico": grafico,
                    "rentabilidad_mercado": rentabilidad_mercado,
                    "rentabilidad_estrategia": rentabilidad_estrategia,
                    "probabilidad_subida": probabilidad_subida * 100,
                    "ultima_senal_trading": ultima_senal_trading,
                }
            except ValueError as exc:
                error = str(exc)

    return render_template(
        "index.html",
        valores=valores,
        error=error,
        resultado=resultado,
        hoy=date.today().isoformat(),
    )
