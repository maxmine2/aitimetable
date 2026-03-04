# analysis.py — Usage

Scrapes all NSU timetables from `table.nsu.ru` into a normalized `nsu_data.json`.

## Dependencies

```
pip install aiohttp beautifulsoup4 aiolimiter
```

## Run

```bash
python analysis.py
```

Discovers all faculties → scrapes group metadata (faculty, degree, year, specialty) → fetches every group's schedule concurrently (rate-limited to ~5 req/s) → writes `nsu_data.json`.

Progress is logged to the console.

## Pipeline

```
GET /faculties            → list of faculty slugs
GET /faculty/{slug}  ×N   → group IDs + metadata (degree, year, specialty)
GET /group/{id}      ×M   → timetable HTML → parsed schedule entries
                          → nsu_data.json
```

## Output

See [DATA_FORMAT.md](DATA_FORMAT.md) for the full JSON schema.
