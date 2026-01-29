# Browser-Use Mimic

A practical, self-hostable UI and API for **browser-use** agents. This project lets you:
- chat with an agent in a Web UI,
- watch/stream the agent’s browser actions,
- export a reproducible **flow script** via CodeAgent, and
- deploy everything in a single Docker container.

It is built on top of the open-source **browser-use** library and the **browser-use/web-ui** layout, with updates for the latest browser-use APIs and a Gemini-first setup.

## What you can do
- **Agent chat + demonstration**: describe a task, watch the agent browse, and get step-by-step reasoning output.
- **Flow-as-code**: generate a Python script that reproduces the same workflow later.
- **API trigger**: call a REST endpoint to run the same flow in the cloud.

## Quickstart (Local)

### 1) Create a Python 3.11 environment
```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 3) Configure environment
```bash
cp .env.example .env
```
Edit `.env` and set at least:
- `GOOGLE_API_KEY` (Gemini)
- `BROWSER_USE_API_KEY` (required to export flow scripts via CodeAgent)

### 4) Run the Web UI
```bash
python webui.py --ip 127.0.0.1 --port 7788
```
Open:
- Web UI: `http://127.0.0.1:7788`

## Docker (Single Container)

```bash
docker compose up --build
```
Open:
- Web UI: `http://localhost:7788`
- VNC Viewer: `http://localhost:6080/vnc.html`
  - Default password: `youvncpassword`

## How to use it (detailed)

### 1) Agent Settings
**Purpose:** Configure the model and agent behavior.
- **LLM Provider / Model**: Choose Gemini (default), OpenAI, Anthropic, etc.
- **Temperature**: Controls creativity vs. determinism.
- **Use Vision**: Adds screenshots to the model context (recommended).
- **Ollama Context Length**: Only used when Ollama is selected.
- **Flow Script Output Dir**: Where CodeAgent exports scripts.

### 2) Browser Settings
**Purpose:** Control the browser runtime used by the agent.
- **Use Own Browser**: Attach to your local Chrome profile to reuse logins.
- **Keep Browser Open**: Persist browser state between tasks.
- **Headless Mode**: Enables a live screenshot stream in the UI.
- **Disable Security**: Useful for some automation but less safe.
- **CDP / WSS**: Connect to a remote or pre‑launched Chrome instance.
- **Recording / Trace / Download paths**: Store media and downloads.

### 3) Run Agent (Chat + Demonstration)
**Purpose:** Execute tasks and watch the agent in action.
- Type a task (e.g., “Find the latest blog post and summarize it”).
- Click **Submit Task** to start.
- The chat shows step-by-step outputs + screenshots.
- Use **Pause/Resume** if you want to intervene.
- Use **Stop** to terminate the run early.

### 4) Flow Script (CodeAgent export)
**Purpose:** Turn a task into a reusable Python script.
- Click **Generate Script**.
- Requires `BROWSER_USE_API_KEY` in `.env`.
- The script is saved to the directory in **Flow Script Output Dir**.
- Useful for deployment: run the script in a cloud container or CI job.

### 5) API mode
**Purpose:** Trigger tasks from other systems (e.g. cron, server, workflow tool).
- `/api/agent/run` runs a task and saves history.
- `/api/flow/export` generates a script from a task.

## API
The UI is mounted at `/`, and API routes are under `/api`.

### Run an agent task
```bash
curl -X POST http://localhost:7788/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task":"Open example.com and summarize the homepage","llm_provider":"google","llm_model":"gemini-3-pro-preview"}'
```

### Export a flow script (CodeAgent)
```bash
curl -X POST http://localhost:7788/api/flow/export \
  -H "Content-Type: application/json" \
  -d '{"task":"Search for the latest docs and open the top result"}'
```

## Notes
- **Flow export requires** `BROWSER_USE_API_KEY` (Browser-Use). Gemini key alone is not enough.
- Headless mode enables live browser screenshots inside the UI.
- If you want persistent sessions, enable **Keep Browser Open** in settings.

## License
See `LICENSE`.
