from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(os.getenv("COBRANCA_DB", "data/cobrancas.db"))

DEFAULT_GROUP_NAME = "Geral"

SUGGESTED_GROUPS = [
    "Geral",
    "Mensalidades",
    "Décimo terceiro",
    "Férias",
    "Reembolsos",
    "Empréstimos",
    "Acordo antigo",
    "Outros",
]

ADMIN_STATUSES = [
    "Aberta",
    "Em disputa",
    "Renegociada",
    "Cancelada",
    "Incobrável",
    "Judicializada",
]

REF_PREFIX_TITULO = "TIT"
REF_PREFIX_RECEBIMENTO = "REC"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _parse_year_from_date_str(value: str | None) -> int:
    if not value:
        return date.today().year

    try:
        return date.fromisoformat(str(value)[:10]).year
    except ValueError:
        return date.today().year


def _competencia_from_date_str(value: str | None) -> str:
    if not value:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"

    try:
        d = date.fromisoformat(str(value)[:10])
        return f"{d.year:04d}-{d.month:02d}"
    except ValueError:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"


def _format_public_ref(prefix: str, year: int, number: int) -> str:
    return f"{prefix}-{year:04d}-{number:06d}"


def _parse_public_ref(value: str | None) -> tuple[str, int, int] | None:
    if not value:
        return None

    parts = str(value).strip().split("-")

    if len(parts) != 3:
        return None

    prefix, year_str, number_str = parts

    try:
        return prefix, int(year_str), int(number_str)
    except ValueError:
        return None


def _gerar_public_ref_conn(
    conn: sqlite3.Connection,
    prefix: str,
    data_referencia: str | None,
) -> str:
    year = _parse_year_from_date_str(data_referencia)

    row = conn.execute(
        """
        SELECT ultimo_numero
        FROM sequencias
        WHERE entidade = ?
          AND ano = ?
        """,
        (prefix, year),
    ).fetchone()

    if row:
        next_number = int(row["ultimo_numero"]) + 1
        conn.execute(
            """
            UPDATE sequencias
            SET ultimo_numero = ?
            WHERE entidade = ?
              AND ano = ?
            """,
            (next_number, prefix, year),
        )
    else:
        next_number = 1
        conn.execute(
            """
            INSERT INTO sequencias(entidade, ano, ultimo_numero)
            VALUES (?, ?, ?)
            """,
            (prefix, year, next_number),
        )

    return _format_public_ref(prefix, year, next_number)


def _sync_sequence_with_existing_refs_conn(
    conn: sqlite3.Connection,
    table: str,
    prefix: str,
) -> None:
    rows = conn.execute(
        f"""
        SELECT public_ref
        FROM {table}
        WHERE public_ref IS NOT NULL
          AND trim(public_ref) <> ''
        """
    ).fetchall()

    max_by_year: dict[int, int] = {}

    for row in rows:
        parsed = _parse_public_ref(row["public_ref"])

        if not parsed:
            continue

        parsed_prefix, year, number = parsed

        if parsed_prefix != prefix:
            continue

        max_by_year[year] = max(max_by_year.get(year, 0), number)

    for year, number in max_by_year.items():
        atual = conn.execute(
            """
            SELECT ultimo_numero
            FROM sequencias
            WHERE entidade = ?
              AND ano = ?
            """,
            (prefix, year),
        ).fetchone()

        if atual:
            if int(atual["ultimo_numero"]) < number:
                conn.execute(
                    """
                    UPDATE sequencias
                    SET ultimo_numero = ?
                    WHERE entidade = ?
                      AND ano = ?
                    """,
                    (number, prefix, year),
                )
        else:
            conn.execute(
                """
                INSERT INTO sequencias(entidade, ano, ultimo_numero)
                VALUES (?, ?, ?)
                """,
                (prefix, year, number),
            )


