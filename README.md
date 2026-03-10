# Automatic Log Analyzer

A CLI tool for scanning log files with configurable filters. Streams line-by-line so it works on files of any size without loading them into memory.

## Requirements

Python 3.7+, no third-party dependencies.

## Usage

```
python analyze.py <log_file> [options]
```

### Arguments

| Argument | Description | Default |
|---|---|---|
| `log_file` | Path to the log file to analyze | *(required)* |
| `--filter <file>` | Path to the filter configuration file | `filter.json` |
| `--criticality <level>` | Minimum criticality to report (`high`, `medium`, `low`) | `high` |
| `-s` | Print stats after analysis (line count, match count, RAM usage) | off |
| `--json` | Output results as JSON instead of colored text | off |

### Examples

```bash
# Basic analysis using the default filter.json
python analyze.py system.log

# Show all medium and higher severity matches
python analyze.py system.log --criticality medium

# Use a custom filter file and print stats
python analyze.py system.log --filter my_filters.json -s

# Output results as JSON
python analyze.py system.log --json

# JSON output with stats block
python analyze.py system.log --json -s
```

## Output

### Default (colored text)

Each matched line is printed with a color-coded criticality badge, padded to align columns:

```
l2082 [MEDIUM] (blocking process): ... task kworker/2:1 blocked for more than 20 seconds.
l2105 [MEDIUM] (blocking process): ... task sm:AO:2615 blocked for more than 20 seconds.
l2133 [HIGH  ] (kernel panic    ): ... Kernel panic - not syncing: hung_task: blocked tasks
```

With `-s`, a stats block is appended:

```
--- Stats ---
Lines scanned : 3200
Total matches : 3
  MEDIUM (blocking process): 2
  HIGH   (kernel panic    ): 1

RAM: 1.2 KB | 3.4 KB | 5.6 KB
```

The RAM line shows `min | avg | max` memory usage sampled across the run.

### JSON (`--json`)

```json
{
  "filters": [
    {"id": 0, "name": "blocking process", "criticality": "medium"},
    {"id": 1, "name": "kernel panic",     "criticality": "high"}
  ],
  "matches": [
    {"filter_id": 0, "line_number": 2082, "text": "... blocked for more than 20 seconds."},
    {"filter_id": 0, "line_number": 2105, "text": "... blocked for more than 20 seconds."},
    {"filter_id": 1, "line_number": 2133, "text": "... Kernel panic - not syncing: ..."}
  ]
}
```

Each filter name appears once in `"filters"`. Matches reference filters by `filter_id` to avoid repeating the name. With `-s`, a `"stats"` key is added containing line count, total matches, per-filter match counts, and RAM usage.

## Building from source

Compile to a standalone Windows `.exe` using [PyInstaller](https://pyinstaller.org):

```bash
pip install pyinstaller
pyinstaller --onefile --name log-analyzer analyze.py
```

The executable is written to `dist\log-analyzer.exe`. Run it the same way as the Python script:

```
log-analyzer.exe system.log --criticality medium -s
```

A pre-built Windows executable is attached to each [GitHub Release](../../releases).

## Development

Install test dependencies and run the test suite:

```bash
pip install pytest
pytest -v
```

## Filter Configuration

Filters are defined in a JSON file (default: `filter.json`). The file contains an array of filter groups:

```json
[
  {
    "name": "kernel panic",
    "criticality": "high",
    "filters": [
      {
        "filter": "kernel panic",
        "regex": false,
        "case_sensitive": false,
        "word_match": false
      }
    ]
  },
  {
    "name": "blocking process",
    "criticality": "medium",
    "filters": [
      {
        "filter": "blocked for more than .* seconds",
        "regex": true,
        "case_sensitive": false,
        "word_match": false
      }
    ]
  }
]
```

### Filter group fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name for this group |
| `criticality` | string | `high`, `medium`, or `low` |
| `filters` | array | One or more filter rules (any match triggers the group) |

### Filter rule fields

| Field | Type | Description |
|---|---|---|
| `filter` | string | The search string or regex pattern |
| `regex` | bool | If `true`, treat `filter` as a regular expression |
| `case_sensitive` | bool | If `false`, match is case-insensitive |
| `word_match` | bool | If `true`, only match whole words (`\b` boundaries) |

A line matches a group if **any** of its filter rules match. At most one match per group is reported per line.
