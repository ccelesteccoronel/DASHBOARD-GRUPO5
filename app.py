"""
Dashboard · Dinámica de ingresos y desigualdad (EPH-INDEC) · Grupo 5
Series trimestrales 2024-2025 · Total urbano EPH y Aglomerado Corrientes

Ejecutar:  streamlit run app.py
Requiere los CSV de data/processed/ (se generan con:  python src/etl.py)
"""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

VERSION = "2.0 (octubre de 2026)"
REPO_URL = "https://github.com/ccelesteccoronel/DASHBOARD-GRUPO5"
DATA = Path(__file__).parent / "data" / "processed"
PERIODOS = [f"T{t} {a}" for a in (2024, 2025) for t in (1, 2, 3, 4)]
REC_COLOR = {"Corrientes": "#d1495b", "Total urbano EPH": "#2e6f95"}
REC_LABEL = {"Corrientes": "Corrientes", "Total urbano EPH": "Total urbano EPH (31 aglomerados)"}

st.set_page_config(page_title="Desigualdad de ingresos | EPH-INDEC", layout="wide")


# ----------------------------------------------------------------- utilidades
def f(x, d=4):
    """Formato argentino: coma decimal y punto de miles (0,3306 · 392.641)."""
    return f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def mostrar(fig):
    fig.update_layout(separators=",.")
    st.plotly_chart(fig, width="stretch")


def pct(x, d=1, signo=False):
    return (f"{x * 100:+.{d}f}" if signo else f"{x * 100:.{d}f}").replace(".", ",") + "%"


def pesos(x):
    return "$" + f(x, 0)


@st.cache_data
def cargar():
    nombres = ["gini_serie", "gini_interanual", "lorenz_curvas", "deciles", "brechas", "composicion",
               "theil", "theil_grupos", "calidad_muestra", "validacion", "ipc_trimestral", "deciles_interanual", "gini_serie_larga"]
    d = {n: pd.read_csv(DATA / f"{n}.csv") for n in nombres}
    d["meta"] = json.loads((DATA / "metadata.json").read_text())
    return d


try:
    D = cargar()
except FileNotFoundError:
    st.error("No encontré los datos procesados. Corré primero el ETL (ver README):\n\n"
             "`python src/etl.py --raw data/raw`")
    st.stop()

serie, inter, lor = D["gini_serie"], D["gini_interanual"], D["lorenz_curvas"]
dec, brech, comp = D["deciles"], D["brechas"], D["composicion"]
hay_real = D["deciles"]["ipcf_real"].notna().all()

# ------------------------------------------------------------------- sidebar
st.sidebar.header("Controles")
trim = st.sidebar.selectbox("Trimestre a comparar (2025 vs 2024)", [4, 3, 2, 1],
                            format_func=lambda t: f"T{t} 2025 vs T{t} 2024")
P0, P1 = f"T{trim} 2024", f"T{trim} 2025"
recorte = st.sidebar.radio("Recorte para el detalle", list(REC_LABEL), format_func=REC_LABEL.get)
modo = st.sidebar.radio("Ingresos en", ["Pesos reales", "Pesos corrientes (sin deflactar)"],
                        index=0 if hay_real else 1, disabled=not hay_real)
col_ing = "ipcf_real" if modo == "Pesos reales" and hay_real else "ipcf_nominal"
st.sidebar.caption(
    "**Pesos reales** = ajustados por inflación (IPC INDEC), expresados en pesos del T4 2025. "
    "Es la única forma correcta de comparar ingresos entre años." if hay_real else
    "No se cargó el IPC: los ingresos están en pesos corrientes. Cargá data/external/ipc.csv y volvé a correr el ETL.")
if D["meta"].get("demo"):
    st.sidebar.warning("DATOS SINTÉTICOS DE PRUEBA, no son resultados reales.")

st.sidebar.divider()
st.sidebar.markdown(f"**Población ponderada (PONDIH) · {recorte}**")
_pob = D["calidad_muestra"].set_index(["recorte", "periodo"])["pob_ponderada_pondih"]
for _p in (P0, P1):
    if (recorte, _p) in _pob.index:
        st.sidebar.metric(_p, f"{f(_pob[(recorte, _p)], 0)} habitantes")
st.sidebar.divider()
st.sidebar.markdown(f"[Código fuente en GitHub]({REPO_URL})  \nVersión {VERSION}")

# ---------------------------------------------------------------- encabezado
st.title("¿Cambió la desigualdad de ingresos?")
st.caption("Encuesta Permanente de Hogares (INDEC) · 8 trimestres, 2024-2025 · Ingreso per cápita familiar (IPCF) · "
           "Total urbano EPH y aglomerado Corrientes")

# ----------------------------------------------------- hechos para el relato
def fila_inter(rec):
    return inter.query("trim == @trim and recorte == @rec").iloc[0]


def decil_var(rec):
    a = dec.query("periodo == @P0 and recorte == @rec").set_index("decil")[col_ing]
    b = dec.query("periodo == @P1 and recorte == @rec").set_index("decil")[col_ing]
    return (b / a - 1)


