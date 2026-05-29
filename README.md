# document_generator — Backend API

## What This Is
A production-grade FastAPI service that generates boardroom-grade `.docx` reports (9-15 pages) using Mistral AI. It exposes a single HTTP endpoint that accepts a prompt and JSON payload fused together in one text field.

---

## Architecture & Flow

This backend operates strictly via API calls. It does **not** read `prompt.md` or `data.json` from the disk.

1. **You send a POST request** containing `combined_input` (a single string with your prompt text and a fenced ```json ... ``` block).
2. **The Smart Extractor** parses the text, separating the instructions from the JSON data.
3. **The Pipeline** summarizes the JSON, sends it to the Mistral LLM with a strictly enforced length directive (3000-5000 words).
4. **Document Generation** assembles the response into a professionally formatted `.docx` file.
5. **The API returns** the `.docx` file as a binary download.

---

## VM Setup (One-Time)

```bash
# 1. SSH into the VM
ssh azureuser@your-vm-ip

# 2. Clone the repository
git clone https://github.com/culturalLife/document_generator.git
cd document_generator

# 3. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set up the API key (.env file)
# The .env file must be created on the VM. It should never be committed to git.
cp .env.example .env
nano .env

# Inside .env, put:
MISTRAL_API_KEY=your_actual_key_here
MISTRAL_READ_TIMEOUT=400
```

---

## Starting the Server

```bash
# Development (auto-reload on file change)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# Production (no reload, background process)
# Recommended to run via systemd or tmux/screen
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## API Usage

### Check if the server is alive
```bash
curl http://your-vm-ip:8000/health
```
Expected response:
```json
{
  "status": "ok",
  "version": "3.0.0",
  "model": "mistral-large-latest",
  "parallel_calls": 1
}
```

### Trigger report generation
You must send a `multipart/form-data` request with a single field named `combined_input`.

#### Using Python
```python
import requests

URL = "http://your-vm-ip:8000/api/generate-docs"

combined_text = """
Write a highly detailed, 10-page consulting report analyzing the following data.
Include an executive summary, risk analysis, and strategic recommendations.

```json
{
  "client": "Acme Corp",
  "project_status": "Red",
  "metrics": {"velocity": 12, "burn_rate": 50000}
}
```
"""

response = requests.post(URL, data={"combined_input": combined_text})

if response.status_code == 200:
    with open("report.docx", "wb") as f:
        f.write(response.content)
    print("Success!")
else:
    print(response.text)
```

#### Using cURL
```bash
curl -X POST http://your-vm-ip:8000/api/generate-docs \
  -F 'combined_input=Generate a detailed report.

```json
{"sales": 1000}
```' \
  --output report.docx
```

---

## Configuration (config.py)

| Variable | Default | What It Controls |
|---|---|---|
| `GENERATION_MODEL` | `mistral-large-latest` | Mistral model used |
| `TEMPERATURE` | `0.2` | LLM determinism (0=strict, 1=creative) |
| `MAX_PARALLEL_CALLS` | `1` | Parallel threads |
| `REPORTS_OUTPUT_DIR` | `reports/` | Where .docx files are saved temporarily |
| `MAX_RETRIES` | `3` | Retry attempts per Mistral call |
| `RETRY_BACKOFF_SECONDS` | `2.0` | Base backoff (exponential) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `SYSTEM_PROMPT_TEMPLATE`| *(Detailed text)* | The hardcoded length and style enforcements |

### `.env` overrides (VM only)

| Variable | Default | What It Controls |
|---|---|---|
| `MISTRAL_API_KEY` | *(none)* | Your Mistral API key (Required) |
| `MISTRAL_READ_TIMEOUT` | `400` | Wait time (seconds) for Mistral response |

---

## Logs

Logs are written to `logs/pipeline.log` with rotation (5MB × 3 backups).
Every request gets a short UUID (e.g. `[A3F2C1B8]`) in the logs, so you can trace what happened:

```bash
grep "A3F2C1B8" logs/pipeline.log
```
