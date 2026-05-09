from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(os.getenv("COBRANCA_DB", "data/cobrancas.db"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                documento TEXT,
                contato TEXT,
                observacoes TEXT,
                ativo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dividas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                devedor_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Outros',
                valor_original REAL NOT NULL CHECK(valor_original >= 0),
                data_vencimento TEXT NOT NULL,
                observacoes TEXT,
                status TEXT NOT NULL DEFAULT 'Aberta',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(devedor_id) REFERENCES devedores(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pagamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                devedor_id INTEGER NOT NULL,
                divida_id INTEGER,
                data_pagamento TEXT NOT NULL,
                valor REAL NOT NULL CHECK(valor > 0),
                descricao TEXT,
                comprovante_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(devedor_id) REFERENCES devedores(id) ON DELETE CASCADE,
                FOREIGN KEY(divida_id) REFERENCES dividas(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS taxas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competencia TEXT NOT NULL UNIQUE, -- YYYY-MM
                ipca_pct REAL,
                taxa_legal_pct REAL,
                fonte TEXT,
                status TEXT NOT NULL DEFAULT 'Oficial',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );
            """
        )

        defaults = {
            "usar_provisorio": "Sim",
            "ipca_provisorio_pct": "0.50",
            "taxa_legal_provisoria_pct": "0.20",
            "modo_correcao": "Composto pro-rata diario",
            "data_inicio_taxa_legal": "2024-08-01",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(chave, valor) VALUES (?, ?)",
                (k, v),
            )


def get_settings() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT chave, valor FROM settings").fetchall()
    return {r["chave"]: r["valor"] for r in rows}


def set_setting(chave: str, valor: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(chave, valor)
            VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (chave, valor),
        )


def add_devedor(nome: str, documento: str = "", contato: str = "", observacoes: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO devedores(nome, documento, contato, observacoes) VALUES (?, ?, ?, ?)",
            (nome.strip(), documento.strip(), contato.strip(), observacoes.strip()),
        )


def list_devedores(apenas_ativos: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM devedores"
    params: list[Any] = []
    if apenas_ativos:
        q += " WHERE ativo = 1"
    q += " ORDER BY nome"
    with connect() as conn:
        return rows_to_dicts(conn.execute(q, params).fetchall())


def delete_devedor(devedor_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE devedores SET ativo = 0 WHERE id = ?", (devedor_id,))


def add_divida(
    devedor_id: int,
    descricao: str,
    tipo: str,
    valor_original: float,
    data_vencimento: str,
    observacoes: str = "",
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO dividas(devedor_id, descricao, tipo, valor_original, data_vencimento, observacoes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (devedor_id, descricao.strip(), tipo.strip(), float(valor_original), data_vencimento, observacoes.strip()),
        )


def list_dividas(devedor_id: int | None = None, incluir_canceladas: bool = False) -> list[dict[str, Any]]:
    q = """
        SELECT d.*, dev.nome AS devedor
        FROM dividas d
        JOIN devedores dev ON dev.id = d.devedor_id
        WHERE dev.ativo = 1
    """
    params: list[Any] = []
    if not incluir_canceladas:
        q += " AND d.status <> 'Cancelada'"
    if devedor_id:
        q += " AND d.devedor_id = ?"
        params.append(devedor_id)
    q += " ORDER BY d.data_vencimento, d.id"
    with connect() as conn:
        return rows_to_dicts(conn.execute(q, params).fetchall())


def update_divida_status(divida_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE dividas SET status = ? WHERE id = ?", (status, divida_id))


def delete_divida(divida_id: int) -> None:
    update_divida_status(divida_id, "Cancelada")


def add_pagamento(
    devedor_id: int,
    divida_id: int | None,
    data_pagamento: str,
    valor: float,
    descricao: str = "",
    comprovante_ref: str = "",
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO pagamentos(devedor_id, divida_id, data_pagamento, valor, descricao, comprovante_ref)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (devedor_id, divida_id, data_pagamento, float(valor), descricao.strip(), comprovante_ref.strip()),
        )


def list_pagamentos(devedor_id: int | None = None) -> list[dict[str, Any]]:
    q = """
        SELECT p.*, dev.nome AS devedor, d.descricao AS divida_descricao
        FROM pagamentos p
        JOIN devedores dev ON dev.id = p.devedor_id
        LEFT JOIN dividas d ON d.id = p.divida_id
        WHERE dev.ativo = 1
    """
    params: list[Any] = []
    if devedor_id:
        q += " AND p.devedor_id = ?"
        params.append(devedor_id)
    q += " ORDER BY p.data_pagamento, p.id"
    with connect() as conn:
        return rows_to_dicts(conn.execute(q, params).fetchall())


def delete_pagamento(pagamento_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM pagamentos WHERE id = ?", (pagamento_id,))


def upsert_taxa(
    competencia: str,
    ipca_pct: float | None = None,
    taxa_legal_pct: float | None = None,
    fonte: str = "",
    status: str = "Oficial",
) -> None:
    with connect() as conn:
        atual = conn.execute("SELECT * FROM taxas WHERE competencia = ?", (competencia,)).fetchone()
        if atual:
            novo_ipca = ipca_pct if ipca_pct is not None else atual["ipca_pct"]
            nova_tl = taxa_legal_pct if taxa_legal_pct is not None else atual["taxa_legal_pct"]
            conn.execute(
                """
                UPDATE taxas
                SET ipca_pct = ?, taxa_legal_pct = ?, fonte = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE competencia = ?
                """,
                (novo_ipca, nova_tl, fonte or atual["fonte"], status, competencia),
            )
        else:
            conn.execute(
                """
                INSERT INTO taxas(competencia, ipca_pct, taxa_legal_pct, fonte, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (competencia, ipca_pct, taxa_legal_pct, fonte, status),
            )


def list_taxas() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM taxas ORDER BY competencia DESC").fetchall())


def taxas_dict() -> dict[str, dict[str, Any]]:
    return {r["competencia"]: r for r in list_taxas()}


def delete_taxa(taxa_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM taxas WHERE id = ?", (taxa_id,))
