# Thwart

A Python pipeline that ingests openFDA drug label data, validates each record
against explicit rules, and normalizes the survivors into a PostgreSQL schema.

Thwart does not clean data. Records that fail validation are rejected with a
logged reason rather than repaired, and sections with no usable content are
dropped and reported by name. On drug labeling, a wrong guess is worse than a
missing record.

## The problem

The openFDA drug label endpoint serves data derived from Structured Product
Labeling documents that manufacturers submit to the FDA. The FDA's own
documentation notes there is "considerable variation between drug products in
terms of these sections and their contents."

That variation is the engineering problem. A single endpoint serves two
fundamentally different document types with no field indicating which is which:

- **Over-the-counter** labels carry sections like `purpose`, `do_not_use`,
  `ask_doctor`, `keep_out_of_reach_of_children`
- **Prescription** labels carry sections like `adverse_reactions`,
  `contraindications`, `nursing_mothers`, `clinical_pharmacology`

A 100-record sample contained **93 distinct field names**. Only five appeared
in 100% of records, and none of them describe the drug:

| Coverage | Fields |
| --- | --- |
| 100% | `id`, `set_id`, `version`, `effective_time`, `openfda` |
| 99% | `indications_and_usage`, `dosage_and_administration` |
| 82% | `warnings` |
| under 20% | 70+ others |

The 99% row is the reason this analysis happened before any code was written.
A five-record sample showed `indications_and_usage` on every record; at 100
records it is 99%. Designing off the small sample would have produced a
`NOT NULL` constraint that fails partway through ingest.

## Results

A full run against the API pagination ceiling:

| | |
| --- | --- |
| Labels ingested | 25,000 |
| Section rows written | 417,135 |
| Distinct section types discovered | 138 |
| Records rejected by validation | 0 |
| Empty sections filtered | ~1,800 |
| Wall clock | 2m 21s |
| CPU utilisation | 9% |

Section frequency across the run, which is the earlier field-frequency
analysis re-run against the database instead of a sample:

```
spl_product_data_elements              24,977
package_label_principal_display_panel   24,929
indications_and_usage                   23,219
dosage_and_administration               23,175
warnings                                18,960
inactive_ingredient                     15,047
active_ingredient                       14,939
purpose                                 14,626
```

`warnings` lands at 75.8% here against 82% in the original sample — close
enough to confirm the shape, far enough apart to justify not making it
required.

**138 section types against 92 in a 200-record sample.** The vocabulary has a
long tail: roughly 46 section types are rare enough to be invisible at small
sample sizes. All 46 were absorbed as new rows in the lookup table with no
schema migration and no code change, which is the whole reason for the schema
below.

**Zero validation rejections across 25,000 records.** The five required fields
are genuinely universal in this data. This is a result rather than an absence
of one: it is evidence that the frequency analysis picked the right five.

## Schema

```
label ──< label_section >── section_type
```

- **`label`** — one row per drug label. Uses the FDA's own `id` as the primary
  key so rows trace back to the source record.
- **`label_section`** — one row per section of a label. Two foreign keys:
  `label_id` and `section_type_id`.
- **`section_type`** — lookup table, one row per distinct section name, with a
  `UNIQUE` constraint so the vocabulary cannot fragment on a typo.

**Why not one wide table.** A column per section means 138 columns where the
median column is NULL over 90% of the time, and every new section type the FDA
introduces requires an `ALTER TABLE` on a table with hundreds of thousands of
rows. Modelling sections as rows means a new section type is an `INSERT`. This
was not hypothetical — 46 unseen types appeared between the sample and the full
run.

**Why PostgreSQL and not a document store.** The input is inconsistent nested
JSON, which a document store would ingest with no schema work at all. But the
input format describes what is easy to load, not what the system is for.
Thwart's output is relational, its queries are analytical (frequency across all
labels, labels missing a section), and `NOT NULL` plus foreign key constraints
act as a second layer of validation behind the Python. A document store would
have meant doing the validation work and then storing the result somewhere that
enforces none of it.

## Design decisions

**Validate, don't clean.** Cleaning is guessing. Turning `"3.0"` into `3`
requires a judgment call, and so does every case after it — is `""` a zero or a
missing value, is a month of `13` a typo for January or December. A rejected
record fails loudly; a mis-cleaned record is silently wrong and looks correct.

**Errors are a list, not a boolean.** `validate()` returns every reason a
record failed, not just the first. That list is what makes a reject log
diagnostic instead of a tally.

