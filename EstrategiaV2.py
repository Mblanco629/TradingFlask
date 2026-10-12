import base64
from io import BytesIO

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier


# =========================================================
# MÓDULO 1: RECOPILACIÓN DE DATOS
# =========================================================
def descargar_datos(ticker, fecha_inicio, fecha_fin):
    """Descarga el histórico OHLCV desde Yahoo Finance."""
    print(f"Descargando datos de {ticker}...")
    df = yf.download(ticker, start=fecha_inicio, end=fecha_fin)
    
    # yfinance devuelve múltiples niveles en las columnas a veces, simplificamos:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    # Nos quedamos solo con las columnas esenciales
    if df.empty:
        raise ValueError(
            f"No se encontraron datos para {ticker} en el período indicado."
        )

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    return df.dropna()

# =========================================================
# MÓDULO 2: CALCULO DE INDICADORES TÉCNICOS
# =========================================================
def calcular_indicadores(
    df, periodo_media_corta: int = 50, periodo_media_larga: int = 200,
):
    """Añade indicadores matemáticos al DataFrame crudo."""
    print("Calculando indicadores técnicos...")
    df = df.copy()
    
    # 1. Medias Móviles Simples (SMA)
    df['SMA_corta'] = df['Close'].rolling(window=periodo_media_corta).mean()
    df['SMA_larga'] = df['Close'].rolling(window=periodo_media_larga).mean()
    
    # 2. Volatilidad (Desviación estándar de 20 días)
    df['Volatilidad'] = df['Close'].rolling(window=20).std()

    # 3. RSI de 14 períodos con suavizado de Wilder
    cambios = df['Close'].diff()
    ganancias = cambios.clip(lower=0)
    perdidas = -cambios.clip(upper=0)
    ganancia_media = ganancias.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()
    perdida_media = perdidas.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()
    fuerza_relativa = ganancia_media / perdida_media.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + fuerza_relativa))
    df.loc[(perdida_media == 0) & (ganancia_media > 0), 'RSI'] = 100
    df.loc[(perdida_media == 0) & (ganancia_media == 0), 'RSI'] = 50
    
    # Eliminamos filas con valores nulos generados por los indicadores
    return df.dropna()

# =========================================================
# 4. GENERACIÓN DE SEÑALES (Módulo 4)
# =========================================================
def generar_senal(
    sma_50, sma_200, prob_subida, rsi,
    rsi_entrada: float = 30.0, rsi_salida: float = 70.0,
    probabilidad_minima: float = 0.50,
    probabilidad_maxima_venta: float = 0.30,
):
    """Combina la tendencia, la IA y el RSI para generar una recomendación."""

#• Al inicio de los datos históricos, las medias móviles (como la sma_200) no tienen suficientes 
# velas previas para calcularse y devuelven NaN. Si intentas operar con un NaN, 
# el código fallaría. Ante la duda, la función adopta una postura segura y devuelve MANTENER.

    if (
        pd.isna(sma_50) or pd.isna(sma_200)
        or pd.isna(prob_subida) or pd.isna(rsi)
    ):
        return "MANTENER (HOLD)"

# • Qué hace: Si el RSI está en su rango normal (entre 30 y 70), significa que el mercado está en una zona de equilibrio o consolidación.
# • Resultado: No se toma ninguna acción operativa. Directamente devuelve MANTENER, ahorrando tiempo de cómputo al no evaluar el resto de condiciones.

    if rsi_entrada <= rsi <= rsi_salida:
        return "MANTENER (HOLD)"

# Para que la función te diga que compres, se tienen que cumplir las 3 condiciones estrictamente al mismo tiempo:
# 1. RSI < 30: El precio ha caído rápido y el activo está "barato" o en sobreventa.
# 2. SMA 50 > SMA 200: Existe una tendencia alcista de fondo (conocido como Cruce de Oro si ocurre recientemente). Esto asegura que no estás comprando un activo en caída libre infinita.
# 3. Probabilidad > 50%: Tu modelo de IA respalda la operación confirmando que la tendencia matemática apunta a una subida.

    if (
        rsi < rsi_entrada
        and sma_50 > sma_200
        and prob_subida > probabilidad_minima
    ):
        return "COMPRA (BUY)"

# Para que la función te diga que vendas, exige la tormenta perfecta bajista:
# 1. RSI > 70: El precio ha subido demasiado rápido y está "caro" o sobrecomprado.
# 2. SMA 50 < SMA 200: La tendencia general es bajista (Cruce de la Muerte), lo que sugiere presiones de venta a largo plazo.
# 3. Probabilidad < 30%: La IA certifica que el escenario de subida es muy poco probable, apoyando la decisión de salir del activo o abrir una posición en corto.

    if (
        rsi > rsi_salida
        and sma_50 < sma_200
        and prob_subida < probabilidad_maxima_venta
    ):
        return "VENTA (SELL)"
    return "MANTENER (HOLD)"
