# Agentic Data Wrangler

## Description
An agentic solution that
* Allows user to upload upto 3 csv files as input data
* Allows user to specify the required data wrangling logic in natural language
* Generates Python code that does the requested data wrangling
* Uses LangGraph and Django
* Employs 3 AI agents - planner, architect, coder

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
