CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS client_memory (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_memory_client ON client_memory(client_id);
CREATE INDEX IF NOT EXISTS idx_client_memory_embedding ON client_memory USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS soul_configs (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL,
    container_name VARCHAR(255),
    soul_data JSONB NOT NULL DEFAULT '{}',
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_soul_client ON soul_configs(client_id);

CREATE TABLE IF NOT EXISTS skills_registry (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    description TEXT,
    category VARCHAR(100),
    display_category VARCHAR(100),
    tags JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}'
);

INSERT INTO skills_registry (name, display_name, description, category, display_category) VALUES
    ('chat', 'Chat', 'Basic chat conversation capability', 'core', 'Core'),
    ('memory', 'Memory', 'Long-term conversation memory with vector search', 'core', 'Core'),
    ('tasks', 'Task Scheduling', 'Schedule and manage recurring tasks', 'productivity', 'Productivity'),
    ('gdrive', 'Google Drive', 'Read and write files from Google Drive', 'integration', 'Integrations'),
    ('email', 'Email', 'Send and receive emails via SMTP/IMAP', 'integration', 'Integrations'),
    ('api', 'API Integration', 'Connect to external REST APIs', 'integration', 'Integrations')
ON CONFLICT (name) DO NOTHING;

-- Backward compat view for old code referencing 'skills' table
CREATE OR REPLACE VIEW skills AS SELECT id, name, display_name, description, category, is_active, config FROM skills_registry;