# =========================================================
# MÓDULO 5: BACKTESTING (Simulación de Rentabilidad)
# =========================================================
def ejecutar_backtest(df):
    """Calcula el rendimiento de la estrategia frente a simplemente retener el activo."""
    print("Ejecutando simulación de backtesting...")
    df = df.copy()
    
    # 1. Retorno diario del mercado (Buy & Hold)
    # pct_change() calcula qué porcentaje subió o bajó el precio respecto a ayer
    df['Retorno_Mercado'] = df['Close'].pct_change()
    
    # 2. Retorno de nuestra estrategia
    # IMPORTANTE: shift(1) desplaza la señal un día. Si el algoritmo decide "Comprar" 
    # hoy con los datos de cierre, la rentabilidad real se captura mañana. 
    # Olvidar el shift(1) causa "look-ahead bias" (ver el futuro trampa).
    df['Retorno_Estrategia'] = df['Senal_Trading'].shift(1) * df['Retorno_Mercado']
    
    # 3. Evolución del capital acumulado (Asumiendo que empezamos con capital = 1.0)
    df['Capital_Mercado'] = (1 + df['Retorno_Mercado']).cumprod()
    df['Capital_Estrategia'] = (1 + df['Retorno_Estrategia']).cumprod()
    
    return df.dropna()

# =========================================================
# MÓDULO 6: EJECUTAR ESTRATEGIA IA (Función principal)
# =========================================================

def ejecutar_estrategia(
    ticker, fecha_inicio, fecha_fin,
    rsi_entrada: float = 30.0, rsi_salida: float = 70.0,
    probabilidad_minima: float = 0.50,
    probabilidad_maxima_venta: float = 0.30,
    periodo_media_corta: int = 50, periodo_media_larga: int = 200,
):
    """Entrena y evalúa la estrategia para el activo y período indicados."""
    df_crudo = descargar_datos(ticker, fecha_inicio, fecha_fin)
    if periodo_media_corta < 1 or periodo_media_larga < 1:
        raise ValueError("Los períodos de las medias móviles deben ser positivos.")
    if periodo_media_corta >= periodo_media_larga:
        raise ValueError(
            "El período de la media corta debe ser menor que el de la media larga."
        )
    df_indicadores = calcular_indicadores(
        df_crudo, periodo_media_corta, periodo_media_larga
    )

    print("Preparando datos para la Inteligencia Artificial...")
    df_indicadores['Target'] = (
        df_indicadores['Close'].shift(-1) > df_indicadores['Close']
    ).astype(int)
    df_ml = df_indicadores.dropna().copy()

    features = ['SMA_corta', 'SMA_larga', 'Volatilidad', 'RSI']
    train_size = int(len(df_ml) * 0.8)
    if train_size < 2 or len(df_ml) - train_size < 2:
        raise ValueError(
            "El período es demasiado corto para entrenar y probar la estrategia. "
            "Selecciona un rango de fechas más amplio."
        )

    X_train = df_ml[features].iloc[:train_size]
    y_train = df_ml['Target'].iloc[:train_size]
    X_test = df_ml[features].iloc[train_size:]
    if y_train.nunique() < 2:
        raise ValueError(
            "Los datos de entrenamiento no contienen subidas y bajadas suficientes. "
            "Prueba con otro período."
        )

    print("Entrenando el modelo Random Forest...")
    modelo_ia = RandomForestClassifier(
        n_estimators=100, max_depth=5, random_state=42
    )
    modelo_ia.fit(X_train, y_train)

    df_ml['Prob_Subida'] = np.nan
    df_ml.loc[X_test.index, 'Prob_Subida'] = modelo_ia.predict_proba(X_test)[:, 1]

    print("Generando señales de trading en base a las predicciones...")

    df_ml['Recomendacion'] = df_ml.apply(
        lambda fila: generar_senal(
            fila['SMA_corta'], fila['SMA_larga'],
            fila['Prob_Subida'], fila['RSI'], rsi_entrada, rsi_salida,
            probabilidad_minima, probabilidad_maxima_venta,
        ),
        axis=1,
    )
    df_ml['Senal_Trading'] = df_ml['Recomendacion'].map(
        {
            "COMPRA (BUY)": 1,
            "VENTA (SELL)": -1,
            "MANTENER (HOLD)": 0,
        }
    )

    df_prueba = df_ml.iloc[train_size:].copy()
    recomendacion_manana = df_prueba['Recomendacion'].iloc[-1]
    probabilidad_subida = float(df_prueba['Prob_Subida'].iloc[-1])
    ultima_senal_trading = int(df_prueba['Senal_Trading'].iloc[-1])
    print(f"Recomendación para mañana: {recomendacion_manana}")
    print(f"Probabilidad estimada de subida: {probabilidad_subida:.2%}")
    print(f"Último valor de Senal_Trading: {ultima_senal_trading}")
    df_resultados = ejecutar_backtest(df_prueba)
    if df_resultados.empty:
        raise ValueError(
            "No hay suficientes resultados para mostrar. "
            "Selecciona un rango de fechas más amplio."
        )

    grafico = graficar_resultados(
        df_resultados, ticker, recomendacion_manana,
        rsi_entrada, rsi_salida,
        periodo_media_corta, periodo_media_larga,
        probabilidad_minima, probabilidad_maxima_venta,
    )
    rentabilidad_mercado = (
        df_resultados['Capital_Mercado'].iloc[-1] - 1
    ) * 100
    rentabilidad_estrategia = (
        df_resultados['Capital_Estrategia'].iloc[-1] - 1
    ) * 100
    return (
        grafico, rentabilidad_mercado, rentabilidad_estrategia,
        probabilidad_subida, ultima_senal_trading,
    )


