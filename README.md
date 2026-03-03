# Autonomous Multi-Agent Analytics System — POC

A two-agent AutoGen system that automates monthly credit card spend analysis.

## Agents
- **Analyst** — runs the full analytical workflow using Python tools
- **Manager** — critiques across 3 lenses: data accuracy, driver attribution, recommendation justification

## Setup

### 1. Create and activate virtual environment
```bash
python -m venv multi_agent_analytics_env
source multi_agent_analytics_env/bin/activate  # Mac/Linux
# or
multi_agent_analytics_env\Scripts\activate     # Windows
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure your .env file
Create a `.env` file in the project root:
```
OPENAI_API_KEY=sk-your-actual-key-here
REFERENCE_DATE=2015-10-01
```

- `OPENAI_API_KEY` — your OpenAI API key
- `REFERENCE_DATE` — the "today" date for the analysis. The system will analyze the month just before this date.
  - e.g. `2015-10-01` → analyzes September 2015
  - e.g. `2015-11-01` → analyzes October 2015
  - If not set, defaults to `2015-10-01`

### 4. Add your data
Place your CSV at `data/transactions.csv`.

Expected columns:
| Column    | Type   | Notes                    |
|-----------|--------|--------------------------|
| Date      | date   | e.g. 2015-09-15          |
| City      | string | city segmentation        |
| Card Type | string | product segmentation     |
| Exp Type  | string | expense/category type    |
| Gender    | string | demographic segmentation |
| Amount    | float  | transaction amount       |

### 5. Run
```bash
python main.py
```

## Project Structure
```
analytics_agents/
├── main.py          # Entry point — runs the agent conversation
├── agents.py        # Analyst and Manager agent definitions
├── prompts.py       # System prompts for both agents
├── tools.py         # All metric calculations (YoY, CTG, rolling avg, drill-down)
├── requirements.txt
├── .env             # Your API key and reference date (never commit this)
└── data/
    └── transactions.csv   ← your data goes here
```

## Changing the Analysis Period
Only one thing to update — in your `.env` file:
```
REFERENCE_DATE=2015-11-01   # now analyzes October 2015
```
All periods (current month, prior month, prior year, rolling window) update automatically.

## Metrics
- **YoY**: `(current_period / prior_year_period) - 1`
- **CTG**: `(segment_current - segment_prior_year) / total_prior_year_spend`
  - All CTGs for a dimension sum to total portfolio YoY ✓
- **7-day Rolling Avg**: `SUM(last 7 days of current month) / 7`
- **7-day Rolling Avg YoY**: `(rolling_avg_current / rolling_avg_prior_year) - 1`

## Conversation Flow
1. Analyst confirms schema and analysis periods
2. Analyst runs all 5 steps using tools, hands off to Manager
3. Manager critiques across 3 lenses, requests revisions
4. Analyst revises
5. Manager approves ("APPROVED") or does one more cycle
6. Max 10 messages before forced termination
