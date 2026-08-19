from db.connection import get_connection


def load_section_types(conn):
    cache = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM section_type")
        for row in cur.fetchall():
            cache[row[1]] = row[0]
    return cache


def get_or_create_section_type(conn, cache, name):
    if name in cache:
        return cache[name]

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO section_type (name) VALUES (%s) RETURNING id",
            (name,),
        )
        new_id = cur.fetchone()[0]

    cache[name] = new_id
    return new_id


def insert_label(conn, label):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO label (id, set_id, version, effective_time)
            VALUES (%s, %s, %s, %s)
            """,
            (label["id"], label["set_id"], label["version"], label["effective_time"]),
        )


def insert_sections(conn, cache, label_id, sections):
    with conn.cursor() as cur:
        for section in sections:
            type_id = get_or_create_section_type(conn, cache, section["section_name"])
            cur.execute(
                """
                INSERT INTO label_section
                    (label_id, section_type_id, content_type, content)
                VALUES (%s, %s, %s, %s)
                """,
                (label_id, type_id, "text", section["content"]),
            )