from datetime import date, datetime

from flask import Flask, render_template, request

from EstrategiaV2 import ejecutar_estrategia

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def inicio():
    valores = {
        "ticker": request.form.get("ticker", "SAN.MC").strip(),
        "fecha_inicio": request.form.get("fecha_inicio", ""),
        "fecha_fin": request.form.get("fecha_fin", ""),
        "rsi_entrada": request.form.get("rsi_entrada", "30"),
        "rsi_salida": request.form.get("rsi_salida", "70"),
        "probabilidad_minima": request.form.get("probabilidad_minima", "50"),
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
                if not 0 <= rsi_entrada <= 100 or not 0 <= rsi_salida <= 100:
                    error = "Los valores RSI deben estar entre 0 y 100."
                elif rsi_entrada >= rsi_salida:
                    error = "El RSI de entrada debe ser menor que el RSI de salida."
                elif not 0 <= probabilidad_minima <= 100:
                    error = "La probabilidad de subida debe estar entre 0 y 100."
            except ValueError:
                error = "Introduce valores numéricos válidos para RSI y probabilidad."

        if error is None:
            try:
                grafico, rentabilidad_mercado, rentabilidad_estrategia = (
                    ejecutar_estrategia(
                        valores["ticker"],
                        valores["fecha_inicio"],
                        valores["fecha_fin"],
                        rsi_entrada,
                        rsi_salida,
                        probabilidad_minima / 100,
                    )
                )
                resultado = {
                    "grafico": grafico,
                    "rentabilidad_mercado": rentabilidad_mercado,
                    "rentabilidad_estrategia": rentabilidad_estrategia,
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


if __name__ == "__main__":
    app.run(debug=True)
