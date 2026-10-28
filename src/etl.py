#!/usr/bin/env python
"""
ETL - Dinámica de ingresos y desigualdad (EPH-INDEC) · Grupo 5
================================================================
Procesa las 8 bases individuales de la EPH (T1-T4 de 2024 y 2025) y genera
los CSV livianos que consume el dashboard (data/processed/).

Uso (Colab o local):
    python src/etl.py --raw data/raw --ipc data/external/ipc.csv --boot 500

Archivos esperados en --raw (nombres INDEC, .xlsx o .csv):
    usu_individual_T124, T224, T324, T424, T125, T225, T325, T425

Decisiones metodológicas (todas documentadas en el README):
  * Unidad de análisis: PERSONA, con el IPCF de su hogar. Ponderador PONDIH.
  * Filtro de calidad: DECCFR entre 1 y 10.
  * "Total urbano EPH" = los 31 aglomerados de la EPH (no es el total del país).
  * Corrientes = AGLOMERADO 12. Deciles recalculados dentro de cada recorte.
  * Gini: regla del trapecio sobre la curva de Lorenz.
  * Intervalos de confianza: bootstrap de HOGARES (respeta que los miembros
    de un hogar comparten el mismo IPCF), 95 % percentil.
  * Ingresos reales: IPC nacional nivel general (base dic-2016), pesos del
    último trimestre del análisis.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ANIOS = (2024, 2025)
TRIMS = (1, 2, 3, 4)
AGLO_CORRIENTES = 12
RECORTES = {"Total urbano EPH": None, "Corrientes": AGLO_CORRIENTES}

COLS_OBLIG = ["CODUSU", "NRO_HOGAR", "AGLOMERADO", "IPCF", "DECCFR", "PONDIH"]
COLS_OPC = ["CH03", "ESTADO", "CAT_OCUP", "PP07H", "P21", "TOT_P12", "P47T",
            "T_VI", "V2_M", "V4_M", "V5_M", "PONDERA", "ANO4", "TRIMESTRE",
            "V2_01_M", "V2_02_M", "V2_03_M", "V5_01_M", "V5_02_M", "V5_03_M"]
# Desde 2024 las bases traen V2 (jubilaciones/pensiones) y V5 (subsidios/ayuda social)
# abiertos en subcomponentes; se suman para reconstruir V2_M y V5_M.
DERIVADAS = {"V2_M": ["V2_01_M", "V2_02_M", "V2_03_M"], "V5_M": ["V5_01_M", "V5_02_M", "V5_03_M"]}
COLS_NUM = [c for c in COLS_OBLIG + COLS_OPC if c not in ("CODUSU",)]

IPC_URL = ("https://apis.datos.gob.ar/series/api/series/"
           "?ids=148.3_INIVELNAL_DICI_M_26&format=csv&limit=1000")
# Fecha en que el grupo descargó cada base del INDEC (completar las que falten)
FECHAS_DESCARGA = {f"T{t} {a}": ("2026-07-22" if t == 4 else "2026-10-13") for a in ANIOS for t in TRIMS}
FECHAS_DESCARGA.update({f"T4 {a}": "2026-10-13" for a in range(2020, 2024)})
IPC_DIC_25_VS_DIC_24 = 1.315  # INDEC: inflación dic-25 / dic-24 = 31,5 %

# Valores de referencia de la versión anterior del proyecto (README del repo)
REFERENCIAS = [
    ("Gini Total urbano T4 2024", "T4 2024", "Total urbano EPH", "gini", 0.428276),
    ("Gini Total urbano T4 2025", "T4 2025", "Total urbano EPH", "gini", 0.424758),
    ("Gini Corrientes T4 2024", "T4 2024", "Corrientes", "gini", 0.330571),
    ("Gini Corrientes T4 2025", "T4 2025", "Corrientes", "gini", 0.335805),
    ("Población ponderada Corrientes T4 2024", "T4 2024", "Corrientes", "pob", 392641),
    ("Población ponderada Corrientes T4 2025", "T4 2025", "Corrientes", "pob", 395388),
]


def etiqueta(anio: int, trim: int) -> str:
    return f"T{trim} {anio}"


# ----------------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------------
def _num(s: pd.Series) -> pd.Series:
    if s.dtype == object:
        s = s.astype(str).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def leer_base(path: Path) -> pd.DataFrame:
    usar = lambda c: str(c).strip().upper() in COLS_OBLIG + COLS_OPC  # noqa: E731
    if path.suffix.lower() in (".csv", ".txt"):
        df = pd.read_csv(path, sep=None, engine="python", usecols=usar)
    else:
        df = pd.read_excel(path, usecols=usar)
    df.columns = [str(c).strip().upper() for c in df.columns]
    faltan = [c for c in COLS_OBLIG if c not in df.columns]
    if faltan:
        raise ValueError(f"{path.name}: faltan columnas obligatorias {faltan}")
    sub = {p for ps in DERIVADAS.values() for p in ps}
    for c in COLS_OPC:
        if c not in df.columns:
            if c not in sub and c not in DERIVADAS and c not in ("ANO4", "TRIMESTRE"):
                print(f"   aviso: {path.name} no tiene {c}; se completa con 0/NaN")
            df[c] = np.nan
    for c in COLS_NUM:
        df[c] = _num(df[c])
    for tot, partes in DERIVADAS.items():
        if df[tot].isna().all():
            df[tot] = df[partes].fillna(0).sum(axis=1)
    df["CODUSU"] = df["CODUSU"].astype(str).str.strip()
    df["HOGAR"] = df["CODUSU"] + "_" + df["NRO_HOGAR"].astype("Int64").astype(str)
    return df


def buscar_archivo(raw: Path, trim: int, anio: int) -> Path:
    cod = f"T{trim}{str(anio)[2:]}"
    for p in sorted(raw.glob("*")):
        n = p.name.lower()
        if "individual" in n and f"_{cod.lower()}" in n:
            return p
    raise FileNotFoundError(f"No encontré usu_individual_{cod} en {raw}")


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
def lorenz_ordenada(xs: np.ndarray, ws: np.ndarray):
    """Curva de Lorenz con datos YA ordenados por ingreso."""
    cw = np.cumsum(ws)
    cy = np.cumsum(xs * ws)
    p = np.r_[0.0, cw / cw[-1]]
    L = np.r_[0.0, cy / cy[-1]]
    return p, L


def gini_de_lorenz(p: np.ndarray, L: np.ndarray) -> float:
    """Regla del trapecio: G = 1 - sum (p_i - p_{i-1}) (L_i + L_{i-1})."""
    return float(1.0 - np.sum(np.diff(p) * (L[1:] + L[:-1])))


def palma_de_lorenz(p: np.ndarray, L: np.ndarray) -> float:
    """Palma = ingreso del 10 % más rico / ingreso del 40 % más pobre."""
    l40, l90 = np.interp([0.4, 0.9], p, L)
    return float((1.0 - l90) / l40)


def gini(x, w) -> float:
    o = np.argsort(x, kind="stable")
    return gini_de_lorenz(*lorenz_ordenada(np.asarray(x, float)[o], np.asarray(w, float)[o]))


def bootstrap(xs, ws, hhs, B, rng):
    """Bootstrap de hogares sobre datos ordenados por ingreso.
    -> (B,2) gini y palma, y (B,10) ingreso medio por decil (mismo criterio de
    asignación de deciles que el estimador puntual)."""
    n_hog = hhs.max() + 1
    out, dmed = np.empty((B, 2)), np.full((B, 10), np.nan)
    ultimo = np.r_[xs[1:] != xs[:-1], True]            # fin de cada grupo de IPCF idéntico
    fin = np.minimum.accumulate(np.where(ultimo, np.arange(len(xs)), len(xs))[::-1])[::-1]
    for b in range(B):
        cnt = np.bincount(rng.integers(0, n_hog, n_hog), minlength=n_hog)
        wb = ws * cnt[hhs]
        p, L = lorenz_ordenada(xs, wb)
        out[b] = gini_de_lorenz(p, L), palma_de_lorenz(p, L)
        cum = np.cumsum(wb)
        dec = np.clip(np.ceil(cum[fin] / cum[-1] * 10 - 1e-9), 1, 10).astype(int)
        sw = np.bincount(dec, weights=wb, minlength=11)[1:]
        sxw = np.bincount(dec, weights=wb * xs, minlength=11)[1:]
        dmed[b] = np.where(sw > 0, sxw / np.where(sw > 0, sw, 1), np.nan)
    return out, dmed


def asignar_deciles(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Deciles locales. Agrupa por valor de IPCF sumando PONDIH ANTES de acumular
    población (evita partir al azar un grupo con IPCF idéntico entre dos deciles)."""
    g = pd.DataFrame({"x": x, "w": w}).groupby("x", as_index=False)["w"].sum()
    g = g.sort_values("x")
    cum = g["w"].cumsum() / g["w"].sum()
    dec = np.clip(np.ceil(cum.to_numpy() * 10 - 1e-9), 1, 10).astype(int)
    return dec[np.searchsorted(g["x"].to_numpy(), x)]


