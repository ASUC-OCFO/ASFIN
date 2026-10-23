# ASFIN

ASFIN is the ASUC Office of the Chief Financial Officer (OCFO) data-processing platform. It combines the existing `ASFINT` transformation code with a local FastAPI/PostgreSQL service for durable source storage, processing metadata, and Finance Committee (FiComm) workflow orchestration.

The canonical datasets are:

- `FICOMM` — Finance Committee Financial Request (FR) and Agenda/Minutes processing
- `ABSA` — ABSA processing

Legacy processor entry points remain in the repository for compatibility, but new FiComm work should use the ingestion and processing-run workflow described below.

## Architecture

The local service uses PostgreSQL for metadata and a persistent data volume for source files and processed artifacts.

```text
Upload
  -> immutable raw file
  -> ingestion metadata
  -> FiComm preflight / period check
  -> weekly ProcessingRun
  -> RunArtifact records + processed CSVs
  -> queryable PostgreSQL rows

Bulk FiComm run
  -> parent ProcessingRun
  -> weekly child ProcessingRuns
  -> weekly queryable rows
  -> parent manifest / review outputs
```

Important storage paths are:

```text
/data/raw/{dataset_id}/{ingestion_id}/original.{ext}
/data/processed/{dataset_id}/{run_id}/...
```

PostgreSQL records datasets, collection periods, ingestions, processing runs, run inputs, artifacts, queryable FiComm rows, review flags, validation results, and legacy publish metadata. Processed CSV artifacts remain the reproducible file-level outputs, while selected FiComm artifacts are also loaded into typed PostgreSQL tables for querying.

## Development Setup

Create a Python environment for local tests and processor development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
pip install -e .
```

Create the local Docker environment file from the tracked template and replace the example password:

```bash
cp .env.example .env
```

Start PostgreSQL and the API:

```bash
docker compose up -d --build
```

Apply database migrations and create the canonical dataset rows:

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api python -m app.admin.datasets bootstrap
```

The API binds to `127.0.0.1:8000`; PostgreSQL binds to `127.0.0.1:5432`. The database and data files are stored in the `asfint_postgres` and `asfint_data` Docker volumes.

To stop the services without deleting stored data:

```bash
docker compose stop
```

Do not use `docker compose down -v` unless the Docker volumes and all development data are intentionally being deleted.

## Collection Periods

FiComm uploads are accepted only when their inferred meeting date belongs to an admin-managed collection period that is open for uploads. Periods are intended to represent semester-level ranges such as Fall or Spring.

List periods:

```bash
docker compose exec -T api python -m app.admin.periods list
```

Create an open period:

```bash
docker compose exec -T api python -m app.admin.periods create \
  --dataset-id 1 \
  --label "Fall 2026" \
  --start 2026-08-01 \
  --end 2026-12-31 \
  --open
```

Open or close an existing period:

```bash
docker compose exec -T api python -m app.admin.periods open 1
docker compose exec -T api python -m app.admin.periods close 1
```

Period administration intentionally has no HTTP write API. These commands should be run by an administrator in the same application environment used for storage.

## FiComm Ingestion and Weekly Processing

FiComm source files are uploaded through:

```text
POST /api/v1/datasets/{dataset_id}/ingestions
```

The upload preflight classifies supported sources as `FR` or `AGENDA`, extracts the meeting week/date, verifies that the date belongs to an open collection period, and rejects duplicates before creating durable raw storage.

When both source roles for a meeting week are available, ASFIN creates a weekly processing run. A completed weekly run stores these artifacts:

- `fr_cleaned.csv`
- `agenda_cleaned.csv`
- `merged.csv`
- `contingency.csv`
- `review_flags.csv`

`contingency.csv` is derived from the merged output by retaining rows whose normalized request type is `Contingency`.

Successful weekly FiComm runs automatically publish their merged records and review flags into PostgreSQL after the file artifacts are written. Processing and publication are tracked separately: a run can remain successfully processed even if publication fails and needs to be retried.

## Queryable FiComm Data

The queryable layer loads the canonical `merged.csv` output into `ficomm_records` and the weekly `review_flags.csv` output into `ficomm_review_flags`. Each published source artifact is recorded in `queryable_artifacts`, including its processing run, source hash, row count, and publication metadata.

