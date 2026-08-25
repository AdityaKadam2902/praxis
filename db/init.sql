-- db/init.sql
-- Phase 0 only actually needs Kuzu for the calibration graph. This schema is
-- seeded now so Phase 1 (routing, budgets, multi-task queueing) has
-- somewhere to land without a migration scramble later.

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    tier TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    benchmark_source TEXT,
    prompt TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT REFERENCES agents(id),
    task_id TEXT REFERENCES tasks(id),
    verbalized_conf DOUBLE PRECISION,
    behavioral_conf DOUBLE PRECISION,
    outcome_conf DOUBLE PRECISION,
    fused_2way DOUBLE PRECISION,
    fused_3way DOUBLE PRECISION,
    brier_2way DOUBLE PRECISION,
    brier_3way DOUBLE PRECISION,
    succeeded BOOLEAN,
    tokens_used INTEGER,          -- Phase 5 cost governance lands here
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Phase 5 cost tracking table, seeded early so it's not an afterthought:
CREATE TABLE IF NOT EXISTS cost_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID REFERENCES attempts(id),
    model_name TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