def decil_ic(rec):
    """Variación por decil con IC bootstrap (solo disponible en la base de ingreso del ETL)."""
    d = D["deciles_interanual"].query("trim == @trim and recorte == @rec").set_index("decil")
    return d if (col_ing == "ipcf_real") == (d["base"].iloc[0] == "real") else None


def pp(x, d=2):
    """Puntos porcentuales con signo y formato argentino."""
    return ("+" if x > 0 else "") + f(x, d) + " p. p."


def particion_cambio(rec):
    """Cambio de la participación de cada decil en el ingreso total (puntos porcentuales)."""
    a = dec.query("periodo == @P0 and recorte == @rec").set_index("decil")["pct_ingreso"] * 100
    b = dec.query("periodo == @P1 and recorte == @rec").set_index("decil")["pct_ingreso"] * 100
    return b - a


def relato_participacion(rec):
    dp = particion_cambio(rec)
    top, medio, bajo = dp.loc[10], dp.loc[6:9].sum(), dp.loc[1:5].sum()
    if top < 0:
        destino, val = ("los deciles 6 a 9", medio) if medio >= bajo else ("los deciles 1 a 5", bajo)
        txt = (f"El decil 10 cedió {f(abs(top), 2)} p. p. de participación en el ingreso total y "
               f"esa porción la absorbieron sobre todo {destino} ({pp(val)}).")
    else:
        txt = f"El decil 10 ganó {f(top, 2)} p. p. de participación en el ingreso total."
    return txt + " Son estimaciones puntuales, sin intervalo de confianza: tomarlas como hipótesis."


def veredicto(r, ind="gini"):
    if r[f"{ind}_significativa"]:
        return "subió" if r[f"{ind}_dif"] > 0 else "bajó", True
    return "no mostró un cambio detectable", False


tabs = st.tabs(["1 · Resumen", "2 · Evolución", "3 · Por decil", "4 · Curva de Lorenz",
                "5 · De dónde viene el ingreso", "6 · Metodología y límites", "7 · Datos y descargas"])

