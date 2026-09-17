import re

from django import forms


class UploadDocumentForm(forms.Form):
    file = forms.FileField(
        label="XML file",
        help_text="Upload a PubMed Central / JATS XML article.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xml"}),
    )


class PMCDownloadForm(forms.Form):
    pmcids = forms.CharField(
        label="PMCID(s)",
        help_text="Enter one or more PMCIDs. Separate them with commas, spaces, or new lines.",
        widget=forms.Textarea(attrs={
            "placeholder": "PMC8270360\nPMC1234567",
            "rows": 5,
        }),
    )

    def clean_pmcids(self):
        raw = self.cleaned_data["pmcids"]
        values = [x.strip() for x in re.split(r"[\s,;]+", raw) if x.strip()]
        # Preserve order while removing repeated IDs within the same request.
        values = list(dict.fromkeys(values))
        if not values:
            raise forms.ValidationError("Please enter at least one PMCID.")
        if len(values) > 20:
            raise forms.ValidationError("Please fetch no more than 20 PMCIDs at one time.")
        return values
