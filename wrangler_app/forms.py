from django import forms


class DataWranglingForm(forms.Form):
    """Form for uploading CSVs and entering a data wrangling request."""

    wrangling_request = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 5,
            "placeholder": "Describe your data wrangling request...",
            "class": "form-control",
        }),
        label="Data Wrangling Request",
        help_text="Describe what you want to do with your CSV data using Pandas.",
    )
    csv_file_1 = forms.FileField(
        required=False,
        label="CSV File 1",
        help_text="Upload a CSV file (max 10MB).",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "form-control"}),
    )
    csv_file_2 = forms.FileField(
        required=False,
        label="CSV File 2",
        help_text="Upload a second CSV file (optional).",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "form-control"}),
    )
    csv_file_3 = forms.FileField(
        required=False,
        label="CSV File 3",
        help_text="Upload a third CSV file (optional).",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "form-control"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        files = [
            cleaned_data.get("csv_file_1"),
            cleaned_data.get("csv_file_2"),
            cleaned_data.get("csv_file_3"),
        ]
        has_file = any(f is not None for f in files)
        if not has_file:
            raise forms.ValidationError("Please upload at least one CSV file.")

        for f in files:
            if f is not None:
                if not f.name.endswith(".csv"):
                    raise forms.ValidationError(f"File '{f.name}' is not a CSV file.")
                if f.size > 10 * 1024 * 1024:
                    raise forms.ValidationError(f"File '{f.name}' exceeds the 10MB size limit.")

        return cleaned_data