def _backfill_public_refs_conn(conn: sqlite3.Connection) -> None:
    _sync_sequence_with_existing_refs_conn(conn, "dividas", REF_PREFIX_TITULO)
    _sync_sequence_with_existing_refs_conn(
        conn,
        "pagamentos",
        REF_PREFIX_RECEBIMENTO,
    )

    dividas = conn.execute(
        """
        SELECT id, data_vencimento
        FROM dividas
        WHERE public_ref IS NULL
           OR trim(public_ref) = ''
        ORDER BY data_vencimento, id
        """
    ).fetchall()

    for divida in dividas:
        public_ref = _gerar_public_ref_conn(
            conn,
            REF_PREFIX_TITULO,
            divida["data_vencimento"],
        )
        conn.execute(
            """
            UPDATE dividas
            SET public_ref = ?
            WHERE id = ?
            """,
            (public_ref, int(divida["id"])),
        )

    pagamentos = conn.execute(
        """
        SELECT id, data_pagamento
        FROM pagamentos
        WHERE public_ref IS NULL
           OR trim(public_ref) = ''
        ORDER BY data_pagamento, id
        """
    ).fetchall()

    for pagamento in pagamentos:
        public_ref = _gerar_public_ref_conn(
            conn,
            REF_PREFIX_RECEBIMENTO,
            pagamento["data_pagamento"],
        )
        conn.execute(
            """
            UPDATE pagamentos
            SET public_ref = ?
            WHERE id = ?
            """,
            (public_ref, int(pagamento["id"])),
        )


def _backfill_competencias_conn(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, data_vencimento
        FROM dividas
        WHERE competencia IS NULL
           OR trim(competencia) = ''
        """
    ).fetchall()

    for row in rows:
        conn.execute(
            """
            UPDATE dividas
            SET competencia = ?
            WHERE id = ?
            """,
            (
                _competencia_from_date_str(row["data_vencimento"]),
                int(row["id"]),
            ),
        )


def _create_indexes_conn(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dividas_public_ref
        ON dividas(public_ref)
        WHERE public_ref IS NOT NULL
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pagamentos_public_ref
        ON pagamentos(public_ref)
        WHERE public_ref IS NOT NULL
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dividas_devedor_grupo
        ON dividas(devedor_id, grupo_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dividas_vencimento
        ON dividas(data_vencimento)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pagamentos_devedor_data
        ON pagamentos(devedor_id, data_pagamento)
        """
    )


def _get_or_create_grupo_conn(
    conn: sqlite3.Connection,
    devedor_id: int,
    nome: str | None,
) -> int:
    nome_limpo = (nome or "").strip() or DEFAULT_GROUP_NAME

    row = conn.execute(
        """
        SELECT id
        FROM grupos
        WHERE devedor_id = ?
          AND lower(nome) = lower(?)
          AND ativo = 1
        """,
        (devedor_id, nome_limpo),
    ).fetchone()

    if row:
        return int(row["id"])

    cur = conn.execute(
        """
        INSERT INTO grupos(devedor_id, nome)
        VALUES (?, ?)
        """,
        (devedor_id, nome_limpo),
    )
    return int(cur.lastrowid)


