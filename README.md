# Thwart

Thwart is a Python pipeline that pulls drug label records from the openFDA
API, validates each one against a set of required fields, and writes the
records that pass into a normalized PostgreSQL schema.

It does not try to repair bad data. Records that fail validation get rejected
with a logged reason, and sections that have a field name but no content get
dropped and counted by name. I made that call because a guessed fix on a drug
label is worse than a missing one.

## The problem

The openFDA drug label endpoint serves data derived from the Structured
Product Labeling documents that manufacturers submit to the FDA. The FDA's
documentation says outright that there is "considerable variation between drug
products in terms of these sections and their contents."

That variation is the problem this project is built around. The same endpoint
serves two very different kinds of document, and nothing in the record tells
you which kind you have:

- Over-the-counter labels have sections like `purpose`, `do_not_use`,
  `ask_doctor`, and `keep_out_of_reach_of_children`
- Prescription labels have sections like `adverse_reactions`,
  `contraindications`, `nursing_mothers`, and `clinical_pharmacology`

Before writing any code I pulled 100 records and counted field names. There
were 93 distinct fields. Only five of them appeared in every record, and none
of the five describe the drug itself:

| Coverage | Fields |
| --- | --- |
| 100% | `id`, `set_id`, `version`, `effective_time`, `openfda` |
| 99% | `indications_and_usage`, `dosage_and_administration` |
| 82% | `warnings` |
| under 20% | 70+ others |

The 99% row is the reason I did this first. In a five-record sample,
`indications_and_usage` was on every record, so it looked safe to require. At
100 records it dropped to 99%. If I had designed the schema off the small
sample, the `NOT NULL` constraint on that column would have started failing
partway through a real ingest.

## Results

Numbers from a full run up to the API's pagination limit:

| | |
| --- | --- |
| Labels ingested | 25,000 |
| Section rows written | 417,135 |
| Distinct section types found | 138 |
| Records rejected by validation | 0 |
| Empty sections filtered out | about 1,800 |
| Wall clock | 2m 21s |
| CPU utilization | 9% |

Section counts across the run. This is the same field-frequency check as
above, but run as a query against the database instead of a script against a
sample:

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

`warnings` comes out at 75.8% here, against 82% in the original sample. The
shape held up, but the gap is big enough that I would not have wanted it as a
required field.

The number I was most interested in was 138 section types. A 200-record sample
had turned up 92. So there are roughly 46 section types rare enough that you
will not see them at small sample sizes. All 46 went into the lookup table as
new rows during the run. No migration, no code change. That was the point of
the schema design, and this is the first evidence that it held.

Zero records were rejected by validation across all 25,000. I take that as
confirmation that the five required fields really are universal, which is what
the frequency analysis predicted.

## Schema

```
label --< label_section >-- section_type
```

- `label` has one row per drug label. The primary key is the FDA's own `id`,
  so every row can be traced back to its source record.
- `label_section` has one row per section of a label, with foreign keys to
  both `label` and `section_type`.
- `section_type` is a lookup table with one row per distinct section name. The
  name column is `UNIQUE`, so a typo cannot quietly create a second version of
  an existing type.

### Why not one wide table

A column per section type would mean 138 columns, and for most rows the
majority of them would be NULL. Worse, every time the FDA introduces a new
section type, adding it means an `ALTER TABLE` on a table with hundreds of
thousands of rows. With sections stored as rows, a new section type is just an
`INSERT`. During this run, 46 section types that were not in the original
sample showed up and were handled without any change to the schema.

### Why PostgreSQL instead of a document store

The input is inconsistent nested JSON, and a document store would take it
as-is with no schema work. I went with Postgres anyway because the input format
only tells you what is easy to load, not what the system needs to do with the
data afterward. The output here is relational, the queries I care about are
aggregate (section frequency across all labels, labels that are missing a
particular section), and the `NOT NULL` and foreign key constraints give me a
second layer of validation that runs in the database regardless of what the
Python does. Storing the result in a document store would have meant doing all
the validation work and then putting the output somewhere that enforces none
of it.

## Design decisions

**Validate, do not clean.** Fixing a bad value means guessing what it should
have been. Converting `"3.0"` to `3` is a judgment call, and so is deciding
whether `""` means zero or missing, or whether a month value of `13` was meant
to be January or December. A rejected record is loud and easy to find. A wrongly
cleaned one looks fine and is not.

