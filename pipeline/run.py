from collections import Counter

from core.validator import validate
from core.normalizer import normalize
from db.connection import get_connection
from db.writer import load_section_types, insert_label, insert_sections
from pipeline.fetcher import fetch_all

BATCH_SIZE = 100


def run(max_records=1000):
    conn = get_connection()
    cache = load_section_types(conn)

    stats = Counter()
    reject_reasons = Counter()

    for i, record in enumerate(fetch_all(max_records=max_records), start=1):
        errors = validate(record)
        if errors:
            stats["rejected"] += 1
            for e in errors:
                reject_reasons[e] += 1
            continue

        try:
            label, sections = normalize(record)
            insert_label(conn, label)
            insert_sections(conn, cache, label["id"], sections)
            stats["inserted"] += 1
        except Exception as e:
            conn.rollback()
            stats["failed"] += 1
            reject_reasons[type(e).__name__] += 1
            continue

        if i % BATCH_SIZE == 0:
            conn.commit()
            print(f"{i} processed")

    conn.commit()
    conn.close()

    print("\n--- summary ---")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print("\n--- reject reasons ---")
    for reason, count in reject_reasons.most_common():
        print(f"{count:5d}  {reason}")


if __name__ == "__main__":
    run(max_records=200)