# ============================================================ 1 · RESUMEN
with tabs[0]:
    st.subheader(f"Comparación {P1} vs {P0}")
    c1, c2 = st.columns(2)
    for col, rec in zip((c1, c2), ("Corrientes", "Total urbano EPH")):
        r = fila_inter(rec)
        with col:
            st.markdown(f"#### {REC_LABEL[rec]}")
            a, b = st.columns(2)
            a.metric(f"Gini {P0}", f(r["gini_base"]))
            b.metric(f"Gini {P1}", f(r["gini_comp"]), delta=f"{r['gini_dif']:+.4f}".replace(".", ","),
                     delta_color="off")
            txt, sig = veredicto(r)
            (st.success if sig else st.info)(
                f"**Con 95 % de confianza, la desigualdad {txt}.** "
                f"El cambio estimado es de {f(r['gini_dif'])} y el intervalo va de "
                f"{f(r['gini_dif_lo'])} a {f(r['gini_dif_hi'])}"
                + (" (no incluye el cero)." if sig else " (incluye el cero: puede ser solo ruido de la muestra)."))
    st.divider()

    rec = recorte
    r = fila_inter(rec)
    v = decil_var(rec)
    bre0 = brech.query("periodo == @P0 and recorte == @rec").iloc[0]
    bre1 = brech.query("periodo == @P1 and recorte == @rec").iloc[0]
    ic = decil_ic(rec)
    if ic is None:
        texto_sig = ""
    else:
        n_sig = int(ic["significativa"].sum())
        if n_sig == 10:
            texto_sig = "Los 10 deciles muestran una variación estadísticamente distinguible de cero (IC 95 %)."
        else:
            cuantos = "ninguno" if n_sig == 0 else f"solo {n_sig}"
            texto_sig = (f"**Ojo:** de los 10 deciles, {cuantos} muestra{'n' if n_sig > 1 else ''} una variación estadísticamente "
                         "distinguible de cero (IC 95 %). En el resto, la diferencia puede ser ruido de la muestra: "
                         "no conviene afirmar quién ganó o perdió.")
    unidad = "reales" if col_ing == "ipcf_real" else "corrientes (sin descontar inflación)"

    # --- tablero: todos los indicadores, los que suben y los que bajan
    sr = serie.set_index(["recorte", "periodo"])
    ind = [("Índice de Gini", sr.loc[(rec, P0), "gini"], sr.loc[(rec, P1), "gini"], 4),
           ("Ratio de Palma", sr.loc[(rec, P0), "palma"], sr.loc[(rec, P1), "palma"], 2),
           ("Brecha D10 / D1", bre0["D10_D1"], bre1["D10_D1"], 2),
           ("Brecha D9 / D1", bre0["D9_D1"], bre1["D9_D1"], 2),
           ("Brecha D10 / D5", bre0["D10_D5"], bre1["D10_D5"], 2),
           ("Participación del decil 10 (%)", bre0["pct_ingreso_decil10"] * 100,
            bre1["pct_ingreso_decil10"] * 100, 1)]
    filas_ind = [{"Indicador": n, P0: f(a_, d_), P1: f(b__, d_),
                  "Variación": ("+" if b__ > a_ else "") + f(b__ - a_, d_),
                  "Sentido": "Sube" if b__ > a_ else ("Baja" if b__ < a_ else "Sin cambio")}
                 for n, a_, b__, d_ in ind]
    suben = [n for n, a_, b__, _ in ind if b__ > a_]
    bajan = [n for n, a_, b__, _ in ind if b__ < a_]
    st.subheader(f"Indicadores que suben y que bajan · {REC_LABEL[rec]}")
    st.dataframe(pd.DataFrame(filas_ind), hide_index=True, width="stretch")
    st.markdown(f"**Suben ({len(suben)}):** {', '.join(suben) or 'ninguno'}.  \n"
                f"**Bajan ({len(bajan)}):** {', '.join(bajan) or 'ninguno'}.")
    st.markdown(relato_participacion(rec))
    st.caption("Los indicadores se leen en conjunto: que la brecha con el decil 1 suba mientras la brecha con el decil 5 "
               "y la participación del decil 10 bajan indica que el cambio no fue uniforme. "
               "Salvo el Gini, estos valores se informan como estimaciones puntuales.")
    st.subheader(f"Aspectos claves del análisis · {REC_LABEL[rec]}")
    st.markdown(f"""
**1. ¿Qué medimos?** Cómo se reparte el ingreso entre las personas, usando el ingreso per cápita de su hogar.
Ordenamos a la población de menor a mayor ingreso y la dividimos en 10 grupos iguales (*deciles*).

**2. ¿Qué encontramos en la desigualdad total?** El índice de Gini ({f(r['gini_base'])} → {f(r['gini_comp'])}) 
{veredicto(r)[0]} entre {P0} y {P1}. {"La diferencia es estadísticamente distinguible de cero." if veredicto(r)[1] else "La diferencia es chica frente al error de medición de una encuesta: lo honesto es decir que no hay cambio detectable."}

**3. ¿Qué pasó en los extremos?** El ingreso del decil más rico representó {pct(bre0['pct_ingreso_decil10'])} del total
en {P0} y {pct(bre1['pct_ingreso_decil10'])} en {P1}. La brecha entre el decil 10 y el decil 1 pasó de
{f(bre0['D10_D1'], 2)} a {f(bre1['D10_D1'], 2)} veces; contra el decil 5, de {f(bre0['D10_D5'], 2)} a {f(bre1['D10_D5'], 2)} veces.
De los {len(ind)} indicadores, {len(suben)} suben y {len(bajan)} bajan. {relato_participacion(rec)}

**4. ¿Y el bolsillo?** En pesos {unidad}, el ingreso promedio del decil más pobre varió {pct(v[1], 1, True)} y el del más rico {pct(v[10], 1, True)}.
El decil con mejor desempeño fue el {int(v.idxmax())} ({pct(v.max(), 1, True)}) y el de peor desempeño, el {int(v.idxmin())} ({pct(v.min(), 1, True)}).
{texto_sig}

**5. Cautela.** Es una encuesta por muestreo, no un censo: por eso mostramos intervalos de confianza.
""")
    if col_ing == "ipcf_nominal":
        st.warning("Estas variaciones están en pesos corrientes: con inflación alta, un aumento nominal puede ser "
                   "una caída real. Activá *Pesos reales* en la barra lateral.")
    with st.expander("En palabras simples: ¿qué es el Gini?"):
        st.markdown("Es un número entre 0 y 1. **0** = todos ganan lo mismo; **1** = una sola persona se queda con todo. "
                    "Valores más altos = más desigualdad. Se interpreta mejor *comparando* (entre años o entre lugares) "
                    "que mirando un valor aislado.")

