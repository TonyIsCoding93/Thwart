



REQUIRED_FIELDS = ["id", "set_id", "version", "effective_time", "openfda"]

def validate(record):
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"Missing Required Field: {field}")
        
    return errors