def theil_t(x, w) -> float:
    mu = np.average(x, weights=w)
    r = x / mu
    return float(np.average(np.where(r > 0, r * np.log(np.where(r > 0, r, 1)), 0), weights=w))


def theil_descomp(x, w, g):
    """Theil T = intra + entre grupos."""
    df = pd.DataFrame({"x": x, "w": w, "g": g})
    df = df[df["x"] > 0]
    mu, W = np.average(df["x"], weights=df["w"]), df["w"].sum()
    filas, intra, entre = [], 0.0, 0.0
    for gr, d in df.groupby("g"):
        s, mg = d["w"].sum() / W, np.average(d["x"], weights=d["w"])
        intra += s * (mg / mu) * theil_t(d["x"].to_numpy(), d["w"].to_numpy())
        entre += s * (mg / mu) * np.log(mg / mu)
        filas.append({"grupo": gr, "pob_pct": s, "ipcf_medio": mg})
    return intra + entre, intra, entre, pd.DataFrame(filas)


def grupo_jefe(df: pd.DataFrame) -> pd.Series:
    """Condición laboral del jefe/a: PP07H (descuento jubilatorio) solo existe
    para asalariados; cuenta propia/patrones no distinguen formalidad."""
    est, cat, jub = df["ESTADO"], df["CAT_OCUP"], df["PP07H"]
    g = pd.Series("Jefe/a sin ocupación", index=df.index)
    g[(est == 1) & cat.isin([1, 2])] = "Jefe/a patrón o cuenta propia"
    g[(est == 1) & (cat == 3) & (jub == 2)] = "Jefe/a asalariado no registrado"
    g[(est == 1) & (cat == 3) & (jub == 1)] = "Jefe/a asalariado registrado"
    g[(est == 1) & (cat == 3) & ~jub.isin([1, 2])] = "Jefe/a asalariado s/d"
    return g