**Validation returns a list, not a boolean.** `validate()` returns every
reason a record failed rather than stopping at the first one. That is what
makes the reject counts useful for diagnosis instead of just a total.

**Section type cache.** `label_section` needs an integer `section_type_id`,
but the normalizer produces a section name. Looking that up in the database
for every section would be 417,135 round trips for a mapping that never
changes. Instead the pipeline loads the whole `section_type` table into a dict
at startup. A cache miss means the name is new, so it gets inserted and added
to the dict in the same step. Over the full run that came to 138 inserts
against 417,135 lookups, a 99.97% hit rate.

**Batched commits.** The pipeline commits every 100 records instead of after
each one. Every commit forces a disk flush, and the pipeline is cheap to
re-run, so I traded the risk of losing up to 99 in-flight records on a crash
for the throughput.

**Empty sections are filtered in the normalizer, not the writer.** An early
200-record run produced 34 section rows out of 3,567 that had valid foreign
keys and pointed at real section types but contained nothing except
whitespace. The field was present, the content was not. The normalizer now
drops those before the writer sees them, so an empty section never costs a
cache lookup and never creates a `section_type` row for a name that only ever
shows up blank. I drop the individual section rather than rejecting the whole
label, since one blank field should not throw away an otherwise valid record.
The dropped names are returned and counted. The distribution turned out to be
spread across many section types rather than concentrated in one, which
suggests individual submissions occasionally shipping an empty section, not a
field the FDA defined and never used. `warnings` was in that list.

**Pure core.** Nothing in `core/` does I/O. Both functions take a dict and
return a value. That is what lets the test suite run in 0.01s with no database
and no network, and it is what will let a web frontend call the same
validation code the batch pipeline uses instead of reimplementing it.

## Constraint: pagination depth

The dataset is 262,595 records. The API only lets `skip` go up to 25,000:

```
skip=25000  ->  200 OK
skip=26000  ->  {"code": "BAD_REQUEST", "message": "Skip value must 25000 or less."}
```

Offset pagination makes the database scan past every skipped row to reach the
page you asked for, so deep pages get progressively more expensive. Public APIs
cap the depth to protect themselves. openFDA runs on Elasticsearch, which has
this limit by default.

There are three ways around it:

1. Partition the query. Search by `effective_time` year so that each result
   set stays under 25,000, then paginate each one from `skip=0`. This needs
   nothing from the API.
2. Cursor pagination. openFDA supports `search_after`, which resumes from a
   known position instead of counting past rows, so page 250 costs the same as
   page 1.
3. Bulk download. The FDA publishes the full dataset as zipped JSON files
   because the API is meant for live queries rather than exports. For a full
   ingest this is the right tool.

Because `core/` does no I/O, any of the three is a change to the fetcher only.
The validator, normalizer, and writer take a record dict and do not care where
it came from.

## Performance

CPU stayed at 9% for the whole 25,000-record run. The pipeline spends nearly
all its time waiting on the network, and I have one measurement that makes
that concrete. Raising `PAGE_SIZE` from 100 to 1,000 cut the request count by
10x and took the run from 20,000 records in 4m 18s to 25,000 records in
2m 21s. More records in about half the time, with no change to any of the
processing code.

There is nothing to gain from optimizing the Python. The remaining time is
round trips.

## Layout

```
core/           validator.py, normalizer.py     pure functions, no I/O
db/             schema.sql, connection.py, writer.py
pipeline/       fetcher.py, run.py
tests/          pytest, covering core/
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

You need PostgreSQL running locally. Run the tests with `pytest`.

## Known gaps

- `content_type` is hardcoded to `"text"`. Most sections have a `_table` twin
  (`warnings` and `warnings_table`) that carries an HTML version of the same
  content. The schema has a column for this but the normalizer does not fill
  it in yet.
- No retry or backoff. One network failure or a 429 ends the run. Without an
  API key the limit is 240 requests per minute and 1,000 per day per IP.
- `int(record["version"])` raises on a non-numeric version. I never saw one in
  25,000 records, but that check belongs in the validator rather than as a
  runtime exception.
- Rejections and skipped sections are printed, not stored. A reject log table
  would make them queryable and let counts be compared between runs.
- `effective_time` is passed through as the source string (`"20210902"`).
  Postgres parses it into the `DATE` column on insert, but I would rather the
  conversion be explicit.
