import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from .indexer import parse_document
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

    def test_project_word_count_examples(self):
        cases = {
            "0.65": ["0.65"],
            "24.9%": ["24.9%"],
            "0.65.": ["0.65"],
            "12-15%": ["12", "15%"],
            "12–15%": ["12", "15%"],
            "OR 0.65, CI: 0.44–0.97": ["or", "0.65", "ci", "0.44", "0.97"],
            "5-stage 5‐stage 5‑stage 5–stage": [
                "5-stage", "5‐stage", "5‑stage", "5–stage",
            ],
            "HIV-1 SARS-CoV-2 age‐specific non–small": [
                "hiv-1", "sars-cov-2", "age‐specific", "non–small",
            ],
            "Alzheimer's O’Malley factors—particularly": [
                "alzheimer's", "o’malley", "factors", "particularly",
            ],
            "i.e. e.g. U.S. Δ β α Brca1ΔC/ΔC": [
                "i.e.", "e.g.", "u.s.", "δ", "β", "α", "brca1δc", "δc",
            ],
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(tokenize(source), expected)

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

    def test_whitespace_and_keyword_line_stats(self):
        stats = document_stats("risk\n\nassessment\nKeywords: heart disease")
        self.assertEqual(stats["char_count"], len("risk assessment Keywords: heart disease"))
        self.assertEqual(stats["char_count_no_space"], len("riskassessmentKeywords:heartdisease"))
        self.assertEqual(stats["sentence_count"], 3)

    def test_chinese_sentence_endings(self):
        self.assertEqual(len(split_sentences("第一句。\n第二句！\n第三句？")), 3)


class XmlExtractionTests(SimpleTestCase):
    def _parse_xml(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "article.xml"
            path.write_text(xml, encoding="utf-8")
            return parse_document(str(path))

    def test_jats_main_abstract_headings_and_keywords(self):
        title, search_text, meta = self._parse_xml("""
            <article><front><article-meta>
              <title-group><article-title>Not counted or searched</article-title></title-group>
              <abstract abstract-type="toc"><p>Auxiliary summary.</p></abstract>
              <abstract abstract-type="normal">
                <sec><title>Results</title><p>Main result text.</p></sec>
              </abstract>
              <kwd-group><title>Keywords</title><kwd>heart disease</kwd><kwd>β cell</kwd></kwd-group>
            </article-meta></front><body><sec><title>Introduction</title><p>Body text.</p></sec></body></article>
        """)
        self.assertEqual(title, "Not counted or searched")
        self.assertEqual(meta["abstract"], "Main result text.\n\nKeywords: heart disease, β cell")
        self.assertNotIn("Results", meta["abstract"])
        self.assertNotIn(title, search_text)
        self.assertIn("Body text.", search_text)

    def test_existing_keywords_line_stops_abstract(self):
        _title, _search_text, meta = self._parse_xml("""
            <article><front><article-meta>
              <title-group><article-title>Title</article-title></title-group>
              <abstract>
                <p>Abstract content.</p>
                <p>Keywords: existing, terms</p>
                <p>Reply article text must be excluded.</p>
              </abstract>
              <kwd-group><kwd>duplicate metadata term</kwd></kwd-group>
            </article-meta></front></article>
        """)
        self.assertEqual(meta["abstract"], "Abstract content.\n\nKeywords: existing, terms")

    def test_pubmed_abstract_and_keywords(self):
        title, search_text, meta = self._parse_xml("""
            <PubmedArticleSet><PubmedArticle><MedlineCitation>
              <PMID>1</PMID><Article>
                <ArticleTitle>Bibliographic title</ArticleTitle>
                <Abstract>
                  <AbstractText Label="BACKGROUND">First block.</AbstractText>
                  <AbstractText Label="RESULTS">Second block.</AbstractText>
                </Abstract>
              </Article>
              <KeywordList><Keyword>one</Keyword><Keyword>two</Keyword></KeywordList>
            </MedlineCitation></PubmedArticle></PubmedArticleSet>
        """)
        self.assertEqual(meta["abstract"], "First block.\n\nSecond block.\n\nKeywords: one, two")
        self.assertEqual(search_text, meta["abstract"])
        self.assertNotIn(title, search_text)


class IdentifierTests(TestCase):
    def test_identifier_normalization(self):
        self.assertEqual(normalize_identifier("PMC12503546"), ("pmc", "PMC12503546"))
        self.assertEqual(normalize_identifier("42724776"), ("pubmed", "42724776"))
        self.assertEqual(normalize_identifier("PMID:42724776"), ("pubmed", "42724776"))
