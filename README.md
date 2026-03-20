# Multi-Agent Analytics Automation

An end-to-end multi-agent framework for automated financial analytics — built with AutoGen, connected to Google BigQuery, and served through a real-time group chat UI.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![AutoGen](https://img.shields.io/badge/AutoGen-agentchat-orange) ![BigQuery](https://img.shields.io/badge/Google-BigQuery-4285F4) ![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)


Demo

<img width="1000" height="733" alt="image" src="https://github.com/user-attachments/assets/3cc5dc15-c6a3-422d-a191-264887e564ad" />

<img width="1001" height="830" alt="image" src="https://github.com/user-attachments/assets/843639a2-9b41-423c-81b6-f4e87ec41993" />

Agents taking in user feedback and master agent assign tasks to analyst agent:
<img width="1224" height="862" alt="image" src="https://github.com/user-attachments/assets/1477d01e-2a84-48ab-8c8e-602bc238b76f" />

<img width="1383" height="838" alt="image" src="https://github.com/user-attachments/assets/f30f7daf-a7f3-4db9-94c2-e3886798ef85" />

Link to Data in BigQuery
<img width="1543" height="898" alt="image" src="https://github.com/user-attachments/assets/156f3717-12fb-4b73-9bbb-c163c6195088" />

---

## What It Does

Given a reference date, the system automatically:

1. **Pulls live transaction data** from Google BigQuery
2. **Runs a 5-step analytical pipeline** across 4 specialist AI agents
3. **Generates 12-month trend charts** (YoY line + CTG stacked bar) rendered inline in the chat UI
4. **Searches the web** for external context explaining the key driver
5. **Writes an executive narrative** combining quantitative findings with external context
6. **Generates a PowerPoint slide** with chart, table, and key insights
7. **Streams everything in real time** to a dark-themed group chat UI

---

## Agent Team

| Agent | Role | Tools |
|-------|------|-------|
| 🎯 **Master** | Orchestrates the pipeline, writes narratives, directs other agents | None (coordinates only) |
| 📈 **Analyst** | Runs all quantitative analysis across 5 structured steps | BigQuery → pandas tools |
| 🔍 **WebSearch** | Finds external factors explaining spend trends | Serper.dev search API |
| 🎨 **Visualization** | Generates the final PowerPoint slide | pptxgenjs (Node.js) |

---

## Analytical Pipeline

```
Reference Date Input
        │
        ▼
Phase 1 — Steps 1-3 (Analyst)
  Step 1: Schema & data quality check
  Step 2: Overall MoM + YoY portfolio summary
  Step 3: CTG decomposition by Card Type & Exp Type and Charts
        │
        ▼
  ✋ Checkpoint 1 — User reviews analysis
        │
        ▼
Phase 2 — Step 4 (Analyst)
  Step 4: Filter to top Card Type driver, Top sub-driver identification
        │
        ▼
Round 2 — Master identifies search queries
        │
        ▼
Round 3 — WebSearch runs queries, returns external context
        │
        ▼
Round 4 — Master writes narrative + slide JSON spec
        │
        ▼
  ✋ Checkpoint 2 — User reviews narrative (can request deeper analysis)
        │
        ▼
Round 5 — Visualization generates PowerPoint slide
```

---

## Tech Stack

- **Agents**: [AutoGen AgentChat](https://github.com/microsoft/autogen) with GPT-4o
- **Data**: Google BigQuery (with local CSV fallback)
- **Analytics**: pandas
- **Web Search**: Serper.dev API
- **Slide Generation**: pptxgenjs (Node.js)
- **Server**: Flask with Server-Sent Events (SSE) for real-time streaming
- **UI**: Vanilla HTML/CSS/JS + Chart.js — dark group chat interface

---

## Project Structure

```
Multi-Agent-Analytics-Automation/
├── multi_agent_code/
│   ├── server.py              # Flask server — SSE broadcast, checkpoint routing
│   ├── pipeline.py            # Pipeline orchestration — 5 rounds, 2 checkpoints
│   ├── agents_multi.py        # Agent definitions (Master, Analyst, WebSearch, Viz)
│   ├── prompts_multi.py       # System prompts for all 4 agents
│   ├── tools.py               # All tools: BigQuery loader, analytics, search, slide gen
│   ├── generate_slide.js      # Node.js PowerPoint builder (pptxgenjs)
│   ├── main_multi.py          # Terminal mode entry point
│   └── ui/
│       └── index.html         # Group chat UI with inline Chart.js charts
├── data/                      # Local CSV fallback (not committed)
├── output/                    # Generated .pptx files (not committed)
├── .env                       # API keys and config (never commit)
└── requirements.txt
```

---

## Setup

### Prerequisites
- Python 3.11+
- Node.js (for slide generation)
- Google Cloud account (free tier works)
- OpenAI API key
- Serper.dev API key (free tier: 2,500 searches/month)

### 1. Clone and create virtual environment

```bash
git clone https://github.com/BFvandy/Multi-Agent-Analytics-Automation.git
cd Multi-Agent-Analytics-Automation
python -m venv venv
source venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Node dependencies

```bash
cd multi_agent_code
npm install pptxgenjs
```

### 4. Set up Google BigQuery

```bash
# Install gcloud CLI (macOS)
brew install --cask google-cloud-sdk

# Authenticate
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID

# Install BigQuery Python client
pip install google-cloud-bigquery db-dtypes pyarrow
```

Upload your transaction CSV to BigQuery. Expected schema:

| Column | Type |
|--------|------|
| Date | DATE |
| City | STRING |
| Card Type | STRING |
| Exp Type | STRING |
| Gender | STRING |
| Amount | FLOAT |

### 5. Configure `.env`

```env
OPENAI_API_KEY=sk-...
SERPER_API_KEY=...
BQ_PROJECT=your-gcp-project-id
BQ_TABLE=your-project.your_dataset.your_table

# Optional — set USE_CSV=true to use local CSV instead of BigQuery
# DATA_FILE=India_cc_transactions.csv
# USE_CSV=false
```

### 6. Run

```bash
# Web UI (recommended)
python server.py
# → open http://localhost:8080

# Terminal mode
python main_multi.py
```

---

## Usage

1. Open `http://localhost:8080`
2. Enter a reference date (`YYYY-MM-01`) — e.g. `2025-03-01` analyses February 2025
3. Watch the agents work in real time in the group chat
4. Review analysis at **Checkpoint 1** — press Continue or type feedback
5. Review narrative at **Checkpoint 2** — press Continue or request a deeper drill-down
6. Download the generated `.pptx` slide at the end

---

## Configuration

| `.env` variable | Default | Description |
|----------------|---------|-------------|
| `BQ_PROJECT` | — | GCP project ID |
| `BQ_TABLE` | — | Full BigQuery table path |
| `USE_CSV` | `false` | Set to `true` to use local CSV instead |
| `DATA_FILE` | `India_cc_transactions.csv` | CSV filename (relative to `data/`) |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `SERPER_API_KEY` | — | Serper.dev API key for web search |
| `PORT` | `8080` | Flask server port |

> **Note for macOS users**: Port 5000 is used by AirPlay Receiver. Use port 8080 (default) or disable AirPlay in System Settings → AirDrop & Handoff.

---

## Key Design Decisions

- **Pipeline calls `get_trend_charts` directly** — not via the agent. LLMs silently normalize percentage values to decimals when serializing JSON, corrupting chart data. The pipeline calls the tool in Python and emits chart events directly to the UI, bypassing the LLM entirely.
- **Two-phase analyst** — Steps 1-3 and Step 4 are separate `run_until_complete` calls. This ensures Step 4 (key driver drill-down) always runs regardless of how long Step 3 takes.
- **SSE broadcast queue** — each browser connection gets its own queue. `_push()` writes to all queues simultaneously, so reconnects and multiple tabs both receive the full event stream.
- **BigQuery with thread-safe loading** — a threading lock prevents duplicate queries when multiple pipeline threads call `load_data()` concurrently on startup.
