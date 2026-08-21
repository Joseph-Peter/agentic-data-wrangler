from django.urls import path

from wrangler_app import views

app_name = "wrangler_app"

urlpatterns = [
    path("", views.index, name="index"),
    path("progress/<str:job_id>/", views.progress_stream, name="progress_stream"),
    path("results/<str:job_id>/", views.results, name="results"),
]