# ----------------------------------------------------------------------------
# IPC
# ----------------------------------------------------------------------------
def cargar_ipc(path: Path) -> pd.DataFrame | None:
    """CSV con columnas mes (YYYY-MM) e indice. Si no existe, lo baja de datos.gob.ar."""
    try:
        if path.exists():
            ipc = pd.read_csv(path)
        else:
            print("   descargando IPC de datos.gob.ar ...")
            with urllib.request.urlopen(IPC_URL, timeout=30) as r:
                ipc = pd.read_csv(io.BytesIO(r.read()))
            ipc.columns = ["mes", "indice"]
            ipc["mes"] = ipc["mes"].astype(str).str[:7]
            path.parent.mkdir(parents=True, exist_ok=True)
            ipc.to_csv(path, index=False)
        ipc["mes"] = ipc["mes"].astype(str).str[:7]
        ipc = ipc.set_index("mes")["indice"].astype(float)
        chk = ipc["2025-12"] / ipc["2024-12"]
        if abs(chk - IPC_DIC_25_VS_DIC_24) > 0.002:
            print(f"   ATENCIÓN: IPC dic-25/dic-24 = {chk:.4f}; INDEC publicó 1,315. "
                  "Revisá la serie.")
        return ipc
    except Exception as e:  # noqa: BLE001
        print(f"   No pude cargar el IPC ({e}). Los ingresos reales quedan vacíos.\n"
              "   Colocá un CSV mes,indice en data/external/ipc.csv y volvé a correr.")
        return None


