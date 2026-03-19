// ============================================================
// Agent Context Graph — Schema Definition
// Version: 2.0.0
// Date: 2026-03-20
// Ref: REQUIREMENTS-agent-context-graph-v2.md
// ============================================================

// --- Node Types ---

// Agent: AI agent definitions from AGENTS.md
// Properties: agent_id, name, emoji, role, society, type, pane_id, keywords[]
CREATE NODE TABLE IF NOT EXISTS Agent (
  agent_id STRING PRIMARY KEY,
  name STRING,
  emoji STRING,
  role STRING,
  society STRING,
  type STRING,
  pane_id STRING,
  keywords STRING[]
);

// Skill: Skill definitions from SKILL/*.md
// Properties: skill_id, name, category, path, version, priority, keywords[], scripts[]
CREATE NODE TABLE IF NOT EXISTS Skill (
  skill_id STRING PRIMARY KEY,
  name STRING,
  category STRING,
  path STRING,
  version STRING,
  priority STRING,
  description STRING,
  keywords STRING[],
  scripts STRING[],
  tags STRING[]
);

// KnowledgeDoc: Knowledge documents from KNOWLEDGE/**/*.md
// Properties: doc_id, title, path, category, type, token_estimate, last_modified
CREATE NODE TABLE IF NOT EXISTS KnowledgeDoc (
  doc_id STRING PRIMARY KEY,
  title STRING,
  path STRING,
  category STRING,
  type STRING,
  content_summary STRING,
  token_estimate INT,
  last_modified STRING
);

// DataSource: Data files from personal-data/**/*.json
// Properties: ds_id, name, path, schema_type, is_ssot, write_cli
CREATE NODE TABLE IF NOT EXISTS DataSource (
  ds_id STRING PRIMARY KEY,
  name STRING,
  path STRING,
  schema_type STRING,
  is_ssot BOOLEAN,
  write_cli STRING
);

// ExternalService: External API services
// Properties: svc_id, name, api_url, auth_type
CREATE NODE TABLE IF NOT EXISTS ExternalService (
  svc_id STRING PRIMARY KEY,
  name STRING,
  api_url STRING,
  auth_type STRING
);

// --- Edge Types (AgentRelation table — separate from CodeRelation) ---

// USES_SKILL: Agent → Skill
CREATE REL TABLE IF NOT EXISTS USES_SKILL (
  FROM Agent TO Skill,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// DEPENDS_ON: Skill → KnowledgeDoc
CREATE REL TABLE IF NOT EXISTS DEPENDS_ON (
  FROM Skill TO KnowledgeDoc,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// READS_DATA: Skill → DataSource
CREATE REL TABLE IF NOT EXISTS READS_DATA (
  FROM Skill TO DataSource,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// WRITES_DATA: Skill → DataSource
CREATE REL TABLE IF NOT EXISTS WRITES_DATA (
  FROM Skill TO DataSource,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// CALLS_SERVICE: Skill → ExternalService
CREATE REL TABLE IF NOT EXISTS CALLS_SERVICE (
  FROM Skill TO ExternalService,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// COMPOSES: Skill → Skill (inter-skill dependency)
CREATE REL TABLE IF NOT EXISTS COMPOSES (
  FROM Skill TO Skill,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// ROUTES_TO: Agent → Agent (task routing)
CREATE REL TABLE IF NOT EXISTS ROUTES_TO (
  FROM Agent TO Agent,
  weight DOUBLE DEFAULT 1.0,
  created_at STRING
);

// IMPLEMENTS_CODE: Skill → code file (Phase 3 bridge)
// Links skill definitions to their implementation files in the code graph
// CREATE REL TABLE IF NOT EXISTS IMPLEMENTS_CODE (
//   FROM Skill TO Function,
//   weight DOUBLE DEFAULT 1.0,
//   created_at STRING
// );
