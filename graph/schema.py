"""
graph/schema.py

Phase 0's Kuzu schema — deliberately minimal. Just enough structure to
ask "show me this agent's Brier score trend over time by task type."
The full ADR/decision-graph schema (agents contradicting each other's
architectural choices) is Phase 3 — don't build it early, it has nothing
to attach to until there are multiple agents making real decisions.
"""

from __future__ import annotations

from datetime import datetime

import kuzu


def _create_if_missing(conn: "kuzu.Connection", ddl: str) -> None:
    """
    Kuzu's DDL support for `IF NOT EXISTS` varies by version — the version
    that ended up installed here doesn't accept it (`mismatched input
    'NOT' expecting '('`). Rather than pin behavior to a specific Kuzu
    version's syntax, just attempt the CREATE and swallow the specific
    "already exists" error on repeat runs. Any other error still raises.
    """
    try:
        conn.execute(ddl)
    except RuntimeError as exc:
        if "already exists" not in str(exc).lower():
            raise


def init_schema(db_path: str) -> kuzu.Database:
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    _create_if_missing(conn, """
        CREATE NODE TABLE Agent(
            id STRING,
            model_name STRING,
            tier STRING,
            PRIMARY KEY(id)
        )
    """)

    _create_if_missing(conn, """
        CREATE NODE TABLE Task(
            id STRING,
            task_type STRING,
            difficulty STRING,
            benchmark_source STRING,
            PRIMARY KEY(id)
        )
    """)

    _create_if_missing(conn, """
        CREATE NODE TABLE Attempt(
            id STRING,
            verbalized_conf DOUBLE,
            behavioral_conf DOUBLE,
            outcome_conf DOUBLE,
            fused_2way DOUBLE,
            fused_3way DOUBLE,
            brier_2way DOUBLE,
            brier_3way DOUBLE,
            succeeded BOOLEAN,
            timestamp TIMESTAMP,
            PRIMARY KEY(id)
        )
    """)

    _create_if_missing(conn, """
        CREATE REL TABLE MADE(
            FROM Agent TO Attempt
        )
    """)

    _create_if_missing(conn, """
        CREATE REL TABLE ON_TASK(
            FROM Attempt TO Task
        )
    """)

    return db


def record_attempt(
    conn: "kuzu.Connection",
    agent_id: str,
    model_name: str,
    tier: str,
    task_id: str,
    task_type: str,
    difficulty: str,
    benchmark_source: str,
    attempt_id: str,
    verbalized_conf: float,
    behavioral_conf: float,
    outcome_conf: float,
    fused_2way: float,
    fused_3way: float,
    brier_2way: float,
    brier_3way: float,
    succeeded: bool,
) -> None:
    """Upsert-style write: MERGE the Agent/Task nodes, always CREATE a fresh Attempt."""

    conn.execute(
        "MERGE (a:Agent {id: $id}) SET a.model_name = $model_name, a.tier = $tier",
        {"id": agent_id, "model_name": model_name, "tier": tier},
    )

    conn.execute(
        """MERGE (t:Task {id: $id})
           SET t.task_type = $task_type, t.difficulty = $difficulty,
               t.benchmark_source = $benchmark_source""",
        {
            "id": task_id,
            "task_type": task_type,
            "difficulty": difficulty,
            "benchmark_source": benchmark_source,
        },
    )

    conn.execute(
        """CREATE (att:Attempt {
               id: $id, verbalized_conf: $verbalized_conf,
               behavioral_conf: $behavioral_conf, outcome_conf: $outcome_conf,
               fused_2way: $fused_2way, fused_3way: $fused_3way,
               brier_2way: $brier_2way, brier_3way: $brier_3way,
               succeeded: $succeeded, timestamp: timestamp($timestamp)
           })""",
        {
            "id": attempt_id,
            "verbalized_conf": verbalized_conf,
            "behavioral_conf": behavioral_conf,
            "outcome_conf": outcome_conf,
            "fused_2way": fused_2way,
            "fused_3way": fused_3way,
            "brier_2way": brier_2way,
            "brier_3way": brier_3way,
            "succeeded": succeeded,
            # Kuzu's timestamp() only understands the "now" keyword as
            # literal query text, not as bound parameter data — passing the
            # string "now" here failed to parse. Compute the actual current
            # timestamp in Python instead, in the exact format Kuzu expects.
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
    )

    conn.execute(
        """MATCH (a:Agent {id: $agent_id}), (att:Attempt {id: $attempt_id})
           CREATE (a)-[:MADE]->(att)""",
        {"agent_id": agent_id, "attempt_id": attempt_id},
    )

    conn.execute(
        """MATCH (att:Attempt {id: $attempt_id}), (t:Task {id: $task_id})
           CREATE (att)-[:ON_TASK]->(t)""",
        {"attempt_id": attempt_id, "task_id": task_id},
    )


def brier_trend_by_task_type(conn: "kuzu.Connection", agent_id: str) -> list[dict]:
    """The query Phase 0 cares most about: is 3-way fusion actually winning, broken down by task type?"""
    result = conn.execute(
        """MATCH (a:Agent {id: $agent_id})-[:MADE]->(att:Attempt)-[:ON_TASK]->(t:Task)
           RETURN t.task_type AS task_type,
                  avg(att.brier_2way) AS avg_brier_2way,
                  avg(att.brier_3way) AS avg_brier_3way,
                  count(*) AS n
           ORDER BY task_type""",
        {"agent_id": agent_id},
    )
    rows = []
    while result.has_next():
        row = result.get_next()
        rows.append(
            {
                "task_type": row[0],
                "avg_brier_2way": row[1],
                "avg_brier_3way": row[2],
                "n": row[3],
            }
        )
    return rows