from django.test import TestCase

from .text_processing import document_stats, preprocess, split_sentences, tokenize
from .pmc_client import normalize_identifier


class TextProcessingTests(TestCase):
    def test_preprocess(self):
        self.assertIn("cancer", preprocess("The cancers are growing."))

    def test_biomedical_tokenization(self):
        tokens = tokenize("COVID-19 SARS-CoV-2 IL-6 patient's e.g. 48.1% 0.05")
        self.assertEqual(
            tokens,
            ["covid-19", "sars-cov-2", "il-6", "patient's", "e.g.", "48.1%", "0.05"],
        )

    def test_word_separator_rules(self):
        self.assertEqual(tokenize("activity/exercise"), ["activity", "exercise"])
        self.assertEqual(tokenize("0.44–0.97"), ["0.44", "0.97"])

    def test_sentence_rules(self):
        text = "Dr. Smith measured 3.14 mg. The result was significant."
        self.assertEqual(len(split_sentences(text)), 2)

    def test_multidot_abbreviation(self):
        text = "Several factors, e.g. age and sex, were recorded. Results were stable."
        self.assertEqual(len(split_sentences(text)), 2)

    def test_lowercase_sentence_start_is_not_lost(self):
        text = "The pathway was activated. p53 expression then increased."
        self.assertEqual(len(split_sentences(text)), 2)

    def test_stats(self):
        stats = document_stats("COVID-19 treatment works. It helps patients.")
        self.assertEqual(stats["sentence_count"], 2)
        self.assertEqual(stats["word_count"], 6)


class IdentifierTests(TestCase):
    def test_identifier_normalization(self):
        self.assertEqual(normalize_identifier("PMC12503546"), ("pmc", "PMC12503546"))
        self.assertEqual(normalize_identifier("42724776"), ("pubmed", "42724776"))
        self.assertEqual(normalize_identifier("PMID:42724776"), ("pubmed", "42724776"))
