import re
from pathlib import Path

from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Validate every file selected by one multi-file input."""

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class UploadDocumentForm(forms.Form):
    files = MultipleFileField(
        label="XML files",
        help_text="Select up to 20 PubMed / PubMed Central XML articles.",
        widget=MultipleFileInput(attrs={"accept": ".xml", "multiple": True}),
    )

    def clean_files(self):
        files = self.cleaned_data["files"]
        if len(files) > 20:
            raise forms.ValidationError("Please upload no more than 20 XML files at one time.")
        invalid_names = [
            Path(uploaded.name).name
            for uploaded in files
            if Path(uploaded.name).suffix.lower() != ".xml"
        ]
        if invalid_names:
            raise forms.ValidationError(
                "Only .xml files are supported: " + ", ".join(invalid_names)
            )
        return files


class ArticleFetchForm(forms.Form):
    identifiers = forms.CharField(
        label="PMID or PMCID(s)",
        help_text=(
            "Enter one or more IDs. Use the PMC prefix for a PMCID; "
            "plain numbers are treated as PMID. Separate IDs with commas, spaces, or new lines."
        ),
        widget=forms.Textarea(attrs={
            "placeholder": "42724776\nPMC12503546",
            "rows": 5,
        }),
    )

    def clean_identifiers(self):
        raw = self.cleaned_data["identifiers"]
        values = [x.strip() for x in re.split(r"[\s,;]+", raw) if x.strip()]
        # Preserve order while removing repeated IDs within the same request.
        values = list(dict.fromkeys(values))
        if not values:
            raise forms.ValidationError("Please enter at least one PMID or PMCID.")
        if len(values) > 20:
            raise forms.ValidationError("Please fetch no more than 20 IDs at one time.")
        return values
