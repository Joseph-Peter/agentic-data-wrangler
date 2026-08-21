import json
from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from wrangler_app.forms import DataWranglingForm
from wrangler_app import views


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
