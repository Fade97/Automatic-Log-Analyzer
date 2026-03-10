import json
import re
import pytest
import jsonschema
from analyze import Filter, FilterGroup, load_filters


def write_json(tmp_path, data):
    p = tmp_path / "filters.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_returns_filter_groups(filter_json):
    groups = load_filters(filter_json)
    assert len(groups) == 1
    assert isinstance(groups[0], FilterGroup)


def test_group_fields(filter_json):
    group = load_filters(filter_json)[0]
    assert group.name == "kernel panic"
    assert group.criticality == "high"


def test_filter_objects_created(filter_json):
    group = load_filters(filter_json)[0]
    assert len(group.filters) == 1
    filt = group.filters[0]
    assert isinstance(filt, Filter)
    assert filt.filter == "kernel panic"
    assert filt.regex is False
    assert filt.case_sensitive is False
    assert filt.word_match is False


def test_multiple_groups(tmp_path):
    data = [
        {"name": "group1", "criticality": "high",
         "filters": [{"filter": "a", "regex": False, "case_sensitive": False, "word_match": False}]},
        {"name": "group2", "criticality": "medium",
         "filters": [{"filter": "b", "regex": True, "case_sensitive": True, "word_match": True}]},
    ]
    groups = load_filters(write_json(tmp_path, data))
    assert len(groups) == 2
    assert groups[1].filters[0].regex is True
    assert groups[1].filters[0].case_sensitive is True


def test_multiple_filters_in_group(tmp_path):
    data = [{"name": "g", "criticality": "low", "filters": [
        {"filter": "a", "regex": False, "case_sensitive": False, "word_match": False},
        {"filter": "b", "regex": False, "case_sensitive": False, "word_match": False},
    ]}]
    group = load_filters(write_json(tmp_path, data))[0]
    assert len(group.filters) == 2


def test_empty_array(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]")
    with pytest.raises(jsonschema.ValidationError):
        load_filters(str(p))


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_filters("nonexistent_file.json")


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        load_filters(str(p))


_VALID_FILTER = {"filter": "a", "regex": False, "case_sensitive": False, "word_match": False}


def test_missing_name_field(tmp_path):
    data = [{"criticality": "high", "filters": [_VALID_FILTER]}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_invalid_criticality_value(tmp_path):
    data = [{"name": "g", "criticality": "critical", "filters": [_VALID_FILTER]}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_missing_filter_key(tmp_path):
    data = [{"name": "g", "criticality": "high",
             "filters": [{"regex": False, "case_sensitive": False, "word_match": False}]}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_filter_regex_wrong_type(tmp_path):
    data = [{"name": "g", "criticality": "high",
             "filters": [{"filter": "a", "regex": "yes", "case_sensitive": False, "word_match": False}]}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_additional_property_on_group(tmp_path):
    data = [{"name": "g", "criticality": "high", "filters": [_VALID_FILTER], "priority": 1}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_empty_filters_array(tmp_path):
    data = [{"name": "g", "criticality": "high", "filters": []}]
    with pytest.raises(jsonschema.ValidationError):
        load_filters(write_json(tmp_path, data))


def test_invalid_regex_pattern(tmp_path):
    data = [{"name": "g", "criticality": "high",
             "filters": [{"filter": "[", "regex": True, "case_sensitive": False, "word_match": False}]}]
    with pytest.raises(re.error):
        load_filters(write_json(tmp_path, data))
