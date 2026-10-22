
"""Aplicación Flask para noticias bursátiles y backtests de estrategias.

Sirve la portada y las estrategias mediante las plantillas de ``templates/``
y los recursos de ``static/``, ubicados en la raíz del proyecto.
"""

import hmac
import os
import secrets
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.CargaDatos import calcular_indicadores, descargar_datos
    from src.EstrategiaV1 import ejecutar_estrategia as ejecutar_estrategia_v1
    from src.EstrategiaV2 import ejecutar_estrategia
    from src.EstrategiaV3 import ejecutar_estrategia as ejecutar_estrategia_v3
else:
    from .CargaDatos import calcular_indicadores, descargar_datos
    from .EstrategiaV1 import ejecutar_estrategia as ejecutar_estrategia_v1
    from .EstrategiaV2 import ejecutar_estrategia
    from .EstrategiaV3 import ejecutar_estrategia as ejecutar_estrategia_v3

app = Flask(__name__, template_folder="../templates", static_folder="../static")
URL_RSS_BME = (
    "https://www.bolsasymercados.es/es/"
    "sala-de-comunicacion/noticias.rss.xml"
)
URL_RSS_EXPANSION = "https://www.expansion.com/rss/portada.xml"
app.config["SECRET_KEY"] = (
    os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
)
if not os.environ.get("FLASK_SECRET_KEY"):
    app.logger.warning(
        "FLASK_SECRET_KEY no está definida; las sesiones se invalidarán al reiniciar."
    )
os.makedirs(app.instance_path, exist_ok=True)
database_path = os.path.join(app.instance_path, "tradingflask.sqlite").replace(
    os.sep, "/"
)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para acceder al área privada."
login_manager.login_message_category = "error"
login_manager.init_app(app)


class Usuario(UserMixin, db.Model):
    """Cuenta de acceso a las funciones privadas de la aplicación."""

    id = db.Column(db.Integer, primary_key=True)
    nombre_usuario = db.Column(db.String(40), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(256), nullable=False)

    def establecer_contrasena(self, contrasena):
        self.contrasena_hash = generate_password_hash(contrasena)

    def comprobar_contrasena(self, contrasena):
        return check_password_hash(self.contrasena_hash, contrasena)


with app.app_context():
    db.create_all()


@login_manager.user_loader
def cargar_usuario(usuario_id):
    """Recupera la cuenta guardada en la sesión."""
    try:
        return db.session.get(Usuario, int(usuario_id))
    except (TypeError, ValueError):
        return None


def _token_csrf():
    """Obtiene un token CSRF ligado a la sesión actual."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


@app.before_request
def validar_csrf():
    """Rechaza envíos falsificados a los formularios de autenticación."""
    if request.method == "POST" and request.endpoint in {
        "login", "registro", "logout",
    }:
        token_esperado = session.get("_csrf_token", "")
        token_recibido = request.form.get("csrf_token", "")
        if not token_esperado or not hmac.compare_digest(
            token_esperado, token_recibido
        ):
            abort(
                400,
                description="El formulario ha caducado. Vuelve a intentarlo.",
            )


@app.context_processor
def contexto_plantillas():
    """Proporciona el año actual al pie común de las plantillas."""
    return {
        "current_year": date.today().year,
        "csrf_token": _token_csrf,
    }


@app.route("/")
def portada():
    """Muestra las últimas cinco noticias de BME y EXPANSIÓN."""
    noticias, error_noticias = _cargar_noticias(
        URL_RSS_BME, "www.bolsasymercados.es", "BME"
    )
    noticias_expansion, error_noticias_expansion = _cargar_noticias(
        URL_RSS_EXPANSION, "www.expansion.com", "EXPANSIÓN"
    )

    return render_template(
        "inicio.html",
        noticias=noticias,
        error_noticias=error_noticias,
        noticias_expansion=noticias_expansion,
        error_noticias_expansion=error_noticias_expansion,
    )


@app.route("/chatbot")
def chatbot():
    """Muestra el chatbot conectado al webhook de n8n."""
    return render_template("chatbot.html")


def _cargar_noticias(url_feed, dominio, fuente):
    """Devuelve hasta cinco noticias de un RSS, validando su dominio."""
    try:
        respuesta = requests.get(url_feed, timeout=(3.05, 10))
        respuesta.raise_for_status()
        canal = ET.fromstring(respuesta.content).find("channel")
        if canal is None:
            raise ET.ParseError("El feed no contiene un canal RSS.")

        noticias = []
        for elemento in canal.findall("item"):
            titulo = elemento.findtext("title", "").strip()
            enlace = elemento.findtext("link", "").strip()
            destino = urlparse(enlace)
            if (
                not titulo
                or destino.scheme != "https"
                or destino.hostname != dominio
            ):
                continue
            fecha_publicacion = elemento.findtext("pubDate", "").strip()
            try:
                fecha_publicacion = parsedate_to_datetime(
                    fecha_publicacion
                ).strftime("%d/%m/%Y %H:%M")
            except (TypeError, ValueError, OverflowError):
                fecha_publicacion = ""
            noticias.append({
                "titulo": titulo,
                "enlace": enlace,
                "fecha": fecha_publicacion,
            })
            if len(noticias) == 5:
                break
        return noticias, None
    except requests.RequestException:
        app.logger.exception(
            "No se pudo consultar el RSS de noticias de %s.", fuente
        )
        return [], f"No se pudieron cargar las noticias de {fuente}."
    except ET.ParseError:
        app.logger.exception(
            "El RSS de noticias de %s no contiene XML válido.", fuente
        )
        return [], f"El feed de noticias de {fuente} no está disponible."


@app.route("/registro", methods=["GET", "POST"])
def registro():
    """Crea una cuenta nueva y la autentica."""
    if current_user.is_authenticated:
        return redirect(url_for("portada"))

    if request.method == "POST":
        nombre_usuario = (
            request.form.get("nombre_usuario", "").strip().casefold()
        )
        contrasena = request.form.get("contrasena", "")
        if (
            not 3 <= len(nombre_usuario) <= 40
            or not nombre_usuario.replace("_", "").isalnum()
        ):
            flash(
                "El usuario debe tener entre 3 y 40 caracteres alfanuméricos "
                "o guiones bajos.",
                "error",
            )
        elif len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
        elif db.session.scalar(
            db.select(Usuario).where(Usuario.nombre_usuario == nombre_usuario)
        ):
            flash("Ese nombre de usuario ya está registrado.", "error")
        else:
            usuario = Usuario(nombre_usuario=nombre_usuario)
            usuario.establecer_contrasena(contrasena)
            db.session.add(usuario)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Ese nombre de usuario ya está registrado.", "error")
            else:
                session.pop("_csrf_token", None)
                login_user(usuario)
                flash("Tu cuenta se ha creado correctamente.", "success")
                return redirect(url_for("estrategia_v2"))

    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Inicia sesión y devuelve al usuario al destino local solicitado."""
    if current_user.is_authenticated:
        return redirect(url_for("portada"))

    siguiente = request.args.get("next") or request.form.get("next", "")
    if request.method == "POST":
        nombre_usuario = (
            request.form.get("nombre_usuario", "").strip().casefold()
        )
        contrasena = request.form.get("contrasena", "")
        usuario = db.session.scalar(
            db.select(Usuario).where(Usuario.nombre_usuario == nombre_usuario)
        )
        if usuario is None or not usuario.comprobar_contrasena(contrasena):
            flash("Usuario o contraseña incorrectos.", "error")
        else:
            session.pop("_csrf_token", None)
            login_user(usuario)
            destino = urlparse(urljoin(request.host_url, siguiente))
            if (
                destino.scheme in {"http", "https"}
                and destino.netloc == request.host
            ):
                return redirect(destino.geturl())
            return redirect(url_for("portada"))

    return render_template("login.html", siguiente=siguiente)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    """Cierra la sesión actual."""
    logout_user()
    session.pop("_csrf_token", None)
    flash("Has cerrado la sesión.", "success")
    return redirect(url_for("portada"))


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
@login_required
def estrategia_v2():
    """Ejecuta el backtest de EstrategiaV2."""
    return _pagina_estrategia(ejecutar_estrategia, "EstrategiaV2")


