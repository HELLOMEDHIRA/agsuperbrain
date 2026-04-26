"""
schema.py — KùzuDB DDL (Phase 1 + Phase 3 + Phase 4).

Kùzu does not expose ad-hoc B-tree indexes on arbitrary STRING columns (e.g.
`source_path`); primary keys and optional FTS (see `GraphStore._ensure_fts_indices`) apply.

Node tables:
  Module, Function          ← Phase 1 (code)
  Document, Section,
  Concept                   ← Phase 3 (documents)
  AudioSource, Transcript   ← Phase 4 (audio/video)

Edge tables:
  CALLS                     ← Function → Function
  DEFINED_IN                ← Function → Module
  CONTAINS                  ← Document/Section → Section/Concept
  SOURCE                    ← Transcript → AudioSource
  FOLLOWS                   ← Transcript → Transcript  (temporal order)
"""

SCHEMA_VERSION = "0.2.0"

# ── Phase 1: Code ─────────────────────────────────────────────────────────────

CREATE_MODULE_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Module (
    id          STRING,
    name        STRING,
    source_path STRING,
    source_type STRING,
    language    STRING,
    schema_version STRING,
    PRIMARY KEY (id)
)
"""

CREATE_FUNCTION_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Function (
    id             STRING,
    name           STRING,
    qualified_name STRING,
    source_path    STRING,
    source_type    STRING,
    language       STRING,
    start_line     INT64,
    end_line       INT64,
    is_method      BOOLEAN,
    class_name     STRING,
    body           STRING,
    docstring      STRING,
    PRIMARY KEY (id)
)
"""

CREATE_CALLS_TABLE = """
CREATE REL TABLE IF NOT EXISTS CALLS (
    FROM Function TO Function,
    call_line       INT64,
    source_path     STRING,
    confidence      DOUBLE,
    confidence_type STRING
)
"""

CREATE_DEFINED_IN_TABLE = """
CREATE REL TABLE IF NOT EXISTS DEFINED_IN (
    FROM Function TO Module,
    source_path STRING
)
"""

# ── Phase 3: Documents ────────────────────────────────────────────────────────

CREATE_DOCUMENT_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Document (
    id          STRING,
    title       STRING,
    source_path STRING,
    source_type STRING,
    PRIMARY KEY (id)
)
"""

CREATE_SECTION_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Section (
    id          STRING,
    title       STRING,
    level       INT64,
    source_path STRING,
    source_type STRING,
    chunk_id    STRING,
    PRIMARY KEY (id)
)
"""

CREATE_CONCEPT_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Concept (
    id          STRING,
    text        STRING,
    source_path STRING,
    source_type STRING,
    chunk_id    STRING,
    PRIMARY KEY (id)
)
"""

CREATE_CONTAINS_TABLE = """
CREATE REL TABLE IF NOT EXISTS CONTAINS (
    FROM Document TO Section,
    FROM Document TO Concept,
    FROM Section  TO Section,
    FROM Section  TO Concept,
    relation    STRING,
    source_path STRING
)
"""

# ── Phase 4: Audio / Video ────────────────────────────────────────────────────

CREATE_AUDIOSOURCE_TABLE = """
CREATE NODE TABLE IF NOT EXISTS AudioSource (
    id          STRING,
    title       STRING,
    source_url  STRING,
    source_type STRING,
    wav_path    STRING,
    duration_s  DOUBLE,
    PRIMARY KEY (id)
)
"""

CREATE_TRANSCRIPT_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Transcript (
    id          STRING,
    text        STRING,
    start_sec   DOUBLE,
    end_sec     DOUBLE,
    seq_index   INT64,
    chunk_id    STRING,
    source_path STRING,
    source_type STRING,
    PRIMARY KEY (id)
)
"""

CREATE_SOURCE_TABLE = """
CREATE REL TABLE IF NOT EXISTS SOURCE (
    FROM Transcript TO AudioSource,
    source_path STRING
)
"""

CREATE_FOLLOWS_TABLE = """
CREATE REL TABLE IF NOT EXISTS FOLLOWS (
    FROM Transcript TO Transcript,
    source_path STRING
)
"""

CREATE_DOCUMENTED_BY_TABLE = """
CREATE REL TABLE IF NOT EXISTS DOCUMENTED_BY (
    FROM Function TO Section,
    source_path STRING,
    confidence DOUBLE
)
"""

CREATE_MENTIONS_TABLE = """
CREATE REL TABLE IF NOT EXISTS MENTIONS (
    FROM Transcript TO Function,
    FROM Transcript TO Concept,
    FROM Transcript TO Section,
    FROM Function TO Concept,
    FROM Section TO Function,
    source_path STRING,
    confidence DOUBLE
)
"""

CREATE_READS_TABLE = """
CREATE REL TABLE IF NOT EXISTS READS (
    FROM Function TO Function,
    source_path STRING,
    var_name STRING
)
"""

CREATE_WRITES_TABLE = """
CREATE REL TABLE IF NOT EXISTS WRITES (
    FROM Function TO Function,
    source_path STRING,
    var_name STRING
)
"""

CREATE_RETURNS_TYPE_TABLE = """
CREATE REL TABLE IF NOT EXISTS RETURNS_TYPE (
    FROM Function TO Function,
    source_path STRING,
    type_name STRING
)
"""

CREATE_PARAM_TYPE_TABLE = """
CREATE REL TABLE IF NOT EXISTS PARAM_TYPE (
    FROM Function TO Function,
    source_path STRING,
    param_name STRING,
    type_name STRING
)
"""

# ── Community detection ──────────────────────────────────────────────────────

CREATE_COMMUNITY_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Community (
    id          STRING,
    name        STRING,
    size        INT64,
    modularity  DOUBLE,
    PRIMARY KEY (id)
)
"""

CREATE_IN_COMMUNITY_TABLE = """
CREATE REL TABLE IF NOT EXISTS IN_COMMUNITY (
    FROM Function TO Community,
    source_path STRING
)
"""

ALL_DDL: list[str] = [
    # Phase 1
    CREATE_MODULE_TABLE,
    CREATE_FUNCTION_TABLE,
    CREATE_CALLS_TABLE,
    CREATE_DEFINED_IN_TABLE,
    # Phase 3
    CREATE_DOCUMENT_TABLE,
    CREATE_SECTION_TABLE,
    CREATE_CONCEPT_TABLE,
    CREATE_CONTAINS_TABLE,
    # Phase 4
    CREATE_AUDIOSOURCE_TABLE,
    CREATE_TRANSCRIPT_TABLE,
    CREATE_SOURCE_TABLE,
    CREATE_FOLLOWS_TABLE,
    # Cross-modal (P2)
    CREATE_DOCUMENTED_BY_TABLE,
    CREATE_MENTIONS_TABLE,
    # Data-flow (P2)
    CREATE_READS_TABLE,
    CREATE_WRITES_TABLE,
    CREATE_RETURNS_TYPE_TABLE,
    CREATE_PARAM_TYPE_TABLE,
    # Community detection
    CREATE_COMMUNITY_TABLE,
    CREATE_IN_COMMUNITY_TABLE,
]
