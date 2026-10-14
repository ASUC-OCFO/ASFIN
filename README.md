# ASFIN

ASFIN contains data processing tools used by the ASUC Office of the Chief Financial Officer (OCFO) to clean, standardize, and reconcile financial and organizational data.

The repository supports two main local workflows:

- A general processor interface through `execute.py`
- A Finance Committee FR/Agenda batch workflow through `run_ficomm.py`

Processing logic is organized under `ASFINT/`, with dataset-specific transformations in `ASFINT/Transform/` and shared workflow logic in `ASFINT/Pipeline/`.

## Setup

From the repository root, create and activate a Python environment, then install the project dependencies:

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

Python 3.12 is recommended for local development.

For API development and the full test suite, install the development dependencies instead:

```bash
pip install -r requirements.dev.txt
pip install -e .
```

`requirements.dev.txt` includes both the core processing dependencies and the API dependencies.

## General Processing

`execute.py` is the generic command-line entry point for processors configured in ASFIN.

A typical command looks like:

```bash
python execute.py   --input files/input   --output files/output   --process fr
```

The arguments are:

- `--input`, `-i`: input file or directory to process
- `--output`, `-o`: directory where processed files should be written
- `--process`, `-p`: processor type, such as `fr`, `absa`, or `agenda`
- `--reporting`, `-r`: optional flag that enables processor reporting output

For example, to process files in `files/input` with the ABSA processor and write results to `files/output`:

```bash
python execute.py   --input files/input   --output files/output   --process absa
```

The generic workflow is implemented in `ASFINT/Pipeline/workflow.py`. It loads the source files, routes them to the selected processor, and writes the resulting output.

## FiComm FR/Agenda Processing

`run_ficomm.py` processes a full academic year of Finance Committee Financial Request (FR) spreadsheets together with the corresponding Agenda/Minutes documents.

The command requires three directories:

```bash
python run_ficomm.py   --agendas /path/to/agenda-directory   --frs /path/to/fr-directory   --output /path/to/output-directory
```

For example, with an academic-year folder structured as:

```text
example-year/
  agendas/
    Fall/
    Spring/
  resolutions/
    Fall/
    Spring/
```

the pipeline can be run with:

```bash
python run_ficomm.py   --agendas example-year/agendas   --frs example-year/resolutions   --output example-year/processed
```

The agenda and FR directories may contain semester subdirectories. The pipeline searches them recursively, identifies the meeting week and date for each source file, and pairs the corresponding FR and Agenda records.

For each meeting week, the pipeline:

- Cleans the FR spreadsheet and parses decisions from the Agenda/Minutes document.
- Reconciles corresponding records while preserving values from both sources, including records that appear in only one source.
- Records review flags for conditions that may require manual review, such as date discrepancies, ambiguous name matches, malformed source text, or missing inputs.
- Copies the source inputs into the processed week directory and writes the cleaned and merged CSV outputs.

A processed year is organized by meeting week and date. For example:

```text
processed/
  F1_YYYY-MM-DD/
    F1_YYYY-MM-DD_FR.xlsx
    F1_YYYY-MM-DD_Agenda.docx
    F1_YYYY-MM-DD_FR_cleaned.csv
    F1_YYYY-MM-DD_Agenda_cleaned.csv
    F1_YYYY-MM-DD_merged.csv
  F2_YYYY-MM-DD/
    ...
  manifest.csv
  review_flags.csv
  review_summary.csv
```

`manifest.csv` summarizes each processed week, including source filenames, row counts, warnings, and errors. `review_flags.csv` contains individual items that may require manual review, while `review_summary.csv` summarizes those flags by type.

The Finance Committee workflow is implemented primarily in:

- `ASFINT/Pipeline/workflow.py`
- `ASFINT/Transform/FR_Processor.py`
- `ASFINT/Transform/Agenda_Processor.py`
- `ASFINT/Transform/Reconciliation_Processor.py`
- `ASFINT/Utility/Matching.py`

## API

The FastAPI application is defined in `app/api/main.py`. The API layer is separate from the local processing commands and uses the processing and storage components under `ASFINT/` and `app/`.

For local API development, install `requirements.dev.txt`. The Docker configuration runs the application with `app.api.main:app`.

## Tests

Run the FiComm pipeline tests with:

```bash
python -m pytest tests/test_ficomm_pipeline.py -q
```

Run the full repository test suite, including the API tests under `app/tests/`, with:

```bash
python -m pytest -q
```

## Repository Structure

```text
ASFINT/
  Config/       Processor configuration
  Pipeline/     Workflow orchestration
  Pull/         Input loading
  Push/         Output writing
  Transform/    Dataset-specific processors
  Utility/      Shared utilities
  Validation/   Validation helpers

app/            API, services, storage, and API tests
tests/          Processing pipeline tests
execute.py      Generic processing CLI
run_ficomm.py   FiComm FR/Agenda batch processing CLI
```
