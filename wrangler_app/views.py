import json
import os
import queue
import tempfile
import threading
import uuid

from django.http import StreamingHttpResponse
from django.shortcuts import render

from wrangler_app.forms import DataWranglingForm

# In-memory store for active jobs: job_id -> {queue, status, result, error, csv_paths, upload_dir}
_jobs = {}


def _save_uploaded_csv(uploaded_file, upload_dir: str) -> str:
    """Save an uploaded CSV file to a temporary directory and return the path."""
    dest = os.path.join(upload_dir, uploaded_file.name)
    with open(dest, "wb") as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)
    return dest


def _run_agent_job(job_id: str, user_prompt: str, csv_paths: list[str]):
    """Run the agent pipeline in a background thread, pushing progress to the job queue."""
    job = _jobs[job_id]
    msg_queue = job["queue"]

    def progress_callback(message: str):
        msg_queue.put({"type": "progress", "message": message})

    try:
        from data_wrangling_agent.graph import run_wrangling_agent
        run_wrangling_agent(user_prompt=user_prompt, csv_paths=csv_paths, progress_callback=progress_callback)

        from data_wrangling_agent.tools import PROJECT_ROOT
        generated_files = {}
        if PROJECT_ROOT.exists():
            for f in sorted(PROJECT_ROOT.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(PROJECT_ROOT)
                    try:
                        generated_files[str(rel)] = f.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        generated_files[str(rel)] = "<binary file>"

        job["result"] = {"generated_files": generated_files, "output_dir": str(PROJECT_ROOT)}
        job["status"] = "done"
        msg_queue.put({
            "type": "complete",
            "message": (
                f"Generation complete! Your solution has been saved to: {PROJECT_ROOT}\n\n"
                f"To run the generated code:\n"
                f"  cd {PROJECT_ROOT}\n"
                f"  python <main_script>.py\n\n"
                f"To run the generated tests:\n"
                f"  cd {PROJECT_ROOT}\n"
                f"  python -m pytest"
            ),
            "output_dir": str(PROJECT_ROOT),
            "files": list(generated_files.keys()),
        })
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        msg_queue.put({"type": "error", "message": f"Error: {e}"})

    msg_queue.put(None)  # Sentinel to end the stream


def index(request):
    """Main page: upload CSVs and submit a wrangling request."""
    if request.method == "POST":
        form = DataWranglingForm(request.POST, request.FILES)
        if form.is_valid():
            # Save uploaded CSVs to a temp directory
            upload_dir = tempfile.mkdtemp(prefix="wrangler_upload_")
            csv_paths = []
            for field_name in ["csv_file_1", "csv_file_2", "csv_file_3"]:
                uploaded = form.cleaned_data.get(field_name)
                if uploaded is not None:
                    path = _save_uploaded_csv(uploaded, upload_dir)
                    csv_paths.append(path)

            user_prompt = form.cleaned_data["wrangling_request"]

            # Create a job and start the agent in a background thread
            job_id = uuid.uuid4().hex
            _jobs[job_id] = {
                "queue": queue.Queue(),
                "status": "running",
                "result": None,
                "error": None,
            }
            thread = threading.Thread(
                target=_run_agent_job,
                args=(job_id, user_prompt, csv_paths),
                daemon=True,
            )
            thread.start()

            return render(request, "wrangler_app/processing.html", {"job_id": job_id})
    else:
        form = DataWranglingForm()

    return render(request, "wrangler_app/index.html", {"form": form})


def progress_stream(request, job_id):
    """SSE endpoint that streams progress messages for a given job."""
    job = _jobs.get(job_id)
    if job is None:
        return StreamingHttpResponse(
            _sse_error("Job not found."),
            content_type="text/event-stream",
        )

    def event_stream():
        msg_queue = job["queue"]
        while True:
            try:
                msg = msg_queue.get(timeout=120)
            except queue.Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if msg is None:
                break

            yield f"data: {json.dumps(msg)}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def results(request, job_id):
    """Results page: show generated files after the job completes."""
    job = _jobs.get(job_id)
    if job is None or job["result"] is None:
        return render(request, "wrangler_app/results.html", {
            "generated_files": {},
            "output_dir": "",
            "error": "Job not found or not yet complete.",
        })

    result = job["result"]
    # Clean up the job from memory
    _jobs.pop(job_id, None)

    return render(request, "wrangler_app/results.html", {
        "generated_files": result["generated_files"],
        "output_dir": result["output_dir"],
    })


def _sse_error(message: str):
    """Yield a single SSE error event."""
    yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
