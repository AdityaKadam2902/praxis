"""
scripts/diagnose_kuzu_variants.py

Empirically tests several DDL phrasings against a real Kuzu 0.4.2
install, since the exact 2-column (PRIMARY KEY + one plain column) shape
is failing with a confusing parser error that a 3-column version of the
same table doesn't hit. Rather than guess further, let the actual
installed parser tell us which variant it accepts.

Run from the project root:
    python scripts/diagnose_kuzu_variants.py
"""

import shutil
import uuid
from pathlib import Path

import kuzu

BASE = Path(__file__).parent.parent / "graph"

VARIANTS = {
    "A: current 2-column, inline PRIMARY KEY (known failing)": """
        CREATE NODE TABLE Agent(
            id STRING PRIMARY KEY,
            model_name STRING
        )
    """,
    "B: 3-column, inline PRIMARY KEY (known working baseline)": """
        CREATE NODE TABLE Agent(
            id STRING PRIMARY KEY,
            model_name STRING,
            tier STRING
        )
    """,
    "C: 2-column, trailing PRIMARY KEY(...) clause instead of inline": """
        CREATE NODE TABLE Agent(
            id STRING,
            model_name STRING,
            PRIMARY KEY (id)
        )
    """,
    "D: 2-column, all on one line": (
        "CREATE NODE TABLE Agent(id STRING PRIMARY KEY, model_name STRING)"
    ),
    "E: 2-column, trailing comma after last field": """
        CREATE NODE TABLE Agent(
            id STRING PRIMARY KEY,
            model_name STRING,
        )
    """,
}

for label, ddl in VARIANTS.items():
    fresh_path = str(BASE / f"kuzu_variant_{uuid.uuid4().hex[:8]}")
    db = kuzu.Database(fresh_path)
    conn = kuzu.Connection(db)
    try:
        conn.execute(ddl)
        print(f"[SUCCESS] {label}")
    except Exception as exc:
        print(f"[FAILED]  {label}")
        print(f"           {type(exc).__name__}: {exc}".replace("\n", " "))
    finally:
        shutil.rmtree(fresh_path, ignore_errors=True)

print("\nWhichever variant(s) say SUCCESS tell us the syntax this Kuzu install actually accepts.")