# =========================================================
# MÓDULO 6: VISUALIZACIÓN DE RESULTADOS
# =========================================================
def graficar_resultados(
    df, ticker, recomendacion_manana,
    rsi_entrada: float = 30.0, rsi_salida: float = 70.0,
    periodo_media_corta: int = 50, periodo_media_larga: int = 200,
    probabilidad_minima: float = 0.50,
    probabilidad_maxima_venta: float = 0.30,
):
    """Grafica las señales, los indicadores técnicos y el rendimiento."""
    print("Generando gráficos...")
    figura, (eje_precio, eje_rsi, eje_probabilidad, eje_capital) = plt.subplots(
        4, 1, figsize=(12, 13), sharex=True,
        gridspec_kw={'height_ratios': [2, 1, 1, 1]},
    )

    eje_precio.plot(
        df.index, df['Close'], label='Precio de cierre', color='black'
    )
    eje_precio.plot(
        df.index, df['SMA_corta'],
        label=f'Media móvil corta ({periodo_media_corta})', color='orange'
    )
    eje_precio.plot(
        df.index, df['SMA_larga'],
        label=f'Media móvil larga ({periodo_media_larga})', color='purple'
    )
    compras = df[df['Senal_Trading'] == 1]
    ventas = df[df['Senal_Trading'] == -1]
    eje_precio.scatter(
        compras.index, compras['Close'], marker='^', color='green',
        s=90, label='Compra (BUY)', zorder=3,
    )
    eje_precio.scatter(
        ventas.index, ventas['Close'], marker='v', color='red',
        s=90, label='Venta (SELL)', zorder=3,
    )
    eje_precio.text(
        0.02, 0.95,
        f"Recomendación para mañana: {recomendacion_manana}",
        transform=eje_precio.transAxes, va='top',
        bbox={'boxstyle': 'round', 'facecolor': 'white', 'alpha': 0.85},
    )
    eje_precio.set_ylabel('Precio')
    eje_precio.legend()
    eje_precio.grid(True, alpha=0.3)

    eje_rsi.plot(df.index, df['RSI'], label='RSI (14)', color='teal')
    eje_rsi.axhline(
        rsi_entrada, color='green', linestyle='--',
        label=f'Umbral de entrada ({rsi_entrada:g})',
    )
    eje_rsi.axhline(
        rsi_salida, color='red', linestyle='--',
        label=f'Umbral de salida ({rsi_salida:g})',
    )
    eje_rsi.set_ylabel('RSI')
    eje_rsi.set_ylim(0, 100)
    eje_rsi.legend()
    eje_rsi.grid(True, alpha=0.3)

    eje_probabilidad.plot(
        df.index, df['Prob_Subida'] * 100,
        label='Probabilidad de subida', color='blue',
    )
    eje_probabilidad.axhline(
        probabilidad_minima * 100, color='green', linestyle='--',
        label=f'Umbral de compra ({probabilidad_minima * 100:g}%)',
    )
    eje_probabilidad.axhline(
        probabilidad_maxima_venta * 100, color='red', linestyle='--',
        label=f'Umbral de venta ({probabilidad_maxima_venta * 100:g}%)',
    )
    eje_probabilidad.set_ylabel('Prob. subida (%)')
    eje_probabilidad.set_ylim(0, 100)
    eje_probabilidad.legend()
    eje_probabilidad.grid(True, alpha=0.3)
    
    # Línea base: ¿Qué habría pasado si solo comprabas y esperabas?
    eje_capital.plot(
        df.index, df['Capital_Mercado'],
        label='Mercado (Buy & Hold)', color='gray', alpha=0.6,
    )
    
    # Nuestra estrategia: ¿Qué pasó operando con las señales de la IA?
    eje_capital.plot(
        df.index, df['Capital_Estrategia'],
        label='Estrategia IA', color='blue', linewidth=2,
    )
    
    eje_precio.set_title(f'Señales de trading y backtest ({ticker})')
    eje_capital.set_xlabel('Fecha')
    eje_capital.set_ylabel('Multiplicador de capital')
    eje_capital.legend()
    eje_capital.grid(True, alpha=0.3)
    
    # Resumen de texto en consola
    rent_mercado = (df['Capital_Mercado'].iloc[-1] - 1) * 100
    rent_estrategia = (df['Capital_Estrategia'].iloc[-1] - 1) * 100
    print(f"\n--- RESUMEN FINAL ---")
    print(f"Rentabilidad Mercado: {rent_mercado:.2f}%")
    print(f"Rentabilidad Estrategia: {rent_estrategia:.2f}%")
    
    imagen = BytesIO()
    figura.savefig(imagen, format="png", bbox_inches="tight")
    plt.close(figura)
    return base64.b64encode(imagen.getvalue()).decode("ascii")
