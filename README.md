# Local AI QA Test Case Generation Agent

Reads a requirement specification from **Google Drive** (parameters in `drive_config.yaml`), analyses it, and generates
traceable test cases with a **local Qwen3:4B model via Ollama**. No cloud LLM or paid AI service is used. Google Drive is
used only to download your requirements file.

Streamlit UI | Python backend | Pandas | OpenPyXL | pypdf / python-docx | Ollama `http://localhost:11434/api/chat`

## Architecture

```
app.py                      Streamlit entry point (routing only)
drive_config.yaml           Google Drive + column-mapping parameters  <-- you edit this
src/qagen/
  config.py, logging_setup.py, models.py
  llm/          ollama_client.py (health check, JSON repair, <think> stripping), prompts.py
  ingestion/    drive_loader.py (Drive download), parsers.py (PDF/DOCX/XLSX/CSV/TXT/MD -> requirements)
  services/     requirement_analyzer, generator, test_data, evaluation, exporter
  validation/   validators.py  (all deterministic checks, no LLM)
  ui/           theme.py, state.py, pages.py  (9 pages)
data/           sample_user_stories.md, sample_generated_test_cases.csv
tests/          unit + pipeline tests (mock Ollama), UI smoke test
```

Layers only depend downward: UI -> services -> (llm, ingestion, validation). Validation never calls the LLM.

## Install (Windows 11, 16 GB RAM, no GPU)

1. Install **Python 3.10+** and **Ollama for Windows** (https://ollama.com/download).
2. Pull the model: `ollama pull qwen2.5:3b`
3. In the project folder run `setup.bat` (creates `.venv`, installs packages, copies `.env.example` to `.env`).

Manual equivalent:
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run

```
ollama serve            (skip if the Ollama tray app is already running)
run.bat                 (or:  .venv\Scripts\activate  then  streamlit run app.py)
```
Open http://localhost:8501. The sidebar shows whether Ollama and the model are reachable.

## Reading requirements from Google Drive

Edit `drive_config.yaml` (or use **Requirement Upload > Google Drive > Edit drive_config.yaml** in the app).

| Parameter | Meaning |
|---|---|
| `google_drive.auth_mode` | `service_account`, `oauth` or `public_link` |
| `file_id` / `file_url` / `folder_id` + `file_name` | Identify the file (use one). Full Drive/Docs/Sheets URLs are accepted |
| `export_format_doc` / `export_format_sheet` | How Google Docs / Sheets are downloaded (`docx`/`pdf`/`txt`, `xlsx`/`csv`) |
| `spreadsheet.sheet_name`, `header_row`, `columns` | Map your column titles to Requirement ID, Title, Description, Acceptance Criteria, Priority |
| `text_parsing.id_pattern` | Regex that finds requirement IDs in PDF/DOCX/TXT/MD files |
| `local_fallback_path` | File used by "Load local sample instead" |

**Service account (recommended):** in Google Cloud Console enable the *Drive API*, create a service account, download its JSON key to
`credentials/service_account.json`, then **share the Drive file (or folder) with the service account's e-mail** as Viewer.
**OAuth:** put an OAuth *Desktop* client at `credentials/oauth_client.json`; a browser opens once and the token is cached.
**Public link:** share the file as "Anyone with the link" and set `auth_mode: public_link` (no credentials).

Supported files: Google Docs/Sheets, PDF, DOCX, XLSX, CSV, TXT, MD. Sheets/CSV are read by column mapping (common header
aliases such as "Summary", "Key", "AC" are recognised). Documents are split into requirements by ID headings such as
`REQ-001:`, `US-12:`, `FR-3`.

## Workflow in the app

1. **Requirement Upload**: Drive, file upload or pasted text.
2. **Requirement Analysis**: FR/NFR classification, acceptance-criteria extraction, missing-criteria detection (rules + Qwen3). You can edit criteria.
3. **Test Case Generation**: positive, negative, boundary, edge, security and validation cases per requirement; duplicates removed.
4. **Test Data Generation**: boundary values computed in Python from limits in the text, plus LLM examples.
5. **Review & Approval**: edit cells, set status, approve all clean cases, regenerate one requirement (approved cases are kept).
6. **Coverage & Traceability**, 7. **Evaluation Dashboard**, 8. **Export Centre** (Excel with Test Cases / Requirements / Traceability / Coverage sheets, CSV).

## Deterministic quality controls (`validation/validators.py`)

Mandatory-field completeness; vague/short/missing expected results; requirement-ID existence and traceability field; test-case ID uniqueness
(auto-renumbering); near-duplicate detection (number-aware, so boundary cases 7 vs 21 are not merged; approved cases are never dropped);
requirement and acceptance-criteria coverage.

## Performance settings (`.env`)

`OLLAMA_NUM_CTX=4096`, `OLLAMA_NUM_PREDICT=1500`, `MAX_REQ_CHARS_PER_CALL=1800`, `MAX_TESTS_PER_REQUIREMENT=12`. Requirements are sent **one per call**
so the context stays small. Qwen3 "thinking" is disabled for speed. Expect about 1 to 3 minutes per requirement on CPU; lower
`MAX_TESTS_PER_REQUIREMENT` or `OLLAMA_NUM_PREDICT` to go faster.

## Optional LangSmith tracing

Set these values in `.env` to trace each successful Ollama call:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-langsmith-api-key
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_AGENT_ID=qatestcasegeneratoragent
LANGSMITH_AGENT_ENVIRONMENT=local
```

The trace includes the full system/user prompts, the model output, and Ollama's prompt, completion, and total token counts.
This sends requirement content and generated output to LangSmith; enable it only when that data may be shared with your LangSmith workspace.
Tracing is disabled by default. If enabled without an API key, app startup reports a configuration error. The agent must exist in the LangSmith workspace before traces can be sent.

## Tests

```
python tests/run_tests.py     # 18 tests, no extra packages (pytest -q also works)
python tests/smoke_ui.py      # runs every page function against a stubbed Streamlit
```
Tests use a fake Ollama server (`tests/mock_ollama.py`), so they need neither the model nor internet.

## Sample files

`data/sample_user_stories.md` is a 5-requirement banking spec (REQ-003 deliberately has no acceptance criteria).
`data/sample_generated_test_cases.csv` is an **illustrative, hand-written** example of the output format covering REQ-001 and REQ-002; it is
not real model output, and the other requirements are intentionally uncovered so the coverage page has something to show.

## Troubleshooting

* **Ollama offline / model missing**: the sidebar says which; run `ollama serve` / `ollama pull qwen2.5:3b`.
* **Timeouts**: raise `OLLAMA_TIMEOUT_SEC`, reduce tests per requirement.
* **Invalid JSON from the model**: retried once automatically; failures are listed per requirement and logged in `logs/app.log`.
* **Drive 403/404**: the file is not shared with the service-account e-mail, or the Drive API is not enabled.

## Future phase: MCP

`services/` is UI-independent, so `analyze_requirements`, `TestCaseGenerator` and `validate_all` can be exposed as MCP tools
(`pip install mcp`, then wrap them with `FastMCP`) without touching the UI.
