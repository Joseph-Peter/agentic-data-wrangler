import json
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from groq import RateLimitError
import httpx

from data_wrangling_agent.graph import (
    architect_agent,
    coder_agent,
    is_rate_limit_error,
    planner_agent,
    retry_on_rate_limit,
)
from data_wrangling_agent.states import CoderState, File, ImplementationTask, Plan, TaskPlan
from wrangler_app import views
from wrangler_app.forms import DataWranglingForm


class DataWranglingFormTest(TestCase):
    """Tests for the DataWranglingForm validation logic."""

    def _make_csv(self, name="test.csv", content=b"a,b\n1,2\n"):
        return SimpleUploadedFile(name, content, content_type="text/csv")

    def test_valid_form_with_one_csv(self):
        csv_file = self._make_csv()
        form = DataWranglingForm(
            data={"wrangling_request": "Merge columns a and b"},
            files={"csv_file_1": csv_file},
        )
        self.assertTrue(form.is_valid())

    def test_valid_form_with_three_csvs(self):
        form = DataWranglingForm(
            data={"wrangling_request": "Join all files"},
            files={
                "csv_file_1": self._make_csv("one.csv"),
                "csv_file_2": self._make_csv("two.csv"),
                "csv_file_3": self._make_csv("three.csv"),
            },
        )
        self.assertTrue(form.is_valid())

    def test_form_requires_at_least_one_csv(self):
        form = DataWranglingForm(
            data={"wrangling_request": "Do something"},
            files={},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Please upload at least one CSV file.", form.non_field_errors())

    def test_form_rejects_non_csv_file(self):
        bad_file = SimpleUploadedFile("data.txt", b"hello", content_type="text/plain")
        form = DataWranglingForm(
            data={"wrangling_request": "Process data"},
            files={"csv_file_1": bad_file},
        )
        self.assertFalse(form.is_valid())

    def test_form_requires_wrangling_request(self):
        form = DataWranglingForm(
            data={"wrangling_request": ""},
            files={"csv_file_1": self._make_csv()},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("wrangling_request", form.errors)


class IndexViewTest(TestCase):
    """Tests for the index view."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("wrangler_app:index")

    def test_get_index_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Wrangling Agent")
        self.assertContains(response, "csrf")

    def test_post_without_files_shows_error(self):
        response = self.client.post(self.url, {"wrangling_request": "Do something"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please upload at least one CSV file.")

    def test_post_without_request_text_shows_error(self):
        csv_file = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", content_type="text/csv")
        response = self.client.post(self.url, {"wrangling_request": "", "csv_file_1": csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")

    @patch("wrangler_app.views._run_agent_job")
    def test_successful_submission_shows_processing_page(self, mock_run):
        csv_file = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", content_type="text/csv")
        response = self.client.post(self.url, {
            "wrangling_request": "Sum column a",
            "csv_file_1": csv_file,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Processing Your Request")
        self.assertContains(response, "EventSource")


class ProgressStreamViewTest(TestCase):
    """Tests for the SSE progress stream endpoint."""

    def setUp(self):
        self.client = Client()

    def test_unknown_job_returns_error_event(self):
        url = reverse("wrangler_app:progress_stream", args=["nonexistent123"])
        response = self.client.get(url)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        content = b"".join(response.streaming_content).decode()
        data = json.loads(content.split("data: ")[1].strip())
        self.assertEqual(data["type"], "error")
        self.assertIn("not found", data["message"])

    def test_progress_stream_delivers_messages(self):
        import queue
        job_id = "testjob123"
        msg_queue = queue.Queue()
        views._jobs[job_id] = {
            "queue": msg_queue,
            "status": "running",
            "result": None,
            "error": None,
        }
        msg_queue.put({"type": "progress", "message": "Step 1"})
        msg_queue.put({"type": "complete", "message": "Done!"})
        msg_queue.put(None)

        url = reverse("wrangler_app:progress_stream", args=[job_id])
        response = self.client.get(url)
        content = b"".join(response.streaming_content).decode()
        self.assertIn("Step 1", content)
        self.assertIn("Done!", content)

        views._jobs.pop(job_id, None)


class ResultsViewTest(TestCase):
    """Tests for the results page."""

    def setUp(self):
        self.client = Client()

    def test_unknown_job_shows_error(self):
        url = reverse("wrangler_app:results", args=["nonexistent123"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not found")

    def test_completed_job_shows_results(self):
        job_id = "resultjob456"
        views._jobs[job_id] = {
            "queue": MagicMock(),
            "status": "done",
            "result": {
                "generated_files": {"main.py": "print('hello')"},
                "output_dir": "/tmp/generated_data_wrangler",
            },
            "error": None,
        }

        url = reverse("wrangler_app:results", args=[job_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generation Complete")
        self.assertContains(response, "main.py")
        self.assertContains(response, "print(&#x27;hello&#x27;)")
        # Job should be cleaned up after viewing
        self.assertNotIn(job_id, views._jobs)


class RateLimitRetryTest(TestCase):
    """Tests for LLM rate limit exception detection and 30-second retry handling."""

    def _make_rate_limit_error(self):
        request = httpx.Request("POST", "https://api.groq.com/v1/chat/completions")
        response = httpx.Response(429, request=request)
        return RateLimitError(message="Rate limit exceeded", response=response, body=None)

    def test_is_rate_limit_error_detection(self):
        # Groq RateLimitError
        self.assertTrue(is_rate_limit_error(self._make_rate_limit_error()))

        # Generic exception with 429 status code
        err_with_status = Exception("Custom error")
        err_with_status.status_code = 429
        self.assertTrue(is_rate_limit_error(err_with_status))

        # Exception with rate limit message
        self.assertTrue(is_rate_limit_error(Exception("Rate limit reached for requests per minute (RPM)")))
        self.assertTrue(is_rate_limit_error(Exception("429 Too Many Requests")))

        # Wrapped exception in __cause__ or __context__
        wrapped_err = ValueError("Invocation failed")
        wrapped_err.__cause__ = self._make_rate_limit_error()
        self.assertTrue(is_rate_limit_error(wrapped_err))

        # Negative scenario: non-rate-limit exception
        self.assertFalse(is_rate_limit_error(ValueError("Invalid argument")))
        self.assertFalse(is_rate_limit_error(KeyError("missing_key")))

    @patch("time.sleep")
    def test_retry_on_rate_limit_success_after_retries(self, mock_sleep):
        mock_fn = MagicMock(side_effect=[self._make_rate_limit_error(), self._make_rate_limit_error(), "success"])
        on_retry = MagicMock()

        result = retry_on_rate_limit(mock_fn, "arg1", key="val", on_retry=on_retry)

        self.assertEqual(result, "success")
        self.assertEqual(mock_fn.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(30)
        self.assertEqual(on_retry.call_count, 2)

    @patch("time.sleep")
    def test_retry_on_rate_limit_fails_non_rate_limit_immediately(self, mock_sleep):
        mock_fn = MagicMock(side_effect=ValueError("Invalid prompt"))

        with self.assertRaises(ValueError):
            retry_on_rate_limit(mock_fn)

        self.assertEqual(mock_fn.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_retry_on_rate_limit_exhausts_max_retries(self, mock_sleep):
        rate_err = self._make_rate_limit_error()
        mock_fn = MagicMock(side_effect=rate_err)

        with self.assertRaises(RateLimitError):
            retry_on_rate_limit(mock_fn, max_retries=3, retry_delay=30)

        self.assertEqual(mock_fn.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_sleep.assert_called_with(30)

    @patch("time.sleep")
    @patch("data_wrangling_agent.graph._get_llm")
    def test_planner_agent_retries_on_rate_limit(self, mock_get_llm, mock_sleep):
        expected_plan = Plan(
            name="TestApp",
            description="Test app description",
            techstack="python",
            features=["feature1"],
            files=[File(path="test.py", purpose="test file")],
        )
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = [self._make_rate_limit_error(), expected_plan]
        mock_get_llm.return_value.with_structured_output.return_value = mock_structured

        state = {"user_prompt": "Create test app", "csv_descriptions": "test.csv"}
        result = planner_agent(state)

        self.assertEqual(result["plan"], expected_plan)
        self.assertEqual(mock_structured.invoke.call_count, 2)
        mock_sleep.assert_called_once_with(30)

    @patch("time.sleep")
    @patch("data_wrangling_agent.graph._get_llm")
    def test_architect_agent_retries_on_rate_limit(self, mock_get_llm, mock_sleep):
        plan = Plan(
            name="TestApp",
            description="Test app description",
            techstack="python",
            features=["feature1"],
            files=[File(path="test.py", purpose="test file")],
        )
        expected_task_plan = TaskPlan(
            implementation_steps=[
                ImplementationTask(filepath="test.py", task_description="Implement test file")
            ]
        )
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = [self._make_rate_limit_error(), expected_task_plan]
        mock_get_llm.return_value.with_structured_output.return_value = mock_structured

        state = {"plan": plan}
        result = architect_agent(state)

        self.assertEqual(result["task_plan"].implementation_steps, expected_task_plan.implementation_steps)
        self.assertEqual(mock_structured.invoke.call_count, 2)
        mock_sleep.assert_called_once_with(30)

    @patch("time.sleep")
    @patch("data_wrangling_agent.graph.create_react_agent")
    @patch("data_wrangling_agent.graph.read_file")
    def test_coder_agent_retries_on_rate_limit(self, mock_read, mock_create_agent, mock_sleep):
        mock_read.invoke.return_value = ""
        mock_react = MagicMock()
        mock_react.invoke.side_effect = [self._make_rate_limit_error(), {"messages": []}]
        mock_create_agent.return_value = mock_react

        task_plan = TaskPlan(
            implementation_steps=[
                ImplementationTask(filepath="test.py", task_description="Implement test file")
            ]
        )
        coder_state = CoderState(task_plan=task_plan, current_step_idx=0)
        state = {"coder_state": coder_state}

        result = coder_agent(state)

        self.assertEqual(result["coder_state"].current_step_idx, 1)
        self.assertEqual(mock_react.invoke.call_count, 2)
        mock_sleep.assert_called_once_with(30)