def _ensure_default_groups_for_existing_debtors(conn: sqlite3.Connection) -> None:
    devedores = conn.execute("SELECT id FROM devedores").fetchall()

    for dev in devedores:
        devedor_id = int(dev["id"])
        grupo_geral_id = _get_or_create_grupo_conn(
            conn,
            devedor_id,
            DEFAULT_GROUP_NAME,
        )

        conn.execute(
            """
            UPDATE dividas
            SET grupo_id = ?
            WHERE devedor_id = ?
              AND grupo_id IS NULL
            """,
            (grupo_geral_id, devedor_id),
        )


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

            CREATE TABLE IF NOT EXISTS grupos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                devedor_id INTEGER NOT NULL,
                nome TEXT NOT NULL COLLATE NOCASE,
                ativo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(devedor_id, nome),
                FOREIGN KEY(devedor_id) REFERENCES devedores(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sequencias (
                entidade TEXT NOT NULL,
                ano INTEGER NOT NULL,
                ultimo_numero INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(entidade, ano)
            );

            CREATE TABLE IF NOT EXISTS dividas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_ref TEXT,
                devedor_id INTEGER NOT NULL,
                grupo_id INTEGER,
                descricao TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Outros',
                competencia TEXT,
                valor_original REAL NOT NULL CHECK(valor_original >= 0),
                data_vencimento TEXT NOT NULL,
                observacoes TEXT,
                status TEXT NOT NULL DEFAULT 'Aberta',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                FOREIGN KEY(devedor_id) REFERENCES devedores(id) ON DELETE CASCADE,
                FOREIGN KEY(grupo_id) REFERENCES grupos(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS pagamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_ref TEXT,
                devedor_id INTEGER NOT NULL,
                divida_id INTEGER,
                grupo_id INTEGER,
                data_pagamento TEXT NOT NULL,
                valor REAL NOT NULL CHECK(valor > 0),
                descricao TEXT,
                comprovante_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                FOREIGN KEY(devedor_id) REFERENCES devedores(id) ON DELETE CASCADE,
                FOREIGN KEY(divida_id) REFERENCES dividas(id) ON DELETE SET NULL,
                FOREIGN KEY(grupo_id) REFERENCES grupos(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS taxas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competencia TEXT NOT NULL UNIQUE,
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

        _add_column_if_missing(conn, "dividas", "public_ref", "TEXT")
        _add_column_if_missing(conn, "dividas", "grupo_id", "INTEGER")
        _add_column_if_missing(conn, "dividas", "competencia", "TEXT")
        _add_column_if_missing(conn, "dividas", "updated_at", "TEXT")

        _add_column_if_missing(conn, "pagamentos", "public_ref", "TEXT")
        _add_column_if_missing(conn, "pagamentos", "grupo_id", "INTEGER")
        _add_column_if_missing(conn, "pagamentos", "updated_at", "TEXT")

        _ensure_default_groups_for_existing_debtors(conn)
        _backfill_competencias_conn(conn)
        _backfill_public_refs_conn(conn)
        _create_indexes_conn(conn)

        defaults = {
            "usar_provisorio": "Sim",
            "ipca_provisorio_pct": "0.60",
            "taxa_legal_provisoria_pct": "0.50",
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


def add_devedor(
    nome: str,
    documento: str = "",
    contato: str = "",
    observacoes: str = "",
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO devedores(nome, documento, contato, observacoes)
            VALUES (?, ?, ?, ?)
            """,
            (
                nome.strip(),
                documento.strip(),
                contato.strip(),
                observacoes.strip(),
            ),
        )
        devedor_id = int(cur.lastrowid)
        _get_or_create_grupo_conn(conn, devedor_id, DEFAULT_GROUP_NAME)
        return devedor_id


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


def get_or_create_grupo(devedor_id: int, nome: str | None) -> int:
    with connect() as conn:
        return _get_or_create_grupo_conn(conn, devedor_id, nome)


def list_grupos(
    devedor_id: int,
    apenas_ativos: bool = True,
) -> list[dict[str, Any]]:
    with connect() as conn:
        _get_or_create_grupo_conn(conn, devedor_id, DEFAULT_GROUP_NAME)

        q = """
            SELECT *
            FROM grupos
            WHERE devedor_id = ?
        """
        params: list[Any] = [devedor_id]

        if apenas_ativos:
            q += " AND ativo = 1"

        q += """
            ORDER BY
                CASE WHEN lower(nome) = lower(?) THEN 0 ELSE 1 END,
                nome
        """
        params.append(DEFAULT_GROUP_NAME)

        return rows_to_dicts(conn.execute(q, params).fetchall())


def delete_grupo(grupo_id: int) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT devedor_id, nome FROM grupos WHERE id = ?",
            (grupo_id,),
        ).fetchone()

        if not row:
            return

        if row["nome"].lower() == DEFAULT_GROUP_NAME.lower():
            return

        grupo_geral_id = _get_or_create_grupo_conn(
            conn,
            int(row["devedor_id"]),
            DEFAULT_GROUP_NAME,
        )

        conn.execute(
            """
            UPDATE dividas
            SET grupo_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE grupo_id = ?
            """,
            (grupo_geral_id, grupo_id),
        )

        conn.execute(
            """
            UPDATE pagamentos
            SET grupo_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE grupo_id = ?
            """,
            (grupo_id,),
        )

        conn.execute(
            "UPDATE grupos SET ativo = 0 WHERE id = ?",
            (grupo_id,),
        )


def add_divida(
    devedor_id: int,
    descricao: str,
    tipo: str,
    valor_original: float,
    data_vencimento: str,
    observacoes: str = "",
    grupo_id: int | None = None,
    competencia: str | None = None,
) -> int:
    with connect() as conn:
        if grupo_id is None:
            grupo_id = _get_or_create_grupo_conn(
                conn,
                devedor_id,
                DEFAULT_GROUP_NAME,
            )

        public_ref = _gerar_public_ref_conn(
            conn,
            REF_PREFIX_TITULO,
            data_vencimento,
        )

        competencia_final = (
            competencia.strip()
            if competencia and competencia.strip()
            else _competencia_from_date_str(data_vencimento)
        )

        cur = conn.execute(
            """
            INSERT INTO dividas(
                public_ref,
                devedor_id,
                grupo_id,
                descricao,
                tipo,
                competencia,
                valor_original,
                data_vencimento,
                observacoes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                public_ref,
                devedor_id,
                grupo_id,
                descricao.strip(),
                tipo.strip(),
                competencia_final,
                float(valor_original),
                data_vencimento,
                observacoes.strip(),
            ),
        )
        return int(cur.lastrowid)


def get_divida(divida_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                d.*,
                dev.nome AS devedor,
                COALESCE(g.nome, 'Geral') AS grupo
            FROM dividas d
            JOIN devedores dev ON dev.id = d.devedor_id
            LEFT JOIN grupos g ON g.id = d.grupo_id
            WHERE d.id = ?
            """,
            (divida_id,),
        ).fetchone()

    return dict(row) if row else None


def get_divida_by_public_ref(public_ref: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                d.*,
                dev.nome AS devedor,
                COALESCE(g.nome, 'Geral') AS grupo
            FROM dividas d
            JOIN devedores dev ON dev.id = d.devedor_id
            LEFT JOIN grupos g ON g.id = d.grupo_id
            WHERE d.public_ref = ?
            """,
            (public_ref.strip(),),
        ).fetchone()

    return dict(row) if row else None


def list_dividas(
    devedor_id: int | None = None,
    incluir_canceladas: bool = False,
) -> list[dict[str, Any]]:
    q = """
        SELECT
            d.*,
            dev.nome AS devedor,
            COALESCE(g.nome, 'Geral') AS grupo
        FROM dividas d
        JOIN devedores dev ON dev.id = d.devedor_id
        LEFT JOIN grupos g ON g.id = d.grupo_id
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


def count_pagamentos_diretos_divida(divida_id: int) -> int:
    """
    Conta recebimentos cadastrados diretamente para um título específico.

    Observação:
    recebimentos automáticos ainda são alocados dinamicamente em calculos.py.
    Para saber se um título recebeu pagamento automático, a UI deve consultar
    o resultado de calcular_carteira() e verificar as alocações.
    """
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM pagamentos
            WHERE divida_id = ?
            """,
            (divida_id,),
        ).fetchone()

    return int(row["total"]) if row else 0


def update_divida(
    divida_id: int,
    *,
    grupo_id: int | None,
    descricao: str,
    tipo: str,
    observacoes: str = "",
    status: str = "Aberta",
    valor_original: float | None = None,
    data_vencimento: str | None = None,
    competencia: str | None = None,
    permitir_alterar_valor_vencimento: bool = False,
) -> None:
    """
    Atualiza um título com trava para campos financeiros.

    Campos sempre editáveis:
    - grupo_id
    - descricao
    - tipo
    - competencia
    - observacoes
    - status

    Campos financeiros:
    - valor_original
    - data_vencimento

    Só devem ser alterados quando permitir_alterar_valor_vencimento=True.

    A UI deve passar permitir_alterar_valor_vencimento=False quando o título
    já tiver recebimento alocado, direto ou automático.
    """
    status_limpo = (status or "Aberta").strip()
    if status_limpo not in ADMIN_STATUSES:
        raise ValueError(
            f"Status inválido: {status_limpo}. "
            f"Use um destes: {', '.join(ADMIN_STATUSES)}"
        )

    descricao_limpa = descricao.strip()
    tipo_limpo = tipo.strip() or "Outros"
    observacoes_limpas = observacoes.strip()

    if not descricao_limpa:
        raise ValueError("A descrição do título não pode ficar vazia.")

    with connect() as conn:
        atual = conn.execute(
            "SELECT * FROM dividas WHERE id = ?",
            (divida_id,),
        ).fetchone()

        if not atual:
            raise ValueError("Título não encontrado.")

        if grupo_id is None:
            grupo_id = _get_or_create_grupo_conn(
                conn,
                int(atual["devedor_id"]),
                DEFAULT_GROUP_NAME,
            )

        competencia_final = (
            competencia.strip()
            if competencia and competencia.strip()
            else str(atual["competencia"] or "").strip()
            or _competencia_from_date_str(atual["data_vencimento"])
        )

        if permitir_alterar_valor_vencimento:
            if valor_original is None:
                valor_original = float(atual["valor_original"])

            if data_vencimento is None:
                data_vencimento = str(atual["data_vencimento"])

            if float(valor_original) < 0:
                raise ValueError("O valor original não pode ser negativo.")

            conn.execute(
                """
                UPDATE dividas
                SET grupo_id = ?,
                    descricao = ?,
                    tipo = ?,
                    competencia = ?,
                    valor_original = ?,
                    data_vencimento = ?,
                    observacoes = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    grupo_id,
                    descricao_limpa,
                    tipo_limpo,
                    competencia_final,
                    float(valor_original),
                    data_vencimento,
                    observacoes_limpas,
                    status_limpo,
                    divida_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE dividas
                SET grupo_id = ?,
                    descricao = ?,
                    tipo = ?,
                    competencia = ?,
                    observacoes = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    grupo_id,
                    descricao_limpa,
                    tipo_limpo,
                    competencia_final,
                    observacoes_limpas,
                    status_limpo,
                    divida_id,
                ),
            )


def update_divida_status(divida_id: int, status: str) -> None:
    status_limpo = (status or "Aberta").strip()

    if status_limpo not in ADMIN_STATUSES:
        raise ValueError(
            f"Status inválido: {status_limpo}. "
            f"Use um destes: {', '.join(ADMIN_STATUSES)}"
        )

    with connect() as conn:
        conn.execute(
            """
            UPDATE dividas
            SET status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status_limpo, divida_id),
        )


def delete_divida(divida_id: int) -> None:
    update_divida_status(divida_id, "Cancelada")


def add_pagamento(
    devedor_id: int,
    divida_id: int | None,
    data_pagamento: str,
    valor: float,
    descricao: str = "",
    comprovante_ref: str = "",
    grupo_id: int | None = None,
) -> int:
    if divida_id is not None:
        grupo_id = None

    with connect() as conn:
        public_ref = _gerar_public_ref_conn(
            conn,
            REF_PREFIX_RECEBIMENTO,
            data_pagamento,
        )

        cur = conn.execute(
            """
            INSERT INTO pagamentos(
                public_ref,
                devedor_id,
                divida_id,
                grupo_id,
                data_pagamento,
                valor,
                descricao,
                comprovante_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                public_ref,
                devedor_id,
                divida_id,
                grupo_id,
                data_pagamento,
                float(valor),
                descricao.strip(),
                comprovante_ref.strip(),
            ),
        )
        return int(cur.lastrowid)


def get_pagamento(pagamento_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                p.*,
                dev.nome AS devedor,
                d.public_ref AS divida_public_ref,
                d.descricao AS divida_descricao,
                g.nome AS grupo
            FROM pagamentos p
            JOIN devedores dev ON dev.id = p.devedor_id
            LEFT JOIN dividas d ON d.id = p.divida_id
            LEFT JOIN grupos g ON g.id = p.grupo_id
            WHERE p.id = ?
            """,
            (pagamento_id,),
        ).fetchone()

    return dict(row) if row else None


def get_pagamento_by_public_ref(public_ref: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                p.*,
                dev.nome AS devedor,
                d.public_ref AS divida_public_ref,
                d.descricao AS divida_descricao,
                g.nome AS grupo
            FROM pagamentos p
            JOIN devedores dev ON dev.id = p.devedor_id
            LEFT JOIN dividas d ON d.id = p.divida_id
            LEFT JOIN grupos g ON g.id = p.grupo_id
            WHERE p.public_ref = ?
            """,
            (public_ref.strip(),),
        ).fetchone()

    return dict(row) if row else None


def list_pagamentos(devedor_id: int | None = None) -> list[dict[str, Any]]:
    q = """
        SELECT
            p.*,
            dev.nome AS devedor,
            d.public_ref AS divida_public_ref,
            d.descricao AS divida_descricao,
            g.nome AS grupo
        FROM pagamentos p
        JOIN devedores dev ON dev.id = p.devedor_id
        LEFT JOIN dividas d ON d.id = p.divida_id
        LEFT JOIN grupos g ON g.id = p.grupo_id
        WHERE dev.ativo = 1
    """
    params: list[Any] = []

    if devedor_id:
        q += " AND p.devedor_id = ?"
        params.append(devedor_id)

    q += " ORDER BY p.data_pagamento, p.id"

    with connect() as conn:
        return rows_to_dicts(conn.execute(q, params).fetchall())


def update_pagamento(
    pagamento_id: int,
    *,
    devedor_id: int,
    divida_id: int | None,
    grupo_id: int | None,
    data_pagamento: str,
    valor: float,
    descricao: str = "",
    comprovante_ref: str = "",
) -> None:
    """
    Atualiza um recebimento.

    Regra:
    - se divida_id for informado, grupo_id fica NULL;
    - se divida_id for NULL e grupo_id for NULL, é automático geral;
    - se divida_id for NULL e grupo_id for informado, é automático por grupo.
    """
    if valor <= 0:
        raise ValueError("O valor do recebimento deve ser maior que zero.")

    if divida_id is not None:
        grupo_id = None

    with connect() as conn:
        atual = conn.execute(
            "SELECT id FROM pagamentos WHERE id = ?",
            (pagamento_id,),
        ).fetchone()

        if not atual:
            raise ValueError("Recebimento não encontrado.")

        conn.execute(
            """
            UPDATE pagamentos
            SET devedor_id = ?,
                divida_id = ?,
                grupo_id = ?,
                data_pagamento = ?,
                valor = ?,
                descricao = ?,
                comprovante_ref = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                devedor_id,
                divida_id,
                grupo_id,
                data_pagamento,
                float(valor),
                descricao.strip(),
                comprovante_ref.strip(),
                pagamento_id,
            ),
        )


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
        atual = conn.execute(
            "SELECT * FROM taxas WHERE competencia = ?",
            (competencia,),
        ).fetchone()

        if atual:
            novo_ipca = ipca_pct if ipca_pct is not None else atual["ipca_pct"]
            nova_tl = (
                taxa_legal_pct
                if taxa_legal_pct is not None
                else atual["taxa_legal_pct"]
            )

            if novo_ipca is None or nova_tl is None:
                status_final = "Parcial"
            else:
                status_final = status

            conn.execute(
                """
                UPDATE taxas
                SET ipca_pct = ?,
                    taxa_legal_pct = ?,
                    fonte = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE competencia = ?
                """,
                (
                    novo_ipca,
                    nova_tl,
                    fonte or atual["fonte"],
                    status_final,
                    competencia,
                ),
            )
        else:
            if ipca_pct is None or taxa_legal_pct is None:
                status = "Parcial"

            conn.execute(
                """
                INSERT INTO taxas(
                    competencia,
                    ipca_pct,
                    taxa_legal_pct,
                    fonte,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    competencia,
                    ipca_pct,
                    taxa_legal_pct,
                    fonte,
                    status,
                ),
            )


def list_taxas() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows_to_dicts(
            conn.execute("SELECT * FROM taxas ORDER BY competencia DESC").fetchall()
        )


def taxas_dict() -> dict[str, dict[str, Any]]:
    return {r["competencia"]: r for r in list_taxas()}


def delete_taxa(taxa_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM taxas WHERE id = ?", (taxa_id,))