def ipc_trimestral(ipc, lag: int) -> pd.DataFrame:
    filas = []
    for a in ANIOS:
        for t in TRIMS:
            meses = []
            for m in range(3 * (t - 1) + 1, 3 * t + 1):
                per = pd.Period(f"{a}-{m:02d}", "M") - lag
                meses.append(str(per))
            v = np.nan
            if ipc is not None and all(m in ipc.index for m in meses):
                v = float(np.mean([ipc[m] for m in meses]))
            filas.append({"periodo": etiqueta(a, t), "anio": a, "trim": t, "ipc": v})
    df = pd.DataFrame(filas)
    base = df["ipc"].iloc[-1]
    df["factor_a_pesos_ultimo_trim"] = base / df["ipc"]
    return df


# ----------------------------------------------------------------------------
# Procesamiento por trimestre
# ----------------------------------------------------------------------------
def procesar_periodo(df, periodo, factor, B, rng, comp_sw=True):
    res = {k: [] for k in ["serie", "lorenz", "deciles", "brechas", "comp",
                           "theil", "theil_g", "calidad"]}
    boots = {}
    jefes = df[df["CH03"] == 1].drop_duplicates("HOGAR").copy()
    jefes["GRUPO"] = grupo_jefe(jefes)
    ok_mask = df["DECCFR"].between(1, 10) & df["IPCF"].notna() & (df["IPCF"] >= 0)

    for rec, aglo in RECORTES.items():
        base = df if aglo is None else df[df["AGLOMERADO"] == aglo]
        val = base[ok_mask.loc[base.index]].copy()
        if val.empty:
            print(f"   aviso: {periodo} / {rec} sin casos válidos")
            continue
        # --- calidad de muestra / no respuesta
        pond = base["PONDERA"].fillna(0)
        excl = ~ok_mask.loc[base.index]
        res["calidad"].append({
            "periodo": periodo, "recorte": rec,
            "personas_total": len(base), "personas_validas": len(val),
            "hogares_total": base["HOGAR"].nunique(), "hogares_validos": val["HOGAR"].nunique(),
            "pct_personas_excluidas": excl.mean(),
            "pct_hogares_excluidos": 1 - val["HOGAR"].nunique() / base["HOGAR"].nunique(),
            "pct_pob_excluida_pondera": (pond[excl].sum() / pond.sum()) if pond.sum() > 0 else np.nan,
            "pob_ponderada_pondih": val["PONDIH"].sum(),
        })
        x, w = val["IPCF"].to_numpy(float), val["PONDIH"].to_numpy(float)
        hh = pd.factorize(val["HOGAR"])[0]
        o = np.argsort(x, kind="stable")
        xs, ws, hhs = x[o], w[o], hh[o]
        p, L = lorenz_ordenada(xs, ws)
        g, pal = gini_de_lorenz(p, L), palma_de_lorenz(p, L)
        bt, dm = bootstrap(xs, ws, hhs, B, rng)
        boots[(periodo, rec)] = (bt, dm, factor)
        lo, hi = np.percentile(bt, [2.5, 97.5], axis=0)
        res["serie"].append({
            "periodo": periodo, "recorte": rec, "gini": g, "gini_lo": lo[0], "gini_hi": hi[0],
            "palma": pal, "palma_lo": lo[1], "palma_hi": hi[1],
            "n_personas": len(val), "n_hogares": int(hh.max() + 1),
            "pob_ponderada": w.sum()})
        grid = np.linspace(0, 1, 101)
        res["lorenz"].append(pd.DataFrame({"periodo": periodo, "recorte": rec,
                                           "pob_acum": grid, "ing_acum": np.interp(grid, p, L)}))
        # --- deciles locales
        dec = asignar_deciles(x, w)
        val["DECIL"] = dec
        tot = (x * w).sum()
        d = pd.DataFrame({"x": x, "w": w, "dec": dec}).assign(xw=lambda t: t.x * t.w)
        dd = d.groupby("dec").agg(w=("w", "sum"), xw=("xw", "sum")).reset_index()
        dd["ipcf_nominal"] = dd["xw"] / dd["w"]
        dd["ipcf_real"] = dd["ipcf_nominal"] * factor
        dd["pct_ingreso"] = dd["xw"] / tot
        dd["pob_ponderada"] = dd["w"]
        dd.insert(0, "recorte", rec)
        dd.insert(0, "periodo", periodo)
        res["deciles"].append(dd.rename(columns={"dec": "decil"}).drop(columns=["w", "xw"]))
        m = dd.set_index("dec")["ipcf_nominal"]
        res["brechas"].append({"periodo": periodo, "recorte": rec,
                               "D10_D1": m[10] / m[1], "D9_D1": m[9] / m[1],
                               "D10_D5": m[10] / m[5],
                               "pct_ingreso_decil10": dd.set_index("dec").loc[10, "pct_ingreso"]})
        # --- composición del ingreso por decil (ingresos individuales declarados)
        c = lambda col: val[col].fillna(0).clip(lower=0)  # noqa: E731
        lab = c("P21") + c("TOT_P12")
        jub = c("V2_M")
        trf = c("V4_M") + c("V5_M")
        otros = (c("P47T") - lab - jub - trf).clip(lower=0)
        comp = pd.DataFrame({"decil": dec, "w": w,
                             "Laboral": lab.to_numpy() * w, "Jubilaciones y pensiones": jub.to_numpy() * w,
                             "Transferencias (subsidios, seguro desempleo)": trf.to_numpy() * w,
                             "Otros no laborales": otros.to_numpy() * w})
        cs = comp.groupby("decil").sum().drop(columns="w")
        cs = cs.div(cs.sum(axis=1), axis=0).reset_index().melt("decil", var_name="componente",
                                                              value_name="participacion")
        cs.insert(0, "recorte", rec)
        cs.insert(0, "periodo", periodo)
        res["comp"].append(cs)
        # --- Theil descomponible por condición laboral del jefe/a
        gj = val.merge(jefes[["HOGAR", "GRUPO"]], on="HOGAR", how="left")["GRUPO"].fillna("Jefe/a sin ocupación")
        T, intra, entre, tg = theil_descomp(x, w, gj.to_numpy())
        res["theil"].append({"periodo": periodo, "recorte": rec, "theil": T,
                             "intra_grupos": intra, "entre_grupos": entre,
                             "pct_entre": entre / T if T else np.nan})
        tg.insert(0, "recorte", rec)
        tg.insert(0, "periodo", periodo)
        res["theil_g"].append(tg)
    return res, boots


