-- Admin-editable prompt overrides. Each LLM / Deep Research prompt has a built-in default
-- (in code, registered at startup); a row here overrides it by key. Deleting the row reverts
-- to the default. Loaded into the in-process prompt registry on engine startup.

CREATE TABLE IF NOT EXISTS prompt_overrides (
    key        text PRIMARY KEY,
    text       text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
