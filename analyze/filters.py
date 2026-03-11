"""Filter loading and schema validation."""
import json
import re

import jsonschema

from analyze.models import Filter, FilterGroup

filters_file = "filter.json"

_FILTER_SCHEMA = {
    "type": "array", "minItems": 1,
    "items": {
        "type": "object",
        "required": ["name", "filters", "criticality"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "criticality": {"type": "string", "enum": ["low", "medium", "high"]},
            "logic": {"type": "string", "enum": ["or", "and"]},
            "filters": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["filter", "regex", "case_sensitive", "word_match"],
                    "additionalProperties": False,
                    "properties": {
                        "filter": {"type": "string", "minLength": 1},
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "word_match": {"type": "boolean"},
                        "negate": {"type": "boolean"},
                    }
                }
            }
        }
    }
}


def load_filters(filters_file):
    """Load filter groups from a JSON configuration file.

    Args:
        filters_file (str): Path to the JSON filter configuration file.

    Returns:
        list[FilterGroup]: Parsed filter groups with their Filter objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        jsonschema.ValidationError: If the file does not conform to the filter schema.
        re.error: If a filter with regex=True contains an invalid regular expression.
    """
    with open(filters_file, "r") as f:
        data = json.load(f)
    jsonschema.validate(data, _FILTER_SCHEMA)
    for group in data:
        for filt in group["filters"]:
            if filt["regex"]:
                re.compile(filt["filter"])
    groups = []
    for group in data:
        filter_objs = [
            Filter(f["filter"], f["regex"], f["case_sensitive"], f["word_match"],
                   negate=f.get("negate", False))
            for f in group["filters"]
        ]
        groups.append(FilterGroup(
            group["name"], group["criticality"], filter_objs,
            logic=group.get("logic", "or")
        ))
    return groups
