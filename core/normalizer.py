


from core.validator import REQUIRED_FIELDS



SKIP_FIELDS = set(REQUIRED_FIELDS)
def normalize(record):
    label = {
        "id":record["id"],
        "set_id":record["set_id"],
        "version": int(record["version"]),
        "effective_time": record["effective_time"],

    }

    sections = []
    for field, value in record.items():
        if field in SKIP_FIELDS:
            continue

        if isinstance(value, list):
            text = value[0]
        else: 
            text = value
        
        sections.append({
        "section_name": field,
            "content": text,
        })
    return label, sections
    