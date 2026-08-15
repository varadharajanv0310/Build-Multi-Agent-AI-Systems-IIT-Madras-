-- Faultline store.
--
-- Two design commitments are visible in this schema:
--
-- 1. The trace is the product. `events` is not a debug log — for a tool whose
--    entire value proposition is trustworthiness, the reasoning record is what
--    the user consumes. That inverts the usual relationship: if the trace
--    breaks, the product breaks, so it cannot rot quietly.
--
-- 2. Nothing is unattributed. Every claim carries a paper and a locator;
--    every judgment carries the model and lineage that made it. A claim
--    stripped of its scope conditions is unusable, so those are columns, not
--    an afterthought in a JSON blob.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    mode          TEXT NOT NULL,          -- 'question' | 'paper'
    question      TEXT,
    paper_ref     TEXT,
    field         TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    -- Exact roster used, so a reported number can be tied to the config that
    -- produced it. Reproducibility is a judged criterion.
    config_json   TEXT,
    ledger_json   TEXT
);

-- Content-hash cache. Load-bearing rather than an optimisation: papers recur
-- heavily across questions, and without reuse the free-tier quota maths does
-- not work across 20+ runs.
CREATE TABLE IF NOT EXISTS llm_cache (
    key           TEXT PRIMARY KEY,       -- sha256(provider|model|messages|schema)
    provider      TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    lineage       TEXT NOT NULL,
    response_json TEXT NOT NULL,
    raw_text      TEXT,
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    ts            TEXT NOT NULL,
    stage         TEXT,                   -- pipeline stage
    role          TEXT,                   -- Role enum value
    provider      TEXT,
    model_id      TEXT,
    lineage       TEXT,
    kind          TEXT NOT NULL,          -- call | cache_hit | failover | quota | error | note
    subject_id    TEXT,                   -- claim / pair / conflict id
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    latency_ms    INTEGER DEFAULT 0,
    attempts      INTEGER DEFAULT 1,
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run    ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_id);

CREATE TABLE IF NOT EXISTS papers (
    id            TEXT PRIMARY KEY,       -- OpenAlex id, else DOI
    doi           TEXT,
    title         TEXT,
    year          INTEGER,
    venue         TEXT,
    authors_json  TEXT,
    oa_status     TEXT,
    fulltext_source TEXT,                 -- pmc_xml | arxiv_tex | pdf | abstract_only | none
    retracted     INTEGER DEFAULT 0,
    metadata_json TEXT,
    retrieved_at  TEXT NOT NULL
);

-- Screening decisions, kept with a reason. Borderline exclusions are what a
-- reviewer is asked to defend, so they must survive in the record.
CREATE TABLE IF NOT EXISTS screening (
    run_id        TEXT NOT NULL REFERENCES runs(id),
    paper_id      TEXT NOT NULL,
    decision      TEXT NOT NULL,          -- include | exclude | borderline
    reason        TEXT,
    confidence    REAL,
    model_id      TEXT,
    lineage       TEXT,
    ts            TEXT NOT NULL,
    PRIMARY KEY (run_id, paper_id)
);

-- Append-only. Qualifiers are the raw material of conflict analysis, not
-- metadata: a claim without its scope conditions cannot be compared to
-- anything.
CREATE TABLE IF NOT EXISTS claims (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES runs(id),
    paper_id          TEXT NOT NULL,
    text              TEXT NOT NULL,
    claim_type        TEXT,               -- numeric | empirical | methodological | definitional
    citation_function TEXT,               -- support | contrast | background | method_use
    population        TEXT,
    sample_size       TEXT,
    design            TEXT,
    direction         TEXT,               -- positive | negative | null | mixed
    magnitude         TEXT,
    uncertainty       TEXT,
    outcome_measure   TEXT,
    timepoint         TEXT,
    scope_conditions_json TEXT,
    hedges_json       TEXT,
    confidence_tag    TEXT,               -- V verified | R recalled | U uncertain
    locator           TEXT,               -- section / paragraph / table
    extracted_by      TEXT,               -- model id
    lineage           TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_run   ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_paper ON claims(paper_id);

-- Each side of an opposed judgement is stored separately. Disagreement is the
-- signal; averaging it away would defeat the point of running two lineages.
CREATE TABLE IF NOT EXISTS commensurability (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    claim_a       TEXT NOT NULL,
    claim_b       TEXT NOT NULL,
    side          TEXT NOT NULL,          -- a | b  (which assessor)
    comparable    INTEGER,
    reason_code   TEXT,
    argument      TEXT,
    confidence    REAL,
    model_id      TEXT,
    lineage       TEXT,
    ts            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comm_pair ON commensurability(run_id, claim_a, claim_b);

CREATE TABLE IF NOT EXISTS conflicts (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    claim_a       TEXT NOT NULL,
    claim_b       TEXT NOT NULL,
    kind          TEXT,                   -- opposite_direction | effect_vs_null | magnitude
    agreement     REAL,                   -- inter-model agreement on commensurability
    ts            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS explanations (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    conflict_id   TEXT NOT NULL REFERENCES conflicts(id),
    stance        TEXT NOT NULL,          -- population | dose | measurement | timing | power | bias
    argument      TEXT,
    -- An explanation that cites no concrete study attribute is a post-hoc
    -- rationalisation, and the adjudicator is entitled to reject it as such.
    cited_attributes_json TEXT,
    confidence    REAL,
    model_id      TEXT,
    lineage       TEXT,
    ts            TEXT NOT NULL
);

-- The adjudicator's veto is the most important behaviour in the system: a
-- verdict of 'unresolved' is what produces a gap.
CREATE TABLE IF NOT EXISTS verdicts (
    conflict_id   TEXT PRIMARY KEY REFERENCES conflicts(id),
    run_id        TEXT NOT NULL REFERENCES runs(id),
    verdict       TEXT NOT NULL,          -- explained | unresolved | not_a_conflict
    winning_stance TEXT,
    reasoning     TEXT,
    confidence    REAL,
    model_id      TEXT,
    lineage       TEXT,
    ts            TEXT NOT NULL
);

-- A gap is an unresolved disagreement, but not only that: a methodological
-- gap is not a disagreement at all, which is why bucket is explicit.
CREATE TABLE IF NOT EXISTS gaps (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    conflict_id   TEXT REFERENCES conflicts(id),
    bucket        TEXT NOT NULL,          -- empirical | methodological | theoretical | translational
    status        TEXT NOT NULL,          -- open | unimportant | already_closed | intractable
    proposition   TEXT NOT NULL,          -- stated as testable, not "more research is needed"
    rationale     TEXT,
    ts            TEXT NOT NULL
);