# ============================================================ 2 · EVOLUCIÓN
with tabs[1]:
    st.subheader("Evolución trimestral del Gini, con intervalo de confianza del 95 %")
    st.caption("Cada punto es una estimación con su margen de error (la barra). "
               "Si dos barras se solapan, no se puede afirmar que la desigualdad sea distinta.")
    fig = go.Figure()
    for rec_, col in REC_COLOR.items():
        s = serie[serie.recorte == rec_].set_index("periodo").loc[PERIODOS]
        fig.add_trace(go.Scatter(
            x=PERIODOS, y=s["gini"], mode="lines+markers", name=REC_LABEL[rec_], line=dict(color=col),
            error_y=dict(type="data", symmetric=False, array=s["gini_hi"] - s["gini"],
                         arrayminus=s["gini"] - s["gini_lo"], thickness=1.5)))
    fig.update_layout(yaxis_title="Índice de Gini", height=430, legend=dict(orientation="h", y=1.1),
                      margin=dict(t=30))
    mostrar(fig)

    st.subheader("Ratio de Palma")
    st.caption("Ingreso del 10 % más rico dividido el ingreso del 40 % más pobre. "
               "Ejemplo: 1,5 significa que el 10 % de arriba gana 1,5 veces lo que gana todo el 40 % de abajo.")
    figp = go.Figure()
    for rec_, col in REC_COLOR.items():
        s = serie[serie.recorte == rec_].set_index("periodo").loc[PERIODOS]
        figp.add_trace(go.Scatter(
            x=PERIODOS, y=s["palma"], mode="lines+markers", name=REC_LABEL[rec_], line=dict(color=col),
            error_y=dict(type="data", symmetric=False, array=s["palma_hi"] - s["palma"],
                         arrayminus=s["palma"] - s["palma_lo"], thickness=1.5)))
    figp.update_layout(yaxis_title="Palma", height=380, legend=dict(orientation="h", y=1.1), margin=dict(t=30))
    mostrar(figp)

    st.subheader("Serie larga: Gini del cuarto trimestre, 2020-2025")
    st.caption("Mismo trimestre de cada año (T4), para evitar efectos estacionales. Sirve para ver si un cambio "
               "de un año al otro es tendencia o ruido: compará el tamaño del movimiento con el de las barras.")
    SL = D["gini_serie_larga"].sort_values("anio")
    figl = go.Figure()
    for rec_, col in REC_COLOR.items():
        s_ = SL[SL.recorte == rec_]
        figl.add_trace(go.Scatter(
            x=s_["anio"].astype(str), y=s_["gini"], mode="lines+markers", name=REC_LABEL[rec_], line=dict(color=col),
            error_y=dict(type="data", symmetric=False, array=s_["gini_hi"] - s_["gini"],
                         arrayminus=s_["gini"] - s_["gini_lo"], thickness=1.5)))
    figl.update_layout(xaxis_title="Cuarto trimestre de cada año", yaxis_title="Índice de Gini", height=400,
                       legend=dict(orientation="h", y=1.1), margin=dict(t=30))
    mostrar(figl)
    sc = SL[SL.recorte == "Corrientes"].set_index("anio")["gini"]
    su = SL[SL.recorte == "Total urbano EPH"].set_index("anio")["gini"]
    st.info(f"Entre el T4 {sc.index.min()} y el T4 {sc.index.max()}, el Gini de Corrientes pasó de {f(sc.iloc[0])} a {f(sc.iloc[-1])} "
            f"y el del Total urbano de {f(su.iloc[0])} a {f(su.iloc[-1])}. En ese contexto, el cambio entre T4 2024 y T4 2025 "
            f"({f(sc.loc[2025] - sc.loc[2024])} en Corrientes) es muy chico.")

    st.subheader("Variación interanual (mismo trimestre, 2025 vs 2024)")
    t = inter.copy()
    t["¿Cambio detectable?"] = np.where(t["gini_significativa"], "Sí", "No")
    t = t.assign(Trimestre=t["trim"].map(lambda k: f"T{k}"), Recorte=t["recorte"].map(REC_LABEL),
                 **{"Gini 2024": t["gini_base"].map(f), "Gini 2025": t["gini_comp"].map(f),
                    "Variación": t["gini_dif"].map(lambda v: f(v).replace("-", "−") if v < 0 else "+" + f(v)),
                    "IC 95 %": t.apply(lambda r: f"[{f(r['gini_dif_lo'])} ; {f(r['gini_dif_hi'])}]", axis=1)})
    st.dataframe(t[["Recorte", "Trimestre", "Gini 2024", "Gini 2025", "Variación", "IC 95 %", "¿Cambio detectable?"]]
                 .sort_values(["Recorte", "Trimestre"]), hide_index=True, width="stretch")
    st.caption("Se compara el mismo trimestre de ambos años para evitar efectos estacionales. "
               "El intervalo trata ambas muestras como independientes; como la EPH repite parte de los hogares, "
               "es un criterio conservador (tiende a ser algo más ancho).")