**The section type cache.** `label_section` needs an integer
`section_type_id`, but the normalizer produces a name. Resolving that against
the database per section would mean 417,135 round trips for an answer that
never changes, so the whole `section_type` table is loaded into a dict at
startup and consulted in memory. A cache miss means the name is genuinely new,
so it is inserted and cached in the same step: **138 inserts against 417,135
lookups, a 99.97% hit rate.**

**Batched commits.** Commits fire every 100 records rather than per record.
Each commit forces a disk flush, and re-running the pipeline is cheap, so
throughput wins over losing up to 99 in-flight records on a crash.

**Empty sections are dropped in the normalizer, not the writer.** A first run
produced 34 rows out of 3,567 that had valid foreign keys, pointed at real
section types, and contained only whitespace — present, but unusable. They are
now filtered before the writer sees them, so an empty section costs no cache
lookup and never creates a `section_type` row for a name that only ever appears
blank. Sections are dropped individually rather than rejecting the whole label,
since one blank field should not discard an otherwise valid record. The skipped
names are returned and counted, and the distribution turned out to be diffuse
rather than systematic — no single field the FDA provisioned and abandoned,
just individual submissions occasionally shipping a section with no content,
including sections as important as `warnings`.

**Pure core.** `core/` performs no I/O. It takes a dict, computes, and returns
a value. This is what lets the test suite run in 0.01s with no database and no
network, and what will let a web frontend import the same validation logic the
batch pipeline uses rather than reimplementing it.

## Constraint: pagination depth

The dataset is 262,595 records. The API caps `skip` at 25,000:

```
skip=25000  →  200 OK
skip=26000  →  {"code": "BAD_REQUEST", "message": "Skip value must 25000 or less."}
```

Offset pagination costs the database a scan of every skipped row, so deep pages
are the most expensive queries in the sequence. Public APIs cap it for load
protection; openFDA is Elasticsearch-backed, which has this ceiling by default.

Three ways past it, in increasing order of correctness:

1. **Partition the query.** Slice by `effective_time` year so each search
   returns under 25,000 and paginate each from `skip=0`. Requires no API
   support.
2. **Cursor pagination.** openFDA supports `search_after`, which resumes from a
   position rather than counting past rows, making page 250 as cheap as page 1.
3. **Bulk downloads.** The FDA publishes the full dataset as zipped JSON
   specifically because the API is built for real-time queries rather than
   export. This is the correct tool for a full ingest.

Because `core/` is I/O-free, any of these is a change to the fetcher alone —
the validator, normalizer, and writer take a record dict and do not care where
it came from.

## Performance

The 25,000-record run held at 9% CPU. The pipeline is I/O-bound, not
compute-bound, and the measurement makes that concrete: raising `PAGE_SIZE`
from 100 to 1,000 cut request count 10x and took the run from 20,000 records in
4m 18s to 25,000 records in 2m 21s. More records in half the time, with no
change to any processing logic.

Optimising the Python here would accomplish nothing. The remaining time is
network round trips.

## Layout

```
core/           validator.py, normalizer.py     pure logic, no I/O
db/             schema.sql, connection.py, writer.py
pipeline/       fetcher.py, run.py
tests/          pytest, aimed at core/
```

## Setup

```bash
git clone https://github.com/TonyIsCoding93/thwart.git
cd thwart

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

createdb thwart
psql thwart -f db/schema.sql

echo "DATABASE_URL=postgresql://$USER@localhost:5432/thwart" > .env

python -m pipeline.run
```

Requires PostgreSQL running locally. Tests: `pytest`.

## Known gaps

- **`content_type` is hardcoded to `"text"`.** Nearly every section has a
  `_table` twin (`warnings` and `warnings_table`) carrying an HTML
  representation of the same content. The schema has the column to distinguish
  them; the normalizer does not yet populate it.
- **No retry or backoff.** A single network failure or a 429 ends the run. The
  keyless rate limit is 240 requests/minute and 1,000/day per IP.
- **`int(record["version"])` will raise on a non-numeric version.** Not
  observed in 25,000 records, but it belongs in the validator rather than as a
  runtime exception.
- **Rejections and skipped sections are printed, not persisted.** A reject log
  table would make them queryable and let the counts be compared across runs.
- **`effective_time` is passed through as the source string** (`"20210902"`).
  PostgreSQL parses it into the `DATE` column, but the conversion is implicit
  rather than explicit.