The database keeps FR and Agenda values in separate columns rather than selecting one source as authoritative. Contingency records are identified with `is_contingency`; the separate `contingency.csv` file remains available as a processing artifact but is not duplicated into another query table.

Read-only FiComm endpoints are available at:

```text
GET /api/v1/ficomm/records
GET /api/v1/ficomm/records/{record_id}
GET /api/v1/ficomm/review-flags
```

Record queries support filters for collection period, meeting week/date, contingency status, organization, request type, committee status, match type, and source-specific amount ranges. Review-flag queries support collection period, meeting week/date, severity, code, and source filters. Both list endpoints are paginated.

For example:

```bash
curl -s "http://127.0.0.1:8000/api/v1/ficomm/records?contingency=true&organization=Example"
```

By default, queries return the newest published processing run for each collection-period/week combination. Add `include_history=true` to include prior published versions. A historical run published later does not replace a newer processing run as the current result.

A completed weekly run can also be published or retried manually:

```bash
docker compose exec -T api python -m app.admin.ficomm publish-run 5
```

## Bulk FiComm Processing

Historical or semester-level processing reuses the weekly workflow and records a parent bulk run with weekly child runs.

Process one collection period:

```bash
docker compose exec -T api python -m app.admin.ficomm process-period 1
```

Process multiple periods in one bulk run:

```bash
docker compose exec -T api python -m app.admin.ficomm process-periods 1 2 --label "2026-27"
```

List processing runs:

```bash
docker compose exec -T api python -m app.admin.ficomm list-runs
```

Publish completed weekly runs in one collection period that are not already published:

```bash
docker compose exec -T api python -m app.admin.ficomm publish-period 1
```

The backfill continues past individual publication failures and reports attempted, published, skipped, and failed counts. Already-published runs are skipped.

The parent bulk run stores:

- `manifest.csv`
- `review_flags.csv`
- `review_summary.csv`

A bulk run can process weeks with only an FR or only an Agenda and records those cases in the manifest/review outputs. Ambiguous duplicate source roles for the same period/week are rejected instead of being selected implicitly.

File-processing admin commands should run in the same runtime as the stored raw files. With the Docker development setup, run them through `docker compose exec ... api` as shown above.

## Standalone Processing Commands

The original local processor interfaces remain available for compatibility and processor development.

Run a configured processor with `execute.py`:

```bash
python execute.py --input files/input --output files/output --process absa
```

Run the directory-based FiComm year workflow with `run_ficomm.py`:

```bash
python run_ficomm.py \
  --agendas /path/to/agenda-directory \
  --frs /path/to/fr-directory \
  --output /path/to/output-directory
```

The year workflow recursively discovers FiComm sources, pairs them by meeting week, and writes weekly outputs plus a year-level manifest and review files. The service-backed ingestion/run workflow should be preferred when durable source and run tracking are required.

## Database Migrations

Alembic is the source of truth for the service database schema. The API does not create tables automatically on startup.

Apply migrations:

```bash
docker compose exec -T api alembic upgrade head
```

Check model/migration drift during development:

```bash
docker compose exec -T api alembic check
```

## Tests

Run the full repository test suite with:

```bash
pytest -q
```

Run only the standalone FiComm pipeline tests with:

```bash
pytest tests/test_ficomm_pipeline.py -q
```

## Current Scope

ASFIN currently supports local persistent storage, Alembic-managed metadata, FiComm upload preflight, weekly and bulk processing, automatic publication of completed weekly FiComm results, historical publication backfills, and read-only querying of published FiComm records and review flags.

Authentication/authorization, production deployment and backups, ABSA ingestion/query integration, and removal of legacy compatibility paths remain separate follow-up work. The current Docker setup binds services to localhost and should not be exposed directly to an untrusted network.

## Repository Structure

```text
ASFINT/
  Config/       Legacy processor configuration
  Pipeline/     Processing workflow orchestration
  Pull/         Input loading
  Push/         Output writing
  Transform/    Dataset-specific processors
  Utility/      Shared utilities
  Validation/   Validation helpers

app/
  admin/        Backend administration commands
  api/          FastAPI application and routes
  core/         Database, models, schemas, and job runner
  services/     Ingestion, storage, processing, publication, and query services
  tests/        Service/API tests

alembic/        Database migrations
tests/          Standalone processing tests
execute.py      Generic processor CLI
run_ficomm.py   Standalone FiComm batch CLI
```
