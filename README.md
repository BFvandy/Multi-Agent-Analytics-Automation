

# Multi-Agent Analytics Automation

An end-to-end multi-agent framework for automated business analytics — built with AutoGen, connected to Google BigQuery, and served through a real-time group chat UI. Supports any monthly dataset through a simple configuration layer.

Demo

<img width="1000" height="733" alt="image" src="https://github.com/user-attachments/assets/3cc5dc15-c6a3-422d-a191-264887e564ad" />

<img width="1001" height="830" alt="image" src="https://github.com/user-attachments/assets/843639a2-9b41-423c-81b6-f4e87ec41993" />

Agents taking in user feedback and master agent assign tasks to analyst agent:
<img width="1224" height="862" alt="image" src="https://github.com/user-attachments/assets/1477d01e-2a84-48ab-8c8e-602bc238b76f" />

<img width="1383" height="838" alt="image" src="https://github.com/user-attachments/assets/f30f7daf-a7f3-4db9-94c2-e3886798ef85" />

Directly Query Data from BigQuery
<img width="1458" height="929" alt="image" src="https://github.com/user-attachments/assets/343e8d8d-7358-4d23-9eaf-6a8c5d83c666" />


---

## What It Does

Given a reference date and a dataset, the system automatically:

1. **Pulls live data** from Google BigQuery (any monthly dataset)
2. **Runs a structured analytical pipeline** across 4 specialist AI agents
3. **Generates 12-month trend charts** (YoY line + CTG stacked bar) rendered inline in the chat UI
4. **Searches the web** for external context explaining the key driver
5. **Writes an executive narrative** combining quantitative findings with external context
6. **Generates a PowerPoint slide** with chart, table, and key insights
7. **Streams everything in real time** to a dark-themed group chat UI
8. **Accepts user feedback at checkpoints** — ask questions, request drill-downs, edit the narrative — Master routes to the right agent automatically and loops back until you approve

---

## Agent Team

| Agent | Role | Tools |
|-------|------|-------|
| 🎯 **Master** | Orchestrates pipeline, synthesizes findings, routes user feedback | None (coordinates only) |
| 📈 **Analyst** | Runs all quantitative analysis — decomposition, drill-downs, trend data | BigQuery → pandas tools |
| 🔍 **WebSearch** | Finds external factors explaining trends | Serper.dev search API |
| 🎨 **Visualization** | Generates the final PowerPoint slide | pptxgenjs (Node.js) |

---

## Analytical Pipeline

```
Reference Date + Dataset Input
        │
        ▼
Phase 1 — Steps 1-3 (Analyst)
  Step 1: Schema & data quality check
  Step 2: Overall MoM + YoY metric summary
  Step 3: CTG decomposition by all configured dimensions
          + 12-month YoY line charts (one per dimension)
          + 12-month CTG stacked bar charts (one per dimension)
        │
        ▼
  ✋ Checkpoint 1 — Interactive feedback loop
     User can: ask questions | request drill-downs | continue
     Master routes to Analyst or WebSearch as needed
     Loops until user approves
        │
        ▼
Phase 2 — Step 4 (Analyst)
  Filter to top primary dimension driver
  → Secondary dimension decomposition within that segment
  → Top sub-driver identification + analytical observation
        │
        ▼
Round 2 — Master identifies search queries (using actual dimension names)
        │
        ▼
Round 3 — WebSearch runs queries, returns external context
        │
        ▼
Round 4 — Master writes narrative + slide JSON spec
        │
        ▼
  ✋ Checkpoint 2 — Interactive feedback loop
     User can: edit narrative | request more analysis | search for more context | continue
     Master routes to Analyst or WebSearch as needed, re-writes spec
     Loops until user approves
        │
        ▼
Round 5 — Visualization generates PowerPoint slide + download link
```

### Key Metrics
- **YoY %** = `(segment_current / segment_prior_year) − 1`
- **CTG %** = `(segment_current − segment_prior_year) / total_prior_year_value`
  - All CTGs for a dimension sum to total portfolio YoY ✓
- **Trend charts** = last 12 completed months, month-over-same-month prior year

---

## Dataset-Agnostic Design

The system works with **any monthly dataset** via a `DatasetConfig` — no code changes needed to switch datasets.

### Built-in presets

**`credit_card`** (default)
```python
DatasetConfig(
    date_col="Date", value_col="Amount", value_label="Spend",
    dimensions=["Card Type", "Exp Type"],
    primary_dim="Card Type", secondary_dim="Exp Type",
)
```

**`global_ads`**
```python
DatasetConfig(
    date_col="month", value_col="total_revenue", value_label="Revenue",
    dimensions=["platform", "campaign_type", "industry", "country"],
    primary_dim="platform", secondary_dim="campaign_type",
)
```

### Switching datasets

Just change two lines in `.env`:

```env
DATASET_PRESET=global_ads
BQ_TABLE=your-project.your_dataset.Global_Ads_monthly
```

### Adding a new dataset

Add one entry to `DATASET_PRESETS` in `tools.py`:

```python
"my_dataset": DatasetConfig(
    date_col="transaction_date",
    value_col="revenue",
    value_label="Revenue",
    dimensions=["region", "product_category", "channel"],
    primary_dim="region",
    secondary_dim="product_category",
),
```

---

## Tech Stack

- **Agents**: [AutoGen AgentChat](https://github.com/microsoft/autogen) with GPT-4o
- **Data**: Google BigQuery (with local CSV fallback)
- **Analytics**: pandas
- **Web Search**: Serper.dev API
- **Slide Generation**: pptxgenjs (Node.js)
- **Server**: Flask with Server-Sent Events (SSE) broadcast queue
- **UI**: Vanilla HTML/CSS/JS + Chart.js — dark group chat interface

---

## Project Structure

```
Multi-Agent-Analytics-Automation/
├── multi_agent_code/
│   ├── server.py              # Flask server — SSE broadcast, checkpoint routing
│   ├── pipeline.py            # Pipeline orchestration — phases, checkpoints, feedback loops
│   ├── agents_multi.py        # Agent definitions (Master, Analyst, WebSearch, Viz)
│   ├── prompts_multi.py       # Dataset-agnostic system prompts for all 4 agents
│   ├── tools.py               # DatasetConfig, BigQuery loader, analytics tools, search, slide gen
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
- Node.js 18+ (for slide generation)
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
pip install google-cloud-bigquery db-dtypes pyarrow
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
```

Upload your CSV to BigQuery. The table needs a date/month column, a numeric value column, and one or more categorical dimension columns.

### 5. Configure `.env`

```env
OPENAI_API_KEY=sk-...
SERPER_API_KEY=...
BQ_PROJECT=your-gcp-project-id
BQ_TABLE=your-project.your_dataset.your_table
DATASET_PRESET=credit_card        # or global_ads, or any custom preset name

# Optional — use local CSV instead of BigQuery
# USE_CSV=true
# DATA_FILE=India_cc_transactions.csv

# Optional — change server port (default 8080)
# PORT=8080
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
3. Watch the 4 agents work in real time in the group chat
4. At **Checkpoint 1** — review the analysis. You can:
   - Ask a question: *"what was January revenue?"*
   - Request a drill-down: *"drill into Google Ads by country"*
   - Leave blank or type `ok` to continue
5. At **Checkpoint 2** — review the narrative and slide spec. You can:
   - Request an edit: *"change the headline to focus on the decline"*
   - Request more research: *"search for TikTok ad spend trends Q4 2025"*
   - Leave blank or type `ok` to generate the slide
6. Download the generated `.pptx` at the end

Both checkpoints loop — Master handles your request, routes to the right agent, and shows the checkpoint again until you approve.

---

## Configuration Reference

| `.env` variable | Default | Description |
|----------------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key |
| `SERPER_API_KEY` | — | Serper.dev API key for web search |
| `BQ_PROJECT` | — | GCP project ID |
| `BQ_TABLE` | — | Full BigQuery table path (`project.dataset.table`) |
| `DATASET_PRESET` | `credit_card` | Which `DatasetConfig` preset to use |
| `USE_CSV` | `false` | Set to `true` to bypass BigQuery and use local CSV |
| `DATA_FILE` | `India_cc_transactions.csv` | CSV filename under `data/` |
| `PORT` | `8080` | Flask server port |

> **macOS note**: Port 5000 is used by AirPlay Receiver. Default port is 8080. To use 5000, disable AirPlay in System Settings → AirDrop & Handoff.

---

## Key Design Decisions

**Charts bypass the LLM entirely.** `get_trend_charts` is called directly from `pipeline.py` in Python, and chart events are emitted straight to the UI. LLMs silently normalize percentage values to decimals when serializing JSON arrays — bypassing them ensures the numbers are always correct.

**Two-phase analyst.** Steps 1-3 and Step 4 are separate `run_until_complete` calls with distinct trigger words (`STEPS 1-3 COMPLETE` / `ANALYSIS COMPLETE`). This guarantees Step 4 always runs regardless of how long Step 3 takes.

**Fresh agent for additional analysis.** When a user requests a drill-down at a checkpoint, a new analyst agent instance is created with no conversation history. The original agent's history ends with "ANALYSIS COMPLETE" which causes it to skip tool calls. The fresh agent gets all context via the task prompt instead.

**Master holds all memory.** Every Master call receives the full accumulated context — original analysis, all user-requested drill-downs, web research, and the current narrative. Specialist agents are stateless workers; Master is the single source of truth.

**SSE broadcast queue.** Each browser connection gets its own `queue.Queue`. `_push()` writes every event to all queues simultaneously, so reconnects and multiple tabs both see the complete event stream without missing messages.

**Dataset-agnostic prompts.** Master's system prompt contains no hardcoded column names. Dataset context (`primary_dim`, `secondary_dim`, `value_label`) is injected into every Master task message at runtime from `DatasetConfig`, preventing the model from defaulting to terminology from its training data.
