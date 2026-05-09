from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import pandas as pd
import requests

SERIE_IPCA_MENSAL = 433
SERIE_TAXA_LEGAL_MENSAL = 29543

BASE_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def _fmt_bcb(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def fetch_sgs(codigo: int, data_inicial: date, data_final: date) -> pd.DataFrame:
    params = {
        "formato": "json",
        "dataInicial": _fmt_bcb(data_inicial),
        "dataFinal": _fmt_bcb(data_final),
    }
    url = BASE_SGS.format(codigo=codigo)
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()

    data = r.json()
    if not data:
        return pd.DataFrame(columns=["data", "valor"])

    df = pd.DataFrame(data)
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date
    df["valor"] = pd.to_numeric(df["valor"].str.replace(",", ".", regex=False), errors="coerce")
    return df.dropna(subset=["valor"])


def buscar_ipca_e_taxa_legal(data_inicial: date, data_final: date) -> pd.DataFrame:
    ipca = fetch_sgs(SERIE_IPCA_MENSAL, data_inicial, data_final)
    tl = fetch_sgs(SERIE_TAXA_LEGAL_MENSAL, data_inicial, data_final)

    if not ipca.empty:
        ipca["competencia"] = ipca["data"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
        ipca = ipca[["competencia", "valor"]].rename(columns={"valor": "ipca_pct"})
    else:
        ipca = pd.DataFrame(columns=["competencia", "ipca_pct"])

    if not tl.empty:
        tl["competencia"] = tl["data"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
        tl = tl[["competencia", "valor"]].rename(columns={"valor": "taxa_legal_pct"})
    else:
        tl = pd.DataFrame(columns=["competencia", "taxa_legal_pct"])

    out = pd.merge(ipca, tl, how="outer", on="competencia").sort_values("competencia")
    out["fonte"] = "BCB SGS: IPCA 433; Taxa Legal 29543"
    out["status"] = "Oficial"
    return out