# ============================================================ 3 · DECILES
with tabs[2]:
    st.subheader(f"¿Cuánto cambió el ingreso de cada decil? · {REC_LABEL[recorte]} · {P1} vs {P0}")
    v = decil_var(recorte)
    ic = decil_ic(recorte)
    err = (dict(type="data", symmetric=False, array=(ic["hi"] - ic["variacion"]).values * 100,
                arrayminus=(ic["variacion"] - ic["lo"]).values * 100) if ic is not None else None)
    fig = go.Figure(go.Bar(x=v.index, y=v.values * 100, marker_color=np.where(v.values >= 0, "#2a9d8f", "#d1495b"),
                           text=[pct(x, 1, True) for x in v.values], textposition="outside" if ic is None else "inside",
                           error_y=err))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(xaxis=dict(title="Decil (1 = más pobre, 10 = más rico)", tickmode="linear"),
                      yaxis_title="Variación del ingreso promedio (%)", height=430, margin=dict(t=30))
    mostrar(fig)
    nota_ing = ("Ingresos en pesos reales (ajustados por inflación). " if col_ing == "ipcf_real" else
                "Atención: ingresos en pesos corrientes: no descuentan inflación. ")
    nota_ic = ("Las barras finas son el intervalo de confianza del 95 %: si cruzan el cero, el cambio no es distinguible de cero. "
               if ic is not None else "En pesos corrientes no se muestra intervalo de confianza. ")
    st.caption(nota_ing + "Verde = el decil ganó poder de compra; rojo = lo perdió. " + nota_ic +
               "Con pocas observaciones por decil (sobre todo en Corrientes) los intervalos son amplios.")
    if ic is not None:
        st.info(f"{int(ic['significativa'].sum())} de 10 deciles tienen un cambio estadísticamente distinguible de cero en {REC_LABEL[recorte]}.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Participación de cada decil en el ingreso total**")
        figd = go.Figure()
        for per, col in ((P0, "#9bb7d4"), (P1, REC_COLOR[recorte])):
            d = dec.query("periodo == @per and recorte == @recorte").sort_values("decil")
            figd.add_trace(go.Bar(x=d["decil"], y=d["pct_ingreso"] * 100, name=per, marker_color=col))
        figd.update_layout(barmode="group", xaxis=dict(tickmode="linear", title="Decil"),
                           yaxis_title="% del ingreso total", height=380, legend=dict(orientation="h", y=1.1))
        mostrar(figd)
    with c2:
        st.markdown("**Brechas entre deciles**")
        b = brech.query("recorte == @recorte and periodo in [@P0, @P1]").set_index("periodo")
        b = b[["D10_D1", "D9_D1", "D10_D5", "pct_ingreso_decil10"]].rename(columns={
            "D10_D1": "D10 / D1", "D9_D1": "D9 / D1", "D10_D5": "D10 / D5", "pct_ingreso_decil10": "% ingreso decil 10"})
        b["% ingreso decil 10"] = b["% ingreso decil 10"] * 100
        st.dataframe(b.map(lambda v: f(v, 2)), width="stretch")
        st.caption("D10/D1: cuántas veces gana el decil más rico respecto del más pobre.")
        tabla = dec.query("recorte == @recorte and periodo in [@P0, @P1]").pivot(
            index="decil", columns="periodo", values=col_ing)[[P0, P1]]
        st.markdown(f"**Ingreso per cápita promedio por decil** ({'pesos reales' if col_ing == 'ipcf_real' else 'pesos corrientes'})")
        st.dataframe(tabla.map(pesos), width="stretch")

    dp = particion_cambio(recorte)
    figdp = go.Figure(go.Bar(x=dp.index, y=dp.values, marker_color=np.where(dp.values >= 0, "#2a9d8f", "#d1495b"),
                             text=[pp(x, 2) for x in dp.values], textposition="outside"))
    figdp.add_hline(y=0, line_color="gray")
    figdp.update_layout(xaxis=dict(title="Decil (1 = más pobre, 10 = más rico)", tickmode="linear"),
                        yaxis_title="Cambio en la participación (puntos porcentuales)", height=380, margin=dict(t=30))
    st.markdown(f"**¿Quién ganó y quién cedió participación? ({P1} menos {P0})**")
    mostrar(figdp)
    st.caption("Una caída de la participación del decil 10 se compensa con aumentos en otros deciles: "
               "este gráfico muestra hacia dónde se movió esa porción del ingreso total.")

# ============================================================ 4 · LORENZ
with tabs[3]:
    st.subheader(f"¿En qué tramo de la distribución cambió algo? · {REC_LABEL[recorte]}")
    st.caption("Las curvas de Lorenz de dos años son casi idénticas a simple vista; por eso graficamos su **diferencia**. "
               "Por encima de cero: ese tramo de la población acumula una porción mayor del ingreso (más igualdad). "
               "Por debajo: menor.")
    a = lor.query("periodo == @P0 and recorte == @recorte").set_index("pob_acum")["ing_acum"]
    b_ = lor.query("periodo == @P1 and recorte == @recorte").set_index("pob_acum")["ing_acum"]
    dif = (b_ - a) * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dif.index, y=dif.clip(lower=0).values, mode="none", fill="tozeroy",
                             fillcolor="rgba(42,157,143,0.35)", name="Más igualdad", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=dif.index, y=dif.clip(upper=0).values, mode="none", fill="tozeroy",
                             fillcolor="rgba(209,73,91,0.35)", name="Menos igualdad", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=dif.index, y=dif.values, mode="lines", name="Diferencia",
                             line=dict(color=REC_COLOR[recorte], width=3),
                             hovertemplate="Percentil %{x:.0%}: %{y:,.3f} p. p.<extra></extra>"))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(xaxis=dict(title="Percentil de la población (ordenada de menor a mayor ingreso)", tickformat=".0%"),
                      yaxis_title=f"Lorenz {P1} − Lorenz {P0} (puntos porcentuales)", height=430, margin=dict(t=30))
    mostrar(fig)
    _imax, _imin = dif.idxmax(), dif.idxmin()
    st.markdown(f"La diferencia es máxima en el percentil {int(round(_imax * 100))} ({pp(dif.max(), 3)}) y mínima en el "
                f"percentil {int(round(_imin * 100))} ({pp(dif.min(), 3)}). "
                f"La curva cruza el cero en {int((np.diff(np.sign(dif.values[1:-1])) != 0).sum())} punto(s) interiores: "
                "los tramos en verde acumulan más ingreso en " + P1 + " que en " + P0 + "; los rojos, menos.")
    st.caption("Esta diferencia es una estimación puntual: las magnitudes son de décimas o centésimas de punto porcentual, "
               "coherentes con un Gini cuyo cambio no es distinguible de cero.")
    with st.expander("Ver las dos curvas de Lorenz (casi superpuestas)"):
        fl = go.Figure([go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Igualdad perfecta",
                                   line=dict(dash="dash", color="gray"))])
        for per, col in ((P0, "#9bb7d4"), (P1, REC_COLOR[recorte])):
            d = lor.query("periodo == @per and recorte == @recorte")
            fl.add_trace(go.Scatter(x=d["pob_acum"], y=d["ing_acum"], mode="lines", name=per, line=dict(color=col, width=3)))
        fl.update_layout(xaxis=dict(title="% de población acumulada", tickformat=".0%"),
                         yaxis=dict(title="% de ingreso acumulado", tickformat=".0%"), height=420)
        mostrar(fl)