@app.route("/estrategia-v3", methods=["GET", "POST"])
@login_required
def estrategia_v3():
    """Optimiza y muestra los parámetros privados de EstrategiaV3."""
    hoy = date.today()
    valores = {
        "ticker": request.form.get("ticker", "SAN.MC").strip(),
        "fecha_inicio": request.form.get(
            "fecha_inicio", (hoy - timedelta(days=365 * 5)).isoformat()
        ),
        "fecha_fin": request.form.get("fecha_fin", hoy.isoformat()),
    }
    error = None
    resultado = None

    if request.method == "POST":
        try:
            fecha_inicio = datetime.strptime(
                valores["fecha_inicio"], "%Y-%m-%d"
            ).date()
            fecha_fin = datetime.strptime(
                valores["fecha_fin"], "%Y-%m-%d"
            ).date()
            if not valores["ticker"]:
                error = "Introduce un ticker."
            elif fecha_inicio >= fecha_fin:
                error = "La fecha de inicio debe ser anterior a la fecha de fin."
            elif fecha_fin > hoy:
                error = "La fecha de fin no puede ser posterior a hoy."
        except ValueError:
            error = "Introduce fechas válidas."

        if error is None:
            try:
                resultado = ejecutar_estrategia_v3(
                    valores["ticker"],
                    fecha_inicio.isoformat(),
                    (fecha_fin + timedelta(days=1)).isoformat(),
                )
            except ValueError as exc:
                error = str(exc)

    return render_template(
        "estrategia_v3.html",
        valores=valores,
        error=error,
        resultado=resultado,
        hoy=hoy.isoformat(),
    )


@app.route("/estrategia-v1", methods=["GET", "POST"])
def estrategia_v1():
    """Ejecuta el backtest de EstrategiaV1."""
    return _pagina_estrategia(ejecutar_estrategia_v1, "EstrategiaV1")


def _pagina_estrategia(funcion_estrategia, nombre_estrategia):
    """Muestra el formulario y procesa solicitudes de backtesting.

    En solicitudes POST valida el ticker, las fechas, los umbrales RSI y de
    probabilidad (entre 0 y 100), y los períodos de las medias móviles. Si los
    datos son válidos, ejecuta la estrategia indicada y prepara sus métricas y gráfico.
    El formulario, los errores y los resultados se renderizan en
    ``estrategias.html``.
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
                    funcion_estrategia(
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
        "estrategias.html",
        valores=valores,
        error=error,
        resultado=resultado,
        hoy=date.today().isoformat(),
        nombre_estrategia=nombre_estrategia,
    )

"""
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
"""