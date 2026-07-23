from core.normalizer import normalize


def test_version_converted_to_int():
    label, _ = normalize({
        "id": "a", "set_id": "b", "version": "3",
        "effective_time": "20210902",
    })
    assert label["version"] == 3
    assert isinstance(label["version"], int)

def test_core_fields_excluded_from_sections():
    label, sections = normalize({
        "id": "a", "set_id": "b", "version": "3",
        "effective_time": "20210902",
        "warnings": ["Liver warning"],
    })
    names = [s["section_name"] for s in sections]
    assert "warnings" in names
    assert "id" not in names
    assert "version" not in names

def test_list_values_unwrapped():
    _, sections = normalize({
        "id": "a", "set_id": "b", "version": "3",
        "effective_time": "20210902",
        "warnings": ["Liver warning"],
    })
    assert sections[0]["content"] == "Liver warning"