# ============================================================ 5 · COMPOSICIÓN
with tabs[4]:
    st.subheader(f"¿De dónde viene el ingreso de cada decil? · {REC_LABEL[recorte]}")
    per_c = st.select_slider("Trimestre", PERIODOS, value=P1)
    c = comp.query("periodo == @per_c and recorte == @recorte")
    colores = {"Laboral": "#2e6f95", "Jubilaciones y pensiones": "#8d99ae",
               "Transferencias (subsidios, seguro desempleo)": "#d1495b", "Otros no laborales": "#cbd5c0"}
    fig = go.Figure()
    for k, col in colores.items():
        d = c[c.componente == k].sort_values("decil")
        fig.add_trace(go.Bar(x=d["decil"], y=d["participacion"] * 100, name=k, marker_color=col))
    fig.update_layout(barmode="stack", xaxis=dict(tickmode="linear", title="Decil (1 = más pobre)"),
                      yaxis_title="% del ingreso del decil", height=450, legend=dict(orientation="h", y=-0.25))
    mostrar(fig)
    bajos = c[c.decil <= 3].groupby("componente")["participacion"].mean()
    st.info(f"En los 3 deciles más bajos, en promedio, las **transferencias** aportan "
            f"{pct(bajos.get('Transferencias (subsidios, seguro desempleo)', 0))} del ingreso declarado y los "
            f"**ingresos laborales** {pct(bajos.get('Laboral', 0))}.")
    st.caption("Se construye con los ingresos individuales declarados de los miembros del hogar (sin imputar no respuesta). "
               "‘Transferencias’ = subsidios o ayuda social en dinero (V5, suma de V5_01_M a V5_03_M en las bases 2024-2025) + "
               "seguro de desempleo (V4_M). ‘Jubilaciones’ suma V2_01_M a V2_03_M.")

    st.subheader("Desigualdad dentro y entre grupos (índice de Theil)")
    th = D["theil"].query("periodo == @per_c and recorte == @recorte").iloc[0]
    st.markdown(f"Hogares agrupados según la **condición laboral del jefe/a**: del Theil total ({f(th['theil'])}), "
                f"**{pct(th['pct_entre'])}** es desigualdad *entre* grupos y el resto es desigualdad *dentro* de cada grupo.")
    tg = D["theil_grupos"].query("periodo == @per_c and recorte == @recorte").copy()
    tg["pob_pct"] = (tg["pob_pct"] * 100).map(lambda v: f(v, 1))
    tg["ipcf_medio"] = tg["ipcf_medio"].map(pesos)
    st.dataframe(tg[["grupo", "pob_pct", "ipcf_medio"]].rename(columns={
        "grupo": "Grupo", "pob_pct": "% de personas", "ipcf_medio": "IPCF medio (corriente)"}),
        hide_index=True, width="stretch")

