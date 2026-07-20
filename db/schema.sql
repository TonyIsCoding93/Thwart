CREATE TABLE section_type (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE label (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    effective_time DATE
);

CREATE TABLE label_section (
    id SERIAL PRIMARY KEY,
    label_id TEXT NOT NULL REFERENCES label(id),
    section_type_id INTEGER NOT NULL REFERENCES section_type(id),
    content_type TEXT NOT NULL,
    content TEXT NOT NULL
);