def correr(args):
    raw, out = Path(args.raw), Path(args.out)
    interim = Path(args.interim)
    out.mkdir(parents=True, exist_ok=True)
    interim.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    ipc = cargar_ipc(Path(args.ipc))
    ipct = ipc_trimestral(ipc, args.lag_ipc)
    ipct.to_csv(out / "ipc_trimestral.csv", index=False)

    acum = {k: [] for k in ["serie", "lorenz", "deciles", "brechas", "comp", "theil", "theil_g", "calidad"]}
    boots, archivos = {}, {}
    for a in ANIOS:
        for t in TRIMS:
            per = etiqueta(a, t)
            f = buscar_archivo(raw, t, a)
            archivos[per] = f.name
            cache = interim / f"{per.replace(' ', '_')}.csv.gz"
            if cache.exists() and not args.no_cache:
                print(f"[{per}] usando caché {cache.name}")
                df = pd.read_csv(cache, dtype={"CODUSU": str})
            else:
                print(f"[{per}] leyendo {f.name} ...")
                df = leer_base(f)
                df.to_csv(cache, index=False)
            if {"ANO4", "TRIMESTRE"} <= set(df.columns) and df["ANO4"].notna().any():
                if not (df["ANO4"].dropna().eq(a).all() and df["TRIMESTRE"].dropna().eq(t).all()):
                    raise ValueError(f"{f.name} no corresponde a {per} (ANO4/TRIMESTRE no coinciden)")
            factor = float(ipct.loc[ipct["periodo"] == per, "factor_a_pesos_ultimo_trim"].iloc[0])
            r, b = procesar_periodo(df, per, factor, args.boot, rng)
            boots.update(b)
            for k in acum:
                acum[k].extend(r[k])

    def a_df(lst):
        return pd.concat(lst, ignore_index=True) if lst and isinstance(lst[0], pd.DataFrame) else pd.DataFrame(lst)

    serie = a_df(acum["serie"])
    serie.insert(1, "anio", serie["periodo"].str[-4:].astype(int))
    serie.insert(2, "trim", serie["periodo"].str[1].astype(int))
    serie.to_csv(out / "gini_serie.csv", index=False)

    # variación interanual con IC (bootstrap independiente: criterio conservador,
    # la EPH comparte ~50 % de hogares entre t y t+4)
    inter = []
    for t in TRIMS:
        for rec in RECORTES:
            k0, k1 = boots.get((etiqueta(2024, t), rec)), boots.get((etiqueta(2025, t), rec))
            if k0 is None or k1 is None:
                continue
            b0, b1 = k0[0], k1[0]
            s0 = serie.query("periodo == @etiqueta(2024, @t) and recorte == @rec").iloc[0]
            s1 = serie.query("periodo == @etiqueta(2025, @t) and recorte == @rec").iloc[0]
            row = {"trim": t, "recorte": rec, "periodo_base": s0["periodo"], "periodo_comp": s1["periodo"]}
            for j, nom in enumerate(["gini", "palma"]):
                d = b1[:, j] - b0[:, j]
                lo, hi = np.percentile(d, [2.5, 97.5])
                dif = s1[nom] - s0[nom]
                row.update({f"{nom}_base": s0[nom], f"{nom}_comp": s1[nom], f"{nom}_dif": dif,
                            f"{nom}_dif_lo": lo, f"{nom}_dif_hi": hi,
                            f"{nom}_significativa": bool(lo > 0 or hi < 0)})
            inter.append(row)
    pd.DataFrame(inter).to_csv(out / "gini_interanual.csv", index=False)

    # variación interanual del ingreso medio por decil (real si hay IPC) con IC bootstrap
    dd_all = a_df(acum["deciles"])
    di = []
    for t in TRIMS:
        for rec in RECORTES:
            k0, k1 = boots.get((etiqueta(2024, t), rec)), boots.get((etiqueta(2025, t), rec))
            if k0 is None or k1 is None:
                continue
            f0, f1 = k0[2], k1[2]
            usar_real = np.isfinite(f0) and np.isfinite(f1)
            r = (k1[1] * (f1 if usar_real else 1)) / (k0[1] * (f0 if usar_real else 1)) - 1
            a = dd_all.query("periodo == @etiqueta(2024, @t) and recorte == @rec").set_index("decil")
            b = dd_all.query("periodo == @etiqueta(2025, @t) and recorte == @rec").set_index("decil")
            for d in range(1, 11):
                lo, hi = np.nanpercentile(r[:, d - 1], [2.5, 97.5])
                col = "ipcf_real" if usar_real else "ipcf_nominal"
                di.append({"trim": t, "recorte": rec, "decil": d, "base": "real" if usar_real else "nominal",
                           "variacion": b.loc[d, col] / a.loc[d, col] - 1, "lo": lo, "hi": hi,
                           "significativa": bool(lo > 0 or hi < 0)})
    pd.DataFrame(di).to_csv(out / "deciles_interanual.csv", index=False)

    # ---- serie larga: todos los cuartos trimestres disponibles (Gini y Palma son
    # invariantes a la escala, así que no requieren deflactar)
    largo = [serie[serie["trim"] == 4].copy()]
    for a in range(2020, 2024):
        try:
            f = buscar_archivo(raw, 4, a)
        except FileNotFoundError:
            print(f"[T4 {a}] base no encontrada: se omite de la serie larga")
            continue
        per = etiqueta(a, 4)
        archivos[per] = f.name
        cache = interim / f"{per.replace(' ', '_')}.csv.gz"
        if cache.exists() and not args.no_cache:
            df = pd.read_csv(cache, dtype={"CODUSU": str})
        else:
            print(f"[{per}] leyendo {f.name} ...")
            df = leer_base(f)
            df.to_csv(cache, index=False)
        if df["ANO4"].notna().any() and not (df["ANO4"].dropna().eq(a).all() and df["TRIMESTRE"].dropna().eq(4).all()):
            raise ValueError(f"{f.name} no corresponde a {per}")
        r, _ = procesar_periodo(df, per, np.nan, args.boot, rng)
        sl = pd.DataFrame(r["serie"])
        sl.insert(1, "anio", a)
        sl.insert(2, "trim", 4)
        largo.append(sl)
        acum["calidad"].extend(r["calidad"])
    sl = pd.concat(largo, ignore_index=True).sort_values(["recorte", "anio"])
    sl.to_csv(out / "gini_serie_larga.csv", index=False)

    nombres = {"lorenz": "lorenz_curvas", "deciles": "deciles", "brechas": "brechas",
               "comp": "composicion", "theil": "theil", "theil_g": "theil_grupos", "calidad": "calidad_muestra"}
    for k, n in nombres.items():
        a_df(acum[k]).to_csv(out / f"{n}.csv", index=False)

    # validación contra la versión anterior del proyecto
    cal = a_df(acum["calidad"])
    val = []
    for nombre, per, rec, tipo, ref in REFERENCIAS:
        if tipo == "gini":
            calc = serie.query("periodo == @per and recorte == @rec")["gini"].iloc[0]
            tol = 5e-6
        else:
            calc = cal.query("periodo == @per and recorte == @rec")["pob_ponderada_pondih"].iloc[0]
            tol = 1.0
        val.append({"indicador": nombre, "referencia": ref, "calculado": calc,
                    "diferencia": calc - ref, "coincide": bool(abs(calc - ref) <= tol)})
    pd.DataFrame(val).to_csv(out / "validacion.csv", index=False)

    meta = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "archivos": archivos,
            "bootstrap_B": args.boot, "semilla": args.seed, "lag_ipc_meses": args.lag_ipc,
            "fechas_descarga": FECHAS_DESCARGA, "ipc_disponible": ipc is not None, "demo": bool(args.demo)}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print("\nVALIDACIÓN contra el proyecto anterior:")
    print(pd.DataFrame(val).to_string(index=False))
    print(f"\nListo. CSV en {out}/")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="data/raw", help="carpeta con las bases individuales EPH")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--interim", default="data/interim", help="caché de bases ya leídas")
    ap.add_argument("--ipc", default="data/external/ipc.csv", help="CSV mes,indice (IPC nacional)")
    ap.add_argument("--lag-ipc", type=int, default=1, help="meses de rezago del IPC (ingreso del mes anterior)")
    ap.add_argument("--boot", type=int, default=500, help="réplicas bootstrap")
    ap.add_argument("--seed", type=int, default=20260)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--demo", action="store_true", help="marca la salida como datos sintéticos")
    correr(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
