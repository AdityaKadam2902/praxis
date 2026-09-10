"""
graph/schema.py

Phase 0 schema, corrected for Phase 2: `tier` moved from the Agent node
to the Attempt node.

Why: with a single Agent id ("engineer_v0"), storing tier on Agent meant
every new attempt's MERGE...SET overwrote the same node's tier field —
so Agent.tier only ever reflected whichever tier was used *most
recently*, not which tier a specific past attempt actually used.
Grouping history by a.tier (as the Phase 2 trust-based router needs to)
would have silently misattributed every attempt to the wrong tier. Tier
is a property of each individual attempt, not a stable property of the
agent's identity — this fixes that.

Practical consequence: any Attempt data logged before this fix doesn't
have a reliable tier value to route on. Wipe graph/kuzu_db before the
first Phase 2 routing test — same "start clean" step used throughout
this project when the schema changes.
"""

from __future__ import annotations

from datetime import datetime

import kuzu


def _create_if_missing(conn: "kuzu.Connection", ddl: str) -> None:
    """
    Kuzu's DDL support for `IF NOT EXISTS` varies by version — attempt the
    CREATE and swallow the specific "already exists" error on repeat runs
    rather than depending on syntax that isn't consistently supported.
    """
    try:
        conn.execute(ddl)
    except RuntimeError as exc:
        if "already exists" not in str(exc).lower():
            raise


def init_schema(db_path: str) -> kuzu.Database:
    """
    Node table PRIMARY KEY syntax: uses a trailing `PRIMARY KEY (col)`
    clause, not an inline `col TYPE PRIMARY KEY` modifier. Empirically
    determined — this exact Kuzu 0.4.2 install rejects the inline form
    with a confusing parser error ("missing ',' at 'PRIMARY'") even on
    a table shape that worked before, and only the trailing-clause form
    was confirmed to succeed (scripts/diagnose_kuzu_variants.py).
    """
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    _create_if_missing(conn, """
        CREATE NODE TABLE Agent(
            id STRING,
            model_name STRING,
            PRIMARY KEY (id)
        )
    """)

    _create_if_missing(conn, """
        CREATE NODE TABLE Task(
            id STRING,
            task_type STRING,
            difficulty STRING,
            benchmark_source STRING,
            PRIMARY KEY (id)
        )
    """)

    _create_if_missing(conn, """
        CREATE NODE TABLE Attempt(
            id STRING,
            tier STRING,
            verbalized_conf DOUBLE,
            behavioral_conf DOUBLE,
            outcome_conf DOUBLE,
            fused_2way DOUBLE,
            fused_3way DOUBLE,
            brier_2way DOUBLE,
            brier_3way DOUBLE,
            succeeded BOOLEAN,
            timestamp TIMESTAMP,
            PRIMARY KEY (id)
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
    """Signature unchanged from Phase 0 — tier now lands on the Attempt
    node instead of the Agent node (see module docstring for why)."""

    conn.execute(
        "MERGE (a:Agent {id: $id}) SET a.model_name = $model_name",
        {"id": agent_id, "model_name": model_name},
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
               id: $id, tier: $tier, verbalized_conf: $verbalized_conf,
               behavioral_conf: $behavioral_conf, outcome_conf: $outcome_conf,
               fused_2way: $fused_2way, fused_3way: $fused_3way,
               brier_2way: $brier_2way, brier_3way: $brier_3way,
               succeeded: $succeeded, timestamp: timestamp($timestamp)
           })""",
        {
            "id": attempt_id,
            "tier": tier,
            "verbalized_conf": verbalized_conf,
            "behavioral_conf": behavioral_conf,
            "outcome_conf": outcome_conf,
            "fused_2way": fused_2way,
            "fused_3way": fused_3way,
            "brier_2way": brier_2way,
            "brier_3way": brier_3way,
            "succeeded": succeeded,
            # Real formatted timestamp, not the literal string "now" —
            # Kuzu's timestamp() conversion function expects an actual
            # "YYYY-MM-DD hh:mm:ss[.zzzzzz]"-shaped string, not a magic
            # keyword. "now" isn't valid input to it.
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
    """Unchanged from Phase 0 — still useful for a human-readable trend view."""
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


def tier_history_for_routing(conn: "kuzu.Connection", task_type: str, difficulty: str) -> dict:
    """
    New for Phase 2's trust-based router: {tier: {avg_brier, n}} for a
    specific (task_type, difficulty) combination — this is the query the
    Phase 0 schema couldn't reliably answer before the tier-on-Attempt fix.
    """
    result = conn.execute(
        """MATCH (att:Attempt)-[:ON_TASK]->(t:Task)
           WHERE t.task_type = $task_type AND t.difficulty = $difficulty
           RETURN att.tier AS tier, avg(att.brier_3way) AS avg_brier, count(*) AS n""",
        {"task_type": task_type, "difficulty": difficulty},
    )
    history = {}
    while result.has_next():
        row = result.get_next()
        history[row[0]] = {"avg_brier": row[1], "n": row[2]}
    return history