import json
import pytest
from analyze import Filter, FilterGroup


@pytest.fixture
def filter_json(tmp_path):
    data = [
        {
            "name": "kernel panic",
            "criticality": "high",
            "filters": [
                {"filter": "kernel panic", "regex": False, "case_sensitive": False, "word_match": False}
            ],
        }
    ]
    p = tmp_path / "filters.json"
    p.write_text(json.dumps(data))
    return str(p)


@pytest.fixture
def log_file(tmp_path):
    def _make(lines):
        p = tmp_path / "test.log"
        p.write_text("\n".join(lines))
        return str(p)
    return _make


@pytest.fixture
def sample_groups():
    return [
        FilterGroup("kernel panic", "high",
                    [Filter("kernel panic", False, False, False)]),
        FilterGroup("blocking process", "medium",
                    [Filter(r"blocked for more than \d+ seconds", True, False, False)]),
    ]
