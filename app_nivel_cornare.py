import numpy as np
import pandas as pd
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Configuración inicial y constantes
# ------------------------------------------------------------------
NOMBRE_ESTUDIANTE = "Valery Ochoa"
CODIGO_ESTACION = "9"
CALIDAD_DEFECTO = 1

LAT_DEFECTO = 6.2773
LON_DEFECTO = -75.4475

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud"]

st.set_page_config(page_title="Nivel de estación — CORNARE", page_icon="🌊", layout="wide")


# ------------------------------------------------------------------
# Funciones de consulta y procesamiento
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"


def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros


def detectar_coordenadas(datos_json):
    """Busca lat/lon en las llaves raíz de la respuesta. Si no las encuentra, usa el valor por defecto."""
    if not isinstance(datos_json, dict):
        return LAT_DEFECTO, LON_DEFECTO, False

    lat = next((datos_json[k] for k in CANDIDATOS_LAT if k in datos_json), None)
    lon = next((datos_json[k] for k in CANDIDATOS_LON if k in datos_json), None)

    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon), True
        except (TypeError, ValueError):
            pass
    return LAT_DEFECTO, LON_DEFECTO, False


def calcular_indice_calidad(df):
    """Índice simple (0-100) combinando completitud de la serie y proporción de outliers."""
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())


# ------------------------------------------------------------------
# Encabezado principal (vista centrada, sin sidebar)
# ------------------------------------------------------------------
st.title("🌊 Nivel de ríos y quebradas — CORNARE")
st.markdown(f"**Estudiante:** {NOMBRE_ESTUDIANTE} &nbsp;&nbsp;|&nbsp;&nbsp; **Estación:** {CODIGO_ESTACION}")
st.divider()

# ------------------------------------------------------------------
# Filtros de búsqueda en el cuerpo principal
# ------------------------------------------------------------------
col_filtro, col_boton = st.columns([3, 1])

with col_filtro:
    rango_fechas = st.date_input(
        "Selecciona el rango de fechas:",
        value=(pd.to_datetime("2026-08-20"), pd.to_datetime("2026-08-25")),
        format="YYYY/MM/DD",
    )

with col_boton:
    st.write("##")  # Espaciado para alinear el botón con el campo de texto
    consultar = st.button("🔍 Consultar", type="primary", use_container_width=True)

# ------------------------------------------------------------------
# Consulta y visualización de datos
# ------------------------------------------------------------------
if consultar:
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        fecha_desde = rango_fechas[0].strftime("%Y-%m-%d")
        fecha_hasta = rango_fechas[1].strftime("%Y-%m-%d")

        with st.spinner("Consultando la API de CORNARE..."):
            datos_crudos, error = obtener_serie_nivel(CODIGO_ESTACION, fecha_desde, fecha_hasta, CALIDAD_DEFECTO)

        if error:
            st.error(f"❌ {error}")
        else:
            registros = obtener_todas_las_paginas(datos_crudos)

            if not registros:
                st.warning("No hay registros para esta estación y rango de fechas. Prueba otro rango.")
            else:
                df = pd.DataFrame(registros)
                df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
                df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
                df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
                df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

                lat, lon, coords_reales = detectar_coordenadas(datos_crudos)
                indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

                st.markdown("---")

                # --- Métricas principales ---
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Lecturas", len(df))
                m2.metric("Nivel promedio", f"{df['nivel'].mean():.2f}")
                m3.metric("Índice de calidad", f"{indice_calidad} / 100")
                m4.metric("Outliers detectados", n_outliers)

                # --- Gráfico de la serie ---
                st.subheader("Serie de nivel")
                st.line_chart(df.set_index("fecha")["nivel"])

                # --- Mapa de la estación ---
                st.subheader("Ubicación de la estación")
                if not coords_reales:
                    st.caption("Guarne, Quebrada La Brizuela (Red Agua - Cód. 9)")
                st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=10)

                # --- Detalles y descargas ---
                with st.expander("Detalle del índice de calidad"):
                    st.write(f"- Huecos de reporte detectados: **{huecos}**")
                    st.write(f"- Outliers (IQR + nivel negativo): **{n_outliers}** de {len(df)} lecturas")
                    st.write("El índice combina completitud de la serie (70%) y proporción de datos sin outliers (30%).")

                with st.expander("Ver datos crudos"):
                    st.dataframe(df, use_container_width=True)

                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("⬇️ Descargar CSV", csv, file_name=f"nivel_estacion_{CODIGO_ESTACION}.csv", mime="text/csv")
    else:
        st.warning("Por favor, selecciona una fecha inicial y una fecha final completas.")
else:
    st.info("Selecciona el rango de fechas deseado y presiona **Consultar**.")