# ============================================================ 6 · METODOLOGÍA
with tabs[5]:
    st.subheader("Metodología")
    st.markdown("""
- **Fuente:** microdatos de la EPH-INDEC, bases individuales de los trimestres T1-T4 de 2024 y 2025.
- **Unidad de análisis:** la **persona**, a la que se le asigna el IPCF (ingreso per cápita familiar) de su hogar.
- **Ponderador:** `PONDIH`. **Filtro de calidad:** `DECCFR` entre 1 y 10 (se excluyen hogares sin ingreso declarado o sin respuesta).
- **Recortes:** *Total urbano EPH* = los 31 aglomerados que releva la EPH (no es el total del país). *Corrientes* = aglomerado 12.
- **Deciles locales:** se recalculan dentro de cada recorte, agrupando primero por valor de IPCF para no partir hogares con ingreso idéntico.
- **Ingresos reales:** IPC nacional nivel general (INDEC), promedio del trimestre con rezago de un mes
  (el ingreso se declara por el mes anterior), expresado en pesos del T4 2025. La serie (`data/external/ipc.csv`) se
  reconstruyó con las variaciones mensuales del INDEC y coincide con las cifras oficiales de 2024 (117,8 %) y 2025 (31,5 %).
- **Intervalos de confianza:** *bootstrap* de hogares con los ponderadores `PONDIH` (500 réplicas), percentiles 2,5 y 97,5.
- **Composición del ingreso:** ingresos individuales declarados de cada decil: laboral (`P21` + `TOT_P12`), jubilaciones (`V2`), transferencias (`V5` + `V4`) y otros no laborales (resto de `P47T`). En las bases 2024-2025 `V2` y `V5` vienen abiertas en tres subcomponentes que se suman.
- **Theil:** hogares agrupados por la condición laboral del jefe/a; se descompone en desigualdad entre y dentro de grupos.
- **Palma:** se calcula sobre la curva de Lorenz (cortes exactos en 40 % y 90 %); las brechas entre deciles usan los deciles locales por grupos de IPCF idéntico, por lo que pueden diferir levemente (≈2 %) de un cálculo por cortes exactos.
""")
    st.latex(r"G = 1 - \sum_{i=1}^{n} (p_i - p_{i-1})\,(L_i + L_{i-1})")
    st.latex(r"\text{Palma} = \frac{\text{ingreso del 10\% más rico}}{\text{ingreso del 40\% más pobre}}")
    st.latex(r"\frac{D_{10}}{D_1} = \frac{\bar y_{10}}{\bar y_{1}}\qquad \frac{D_{9}}{D_1} = \frac{\bar y_{9}}{\bar y_{1}}"
             r"\qquad \frac{D_{10}}{D_5} = \frac{\bar y_{10}}{\bar y_{5}}\qquad \bar y_d = \frac{\sum_{i\in d} w_i\,y_i}{\sum_{i\in d} w_i}")
    st.latex(r"T = \sum_g s_g\frac{\mu_g}{\mu}T_g \;+\; \sum_g s_g\frac{\mu_g}{\mu}\ln\frac{\mu_g}{\mu}"
             r"\quad(\text{dentro} + \text{entre grupos})")
    st.subheader("Enfoque Metodológico y Alcance")
    st.markdown("""
1. La EPH es una muestra: un cambio dentro del margen de error **no es** un hallazgo.
2. Ocho trimestres permiten ver una dinámica corta; la serie de cuartos trimestres 2020-2025 da más contexto, pero son 6 puntos y el T4 2020 está afectado por la pandemia.
3. Se comparan los mismos trimestres de años distintos para evitar estacionalidad.
4. El IPC es nacional; Corrientes puede haber tenido una inflación distinta.
5. Los ingresos de la EPH se subdeclaran, sobre todo en la cima: el Gini de encuestas tiende a subestimar la desigualdad real.

""")
    st.subheader("Fuente, fecha y reproducibilidad")
    arch = pd.DataFrame({"Trimestre": list(D["meta"]["archivos"]), "Archivo EPH (base individual)": list(D["meta"]["archivos"].values())})
    fd = D["meta"].get("fechas_descarga", {})
    arch["Fecha de descarga"] = arch["Trimestre"].map(lambda k: (lambda d: f"{d[8:]}/{d[5:7]}/{d[:4]}")(fd[k]) if k in fd else "sin dato")
    arch = arch.assign(_k=arch["Trimestre"].str[-4:] + arch["Trimestre"].str[1]).sort_values("_k").drop(columns="_k")
    st.dataframe(arch, hide_index=True, width="stretch")
    st.markdown(f"""
- **Fuente:** INDEC, Encuesta Permanente de Hogares, bases de microdatos usu_individual. La fecha de descarga de cada base figura en la tabla de arriba.
- **Versión del tablero:** {VERSION}.
- **Procesamiento:** {D['meta']['generado']} · {D['meta']['bootstrap_B']} réplicas bootstrap · semilla {D['meta']['semilla']}.
- **Código y datos:** [https://github.com/ccelesteccoronel/DASHBOARD-GRUPO5]({REPO_URL}) (`src/etl.py` reproduce todo desde las bases oficiales).
""")
    st.subheader("Calidad de la muestra")
    _q = D["calidad_muestra"].set_index(["recorte", "periodo"])
    if (recorte, P1) in _q.index:
        _r = _q.loc[(recorte, P1)]
        st.markdown(f"En {REC_LABEL[recorte]} y {P1}, el filtro de `DECCFR` (valores 0 y 12) excluyó "
                    f"{f(_r['personas_total'] - _r['personas_validas'], 0)} de {f(_r['personas_total'], 0)} personas "
                    f"({f(_r['pct_personas_excluidas'] * 100, 1)} %) y {f(_r['hogares_total'] - _r['hogares_validos'], 0)} de "
                    f"{f(_r['hogares_total'], 0)} hogares ({f(_r['pct_hogares_excluidos'] * 100, 1)} %). "
                    "La tabla siguiente detalla todos los trimestres y recortes.")
    cm = D["calidad_muestra"].copy()
    cm["_a"] = cm["periodo"].str[-4:].astype(int)
    cm["_t"] = cm["periodo"].str[1].astype(int)
    cm = cm.sort_values(["recorte", "_a", "_t"]).drop(columns=["_a", "_t"])
    for k in ("pct_personas_excluidas", "pct_hogares_excluidos", "pct_pob_excluida_pondera"):
        cm[k] = (cm[k] * 100).map(lambda v: f(v, 1))
    for k in ("personas_total", "personas_validas", "hogares_total", "hogares_validos", "pob_ponderada_pondih"):
        cm[k] = cm[k].map(lambda v: f(v, 0))
    st.dataframe(cm.rename(columns={
        "personas_total": "Personas (total)", "personas_validas": "Personas válidas",
        "hogares_total": "Hogares (total)", "hogares_validos": "Hogares válidos",
        "pct_personas_excluidas": "% personas excluidas", "pct_hogares_excluidos": "% hogares excluidos",
        "pct_pob_excluida_pondera": "% pob. excluida (PONDERA)", "pob_ponderada_pondih": "Pob. ponderada (PONDIH)"}),
        hide_index=True, width="stretch")
    st.subheader("Verificación contra la versión anterior del proyecto")
    v = D["validacion"].copy()
    v["coincide"] = np.where(v["coincide"], "Sí", "No")
    for k in ("referencia", "calculado"):
        v[k] = v[k].map(lambda x: f(x, 0) if x > 1000 else f(x, 6))
    v["diferencia"] = v["diferencia"].map(lambda x: f(x, 6))
    st.dataframe(v, hide_index=True, width="stretch")
    st.caption(f"Generado: {D['meta']['generado']} · Réplicas bootstrap: {D['meta']['bootstrap_B']} · "
               f"Rezago IPC: {D['meta']['lag_ipc_meses']} mes(es). Fuente: INDEC, EPH. Elaboración propia.")


