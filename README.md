# Morrow — AI-Powered Data Analyst

A local-first AI analytics application that lets users ask business questions in natural language, generate dashboards, and explore business insights.

Built with Python, Streamlit, SQLite, and Ollama.

> **Status:** Active development · Local prototype

## Overview

Morrow combines a natural-language SQL agent, interactive dashboard builder, data profiling, and sales intelligence tools in one application.

The goal is to make data analysis more accessible without hiding the SQL or analytical process from the user.

## Features

### 1. Natural-Language SQL Agent
- Ask business questions in plain English.
- Generate SQLite queries using a locally hosted Qwen model.
- Inspect generated SQL and query results.
- Receive natural-language explanations.
- Explore results through tables and visualizations.

### 2. SQL Safety
- SELECT/WITH-only query validation.
- Multiple-statement rejection.
- Read-only SQLite connections.
- SQLite query-only mode and authorizer restrictions.
- Query execution time limits.
- Maximum result-row limits.

### 3. AI Dashboard Builder
- Read uploaded datasets.
- Read SQLite databases in read-only mode.
- Profile dataset columns.
- Generate and validate dashboard plans.
- Render data visualizations.

### 4. Sales Intelligence
- Factual business insights.
- Monthly comparison analysis.
- Business evidence calculations.
- Recommendation generation.
- Root-cause analysis.
- Natural-language explanations.
- Saved dashboard management.

### 5. Interactive Interface
- Business question interface.
- Example prompts and quick actions.
- Results and visual analysis tabs.
- Sales dashboard.
- Dashboard save/load controls.

## Architecture

```text
                  User
                   |
                   v
              Streamlit UI
              dashboard.py
                   |
        +----------+-----------+
        |          |           |
        v          v           v
     SQL Agent  Dashboard   Sales Intelligence
     app/agent  Builder     app/sales_dashboard
        |          |           |
        v          v           +-- Insights
      Ollama       |           +-- Recommendations
      Qwen         |           +-- Root Cause
        |          |           +-- Saved Dashboards
        v          v
    SQL Validation  Data Profiling
        |
        v
   Read-only SQLite
        |
        v
 Results and Explanation


## Technology Stack

- Python 3.12
- Streamlit
- Pandas
- Plotly
- SQLite
- Ollama with Qwen 3.5 4B
- openpyxl for Excel file uploads

## Requirements

- Python 3.12 or compatible version
- Ollama installed and running
- The configured Qwen model available locally

## Installation

Clone the repository:

```bash
git clone https://github.com/pawan-aicode/morrow-ai-data-analyst.git
cd ai-data-analyst
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Pull the configured model:

```bash
ollama pull qwen3.5:4b-q4_K_M
```

Start the application:

```bash
streamlit run dashboard.py
```

## Running Tests

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the test suite:

```bash
pytest -q
```

Latest recorded test result: **178 passed, 27 subtests passed**.

## SQL Benchmark
The custom benchmark contains 30 questions across six categories: basic queries, filtering, aggregation, joins, ranking, and advanced queries.

| Run | Correct | Accuracy |
|---|---:|---:|
| Initial baseline | 28/30 | 93.33% |
| After prompt modification | 27/30 | 90.00% |

These are results from a small custom benchmark, not a standardized evaluation. Model output can vary between runs.

## Limitations

- SQL generation depends on the locally configured Ollama model.
- Generated SQL is restricted to read-only operations.
- The benchmark contains only 30 test cases.
- Results depend on the model, prompt, and database schema.
- The application currently targets a local development environment.

## Future Improvements

- Expand SQL benchmark coverage.
- Improve complex join and ranking query generation.
- Add more dataset formats and profiling capabilities.
- Improve error handling and query explanations.
- Add deployment and production monitoring.

## License

No open-source license has been selected yet. All rights reserved by default.
