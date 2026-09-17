import re

from django import forms


class UploadDocumentForm(forms.Form):
    file = forms.FileField(
        label="XML file",
        help_text="Upload a PubMed / PubMed Central XML article.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xml"}),
    )


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
