"""Pruebas del ETL. Correr con:  pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import etl  # noqa: E402


def test_gini_igualdad_perfecta():
    assert abs(etl.gini([5, 5, 5, 5], [1, 1, 1, 1])) < 1e-12


def test_gini_valor_conocido():
    # ingresos 1,2,3,4 con igual peso -> Gini = 0.25
    assert abs(etl.gini([1, 2, 3, 4], [1, 1, 1, 1]) - 0.25) < 1e-12


def test_gini_ponderado_equivale_a_replicar():
    x, w = [1, 2, 10], [3, 1, 2]
    rep = [1, 1, 1, 2, 10, 10]
    assert abs(etl.gini(x, w) - etl.gini(rep, [1] * 6)) < 1e-12


def test_palma():
    x = np.arange(1, 101, dtype=float)
    w = np.ones(100)
    p, L = etl.lorenz_ordenada(x, w)
    esperado = x[90:].sum() / x[:40].sum()
    assert abs(etl.palma_de_lorenz(p, L) - esperado) < 1e-9


def test_deciles_no_parten_grupos_empatados():
    x = np.array([1.0] * 50 + [2.0] * 50)
    d = etl.asignar_deciles(x, np.ones(100))
    assert len(set(d[:50])) == 1 and len(set(d[50:])) == 1


def test_theil_descomposicion_suma():
    rng = np.random.default_rng(1)
    x = rng.lognormal(10, 0.6, 500)
    w = rng.uniform(1, 3, 500)
    g = rng.choice(list("abc"), 500)
    T, intra, entre, _ = etl.theil_descomp(x, w, g)
    assert abs(T - etl.theil_t(x, w)) < 1e-10 and entre >= 0


def test_pipeline_completo(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(0)
    for a in etl.ANIOS:
        for t in etl.TRIMS:
            n = 800
            hog = np.repeat(np.arange(n), rng.integers(1, 5, n))
            m = len(hog)
            ipcf = rng.lognormal(11.5 + 0.1 * (a - 2024), 0.7, n)[hog]
            df = pd.DataFrame({
                "CODUSU": [f"U{h}" for h in hog], "NRO_HOGAR": 1,
                "AGLOMERADO": np.where(hog % 10 == 0, 12, rng.choice([2, 3, 13], m)),
                "CH03": np.r_[[1], np.where(hog[1:] == hog[:-1], 3, 1)],
                "ESTADO": 1, "CAT_OCUP": 3, "PP07H": rng.choice([1, 2], m),
                "P21": ipcf * 0.7, "TOT_P12": 0, "P47T": ipcf, "T_VI": ipcf * 0.3,
                "V2_M": ipcf * 0.1, "V4_M": 0, "V5_M": ipcf * 0.05,
                "IPCF": ipcf, "DECCFR": np.where(rng.random(m) < 0.08, 12, 5),
                "PONDIH": rng.uniform(300, 1500, m), "PONDERA": rng.uniform(300, 1500, m)})
            df.to_csv(raw / f"usu_individual_T{t}{str(a)[2:]}.csv", index=False)
    meses = pd.period_range("2023-10", "2026-01", freq="M")
    ipc = pd.DataFrame({"mes": meses.astype(str), "indice": 100 * 1.025 ** np.arange(len(meses))})
    ipc.to_csv(tmp_path / "ipc.csv", index=False)
    out = tmp_path / "out"
    etl.main(["--raw", str(raw), "--out", str(out), "--interim", str(tmp_path / "int"),
              "--ipc", str(tmp_path / "ipc.csv"), "--boot", "40", "--demo"])
    serie = pd.read_csv(out / "gini_serie.csv")
    assert len(serie) == 16 and serie["gini"].between(0, 1).all()
    assert (serie["gini_lo"] <= serie["gini"]).all() and (serie["gini"] <= serie["gini_hi"]).all()
    assert len(pd.read_csv(out / "gini_interanual.csv")) == 8
    comp = pd.read_csv(out / "composicion.csv")
    assert np.allclose(comp.groupby(["periodo", "recorte", "decil"])["participacion"].sum(), 1)
    dec = pd.read_csv(out / "deciles.csv")
    assert np.allclose(dec.groupby(["periodo", "recorte"])["pct_ingreso"].sum(), 1)
    assert dec["ipcf_real"].notna().all()


def test_bootstrap_medias_por_decil_centradas():
    rng = np.random.default_rng(3)
    x = np.sort(rng.lognormal(10, 0.5, 600)); w = rng.uniform(1, 3, 600)
    hh = np.arange(600) // 2
    bt, dm = etl.bootstrap(x, w, hh, 200, rng)
    dec = etl.asignar_deciles(x, w)
    punto = np.array([np.average(x[dec == d], weights=w[dec == d]) for d in range(1, 11)])
    assert np.all(np.abs(np.nanmean(dm, axis=0) / punto - 1) < 0.05)
    assert abs(bt[:, 0].mean() - etl.gini(x, w)) < 0.01
