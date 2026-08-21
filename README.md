# Data Wrangling Agent

An agentic data wrangling solution using Django and LangGraph. Upload up to 3 CSV files and describe your data wrangling request — the system uses 3 AI agents (planner, architect, coder) to generate a Python/Pandas solution.

## Setup

```bash
uv sync
python manage.py migrate
python manage.py runserver
```

## Usage

1. Open http://localhost:8000 in your browser
2. Upload up to 3 CSV files
3. Describe your data wrangling request
4. The generated solution will be saved in the `generated_data_wrangler` folder
