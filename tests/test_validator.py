from core.validator import validate

def test_empty_report_all_missing():
    result = validate({})
    assert len(result) == 5

def test_partial_record():
    result = validate({"id": "a", "set_id": "b"})
    assert len(result) == 3

def test_complete_record_passes():
    record = {"id": "a",
        "set_id": "b",
        "version": "2",
        "effective_time": "20210902",
        "openfda": {},
    }
    assert validate(record) == []