# ============================================================ 7 · DATOS Y DESCARGAS
FUENTES = {
    "gini_serie.csv": ("Gini y Palma por trimestre y recorte, con intervalo de confianza 95 % (T1 2024 a T4 2025)", DATA),
    "gini_serie_larga.csv": ("Gini y Palma del cuarto trimestre, 2020 a 2025, con intervalo de confianza", DATA),
    "gini_interanual.csv": ("Variación interanual del Gini y Palma por trimestre, con IC y marca de cambio detectable", DATA),
    "deciles.csv": ("Ingreso per cápita promedio (corriente y real) y participación en el ingreso por decil", DATA),
    "deciles_interanual.csv": ("Variación interanual del ingreso por decil, con IC bootstrap", DATA),
    "brechas.csv": ("Brechas D10/D1, D9/D1, D10/D5 y participación del decil 10", DATA),
    "lorenz_curvas.csv": ("Curva de Lorenz (101 puntos) por trimestre y recorte", DATA),
    "composicion.csv": ("Composición del ingreso por decil: laboral, jubilaciones, transferencias, otros", DATA),
    "theil.csv": ("Índice de Theil total y su descomposición entre/dentro de grupos", DATA),
    "theil_grupos.csv": ("Participación poblacional e ingreso medio de cada grupo de la descomposición de Theil", DATA),
    "calidad_muestra.csv": ("Casos totales y válidos, hogares excluidos por el filtro DECCFR y no respuesta", DATA),
    "validacion.csv": ("Verificación contra los valores de la versión anterior del proyecto", DATA),
    "ipc_trimestral.csv": ("IPC promedio por trimestre y factor para expresar en pesos del T4 2025", DATA),
    "ipc.csv": ("Serie mensual del IPC nacional usada para deflactar (data/external)", DATA.parent.parent / "data" / "external"),
}


def csv_bytes(df, excel_ar):
    if excel_ar:
        return df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
    return df.to_csv(index=False).encode("utf-8")


with tabs[6]:
    st.subheader("Datos utilizados en el tablero")
    st.markdown("Todas las tablas que alimentan los gráficos se pueden descargar en CSV. Son resultados procesados "
                "a partir de los microdatos de la EPH; las bases originales no se incluyen por su tamaño y se bajan del INDEC.")
    formato = st.radio("Formato del CSV", ["Estándar (coma separadora, punto decimal)", "Excel en español (punto y coma, coma decimal)"])
    excel_ar = formato.startswith("Excel")
    sufijo = "_excel_ar" if excel_ar else ""
    tablas = {n: pd.read_csv(ruta / n) for n, (_, ruta) in FUENTES.items() if (ruta / n).exists()}
    for nombre, df_ in tablas.items():
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"**{nombre}** · {FUENTES[nombre][0]} ({f(len(df_), 0)} filas)")
        c2.download_button("Descargar CSV", csv_bytes(df_, excel_ar), file_name=nombre.replace(".csv", f"{sufijo}.csv"),
                           mime="text/csv", key=f"dl_{nombre}", width="stretch")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, df_ in tablas.items():
            z.writestr(nombre.replace(".csv", f"{sufijo}.csv"), csv_bytes(df_, excel_ar))
    st.download_button("Descargar todas las tablas (ZIP)", buf.getvalue(), file_name=f"datos_grupo5{sufijo}.zip",
                       mime="application/zip", type="primary")
    st.markdown("**Microdatos originales:** [INDEC · Bases de microdatos EPH]"
                "(https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos). "
                f"Código para reproducir todo: [repositorio]({REPO_URL}).")
    with st.expander("Diccionario de las columnas más usadas"):
        st.markdown("""
- **periodo / anio / trim:** trimestre de la EPH. **recorte:** *Corrientes* (aglomerado 12) o *Total urbano EPH* (31 aglomerados).
- **gini, palma:** índices de desigualdad; **`_lo` y `_hi`:** límites del intervalo de confianza del 95 %.
- **ipcf_nominal / ipcf_real:** ingreso per cápita familiar promedio del decil, en pesos corrientes y en pesos del T4 2025.
- **pct_ingreso:** participación del decil en el ingreso total (proporción de 0 a 1).
- **variacion, lo, hi, significativa:** cambio interanual, su intervalo de confianza y si excluye el cero.
""")
