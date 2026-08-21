import logging
import pathlib
import shutil
import time
from typing import Any, Callable

import pandas as pd
from dotenv import load_dotenv
from groq import RateLimitError
from langchain_groq.chat_models import ChatGroq
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.prebuilt import create_react_agent

from data_wrangling_agent.prompts import architect_prompt, coder_system_prompt, planner_prompt
from data_wrangling_agent.states import CoderState, Plan, TaskPlan
from data_wrangling_agent.tools import PROJECT_ROOT, get_current_directory, list_files, read_file, write_file

_ = load_dotenv()

logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_DELAY = 30
MAX_RATE_LIMIT_RETRIES = 5

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGroq(model="openai/gpt-oss-120b")
    return _llm


def is_rate_limit_error(e: BaseException) -> bool:
    """Check if an exception is an LLM rate limit error."""
    if isinstance(e, RateLimitError):
        return True
    if getattr(e, "status_code", None) == 429:
        return True
    response = getattr(e, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    error_name = type(e).__name__.lower()
    if "ratelimit" in error_name:
        return True
    error_msg = str(e).lower()
    if any(phrase in error_msg for phrase in ["rate limit", "rate_limit", "429", "too many requests"]):
        return True
    if e.__cause__ is not None and is_rate_limit_error(e.__cause__):
        return True
    if e.__context__ is not None and is_rate_limit_error(e.__context__):
        return True
    return False


def retry_on_rate_limit(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = MAX_RATE_LIMIT_RETRIES,
    retry_delay: int = RATE_LIMIT_RETRY_DELAY,
    on_retry: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a callable and retry after a delay when an LLM rate limit error occurs."""
    attempts = 0
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if is_rate_limit_error(e) and attempts < max_retries:
                attempts += 1
                msg = f"LLM rate limit reached. Retrying in {retry_delay}s (attempt {attempts}/{max_retries})..."
                logger.warning(msg)
                if on_retry:
                    try:
                        on_retry(msg)
                    except Exception:
                        pass
                time.sleep(retry_delay)
            else:
                raise


def _describe_csvs(csv_paths: list[str]) -> str:
    """Generate a text description of CSV files for the planner."""
    descriptions = []
    for path in csv_paths:
        try:
            df = pd.read_csv(path, nrows=5)
            name = pathlib.Path(path).name
            cols = ", ".join([f"{c} ({df[c].dtype})" for c in df.columns])
            descriptions.append(f"- {name}: columns=[{cols}], shape={df.shape[0]}+ rows x {df.shape[1]} cols")
        except Exception as e:
            descriptions.append(f"- {path}: ERROR reading file: {e}")
    return "\n".join(descriptions) if descriptions else "No CSV files provided."


def _copy_csvs_to_output(csv_paths: list[str]) -> None:
    """Copy uploaded CSV files to the generated_data_wrangler folder."""
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    for path in csv_paths:
        src = pathlib.Path(path)
        if src.exists():
            shutil.copy2(src, PROJECT_ROOT / src.name)


def _emit(state: dict, msg: str):
    cb = state.get("progress_callback")
    if cb:
        cb(msg)


def planner_agent(state: dict) -> dict:
    """Converts user prompt into a structured Plan."""
    user_prompt = state["user_prompt"]
    csv_descriptions = state.get("csv_descriptions", "")
    prompt = planner_prompt(user_prompt, csv_descriptions)
    structured_llm = _get_llm().with_structured_output(Plan)
    resp = retry_on_rate_limit(
        structured_llm.invoke,
        prompt,
        on_retry=lambda msg: _emit(state, msg),
    )
    if resp is None:
        raise ValueError("Planner did not return a valid response.")
    _emit(state, f"Planner complete — project '{resp.name}' with {len(resp.files)} file(s) planned.")
    return {"plan": resp}


def architect_agent(state: dict) -> dict:
    """Creates TaskPlan from Plan."""
    _emit(state, "Starting Architect agent — breaking plan into implementation tasks...")
    plan: Plan = state["plan"]
    prompt = architect_prompt(plan=plan.model_dump_json())
    structured_llm = _get_llm().with_structured_output(TaskPlan)
    resp = retry_on_rate_limit(
        structured_llm.invoke,
        prompt,
        on_retry=lambda msg: _emit(state, msg),
    )
    if resp is None:
        raise ValueError("Architect did not return a valid response.")

    resp.plan = plan
    _emit(state, f"Architect complete — {len(resp.implementation_steps)} implementation task(s) created.")
    return {"task_plan": resp}


def coder_agent(state: dict) -> dict:
    """LangGraph tool-using coder agent."""
    coder_state: CoderState = state.get("coder_state")
    if coder_state is None:
        coder_state = CoderState(task_plan=state["task_plan"], current_step_idx=0)
        _emit(state, "Starting Coder agent — implementing solution files...")

    steps = coder_state.task_plan.implementation_steps
    if coder_state.current_step_idx >= len(steps):
        _emit(state, "Coder complete — all files generated successfully.")
        return {"coder_state": coder_state, "status": "DONE"}

    current_task = steps[coder_state.current_step_idx]
    existing_content = read_file.invoke({"path": current_task.filepath})

    system_prompt = coder_system_prompt()
    user_prompt = (
        f"Task: {current_task.task_description}\n"
        f"File: {current_task.filepath}\n"
        f"Existing content:\n{existing_content}\n"
        "Use write_file(path, content) to save your changes."
    )

    coder_tools = [read_file, write_file, list_files, get_current_directory]
    react_agent = create_react_agent(_get_llm(), coder_tools)

    step_num = coder_state.current_step_idx + 1
    total = len(steps)
    _emit(state, f"Coder: implementing file {step_num}/{total} — {current_task.filepath}")

    retry_on_rate_limit(
        react_agent.invoke,
        {"messages": [{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}]},
        on_retry=lambda msg: _emit(state, msg),
    )

    coder_state.current_step_idx += 1
    _emit(state, f"Coder: completed {current_task.filepath}")
    return {"coder_state": coder_state}


graph = StateGraph(dict)

graph.add_node("planner", planner_agent)
graph.add_node("architect", architect_agent)
graph.add_node("coder", coder_agent)

graph.add_edge("planner", "architect")
graph.add_edge("architect", "coder")
graph.add_conditional_edges(
    "coder",
    lambda s: "END" if s.get("status") == "DONE" else "coder",
    {"END": END, "coder": "coder"}
)

graph.set_entry_point("planner")
agent = graph.compile()


def run_wrangling_agent(
    user_prompt: str,
    csv_paths: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """Main entry point: run the 3-agent pipeline for data wrangling.

    Args:
        user_prompt: The user's data wrangling request.
        csv_paths: List of paths to uploaded CSV files (up to 3).
        progress_callback: Optional callable(message: str) for progress updates.

    Returns:
        The final state dict from the agent pipeline.
    """
    def _emit(msg: str):
        if progress_callback:
            progress_callback(msg)

    csv_paths = csv_paths or []
    _emit("Analysing uploaded CSV files...")
    csv_descriptions = _describe_csvs(csv_paths)
    _copy_csvs_to_output(csv_paths)

    _emit("Starting Planner agent — creating project plan from your request...")
    result = agent.invoke(
        {
            "user_prompt": user_prompt,
            "csv_descriptions": csv_descriptions,
            "progress_callback": progress_callback,
        },
        {"recursion_limit": 100},
    )
    return result
