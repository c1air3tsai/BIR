import math
import re
from nltk.stem.porter import PorterStemmer

_stemmer = PorterStemmer()

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "at", "by", "for", "with", "about", "against", "between", "into",
    "through", "during", "before", "after", "above", "below", "from", "up", "down",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having",
    "do", "does", "did", "doing", "this", "that", "these", "those", "it", "its", "as",
    "we", "our", "their", "which", "who", "whom", "not", "no", "can", "will", "would",
    "should", "could", "may", "might", "must", "shall", "than", "so", "such"
}

ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "vs", "etc", "al", "fig", "figs",
    "eq", "eqs", "approx", "no", "nos", "vol", "vols", "pp", "p", "i.e", "e.g",
    "cf", "et", "inc", "ltd", "co", "st"
}

MULTI_DOT_ABBREVIATIONS = {
    "e.g.", "i.e.", "a.m.", "p.m.",
}

# Shared token rule used by indexing, ranking, statistics and highlighting.
# Examples counted as ONE token:
# COVID-19, SARS-CoV-2, IL-6, patient's, well-known, e.g., 48.1%, 0.05
TOKEN_PATTERN = re.compile(
    # Dotted abbreviations (e.g., i.e., U.S.) are one token.
    r"(?:[A-Za-z]\.){2,}"
    # Decimal/integer/percentage values are one token.
    r"|\d+(?:\.\d+)*(?:%)?"
    # Hyphenated/apostrophe biomedical words are one token.
    r"|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*",
    flags=re.UNICODE,
)


def tokenize(text: str):
    """Tokenize biomedical English text with hyphenated words and decimals intact."""
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text or "")]


def remove_stopwords(tokens):
    return [t for t in tokens if t not in STOPWORDS]


def stem_tokens(tokens):
    return [_stemmer.stem(t) for t in tokens]


def preprocess(text: str):
    """Main IR preprocessing: tokenize -> stop-word removal -> Porter stemming."""
    return stem_tokens(remove_stopwords(tokenize(text)))


def _split_paragraph_sentences(text: str):
    """Apply EOS rules inside one paragraph."""
    sentences = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if ch not in ".!?":
            i += 1
            continue

        if ch == ".":
            # Decimal number: 3.14 / 0.05 / 48.1
            if (
                0 < i < n - 1
                and text[i - 1].isdigit()
                and text[i + 1].isdigit()
            ):
                i += 1
                continue

            # Multi-dot abbreviations: e.g. / i.e. / a.m. / p.m.
            left = text[max(0, i - 12): i + 1].lower()
            if any(left.endswith(abbr) for abbr in MULTI_DOT_ABBREVIATIONS):
                i += 1
                continue

            # Normal abbreviations: Dr. / Fig. / etc.
            prefix = text[max(start, i - 30): i + 1]
            match = re.search(r"([A-Za-z]+)\.$", prefix)
            prev_word = match.group(1) if match else ""

            if prev_word.lower() in ABBREVIATIONS:
                i += 1
                continue

            # Initial followed by a capitalized name: J. Smith
            j = i + 1
            while j < n and text[j] in "\"'”’)]}":
                j += 1
            while j < n and text[j].isspace():
                j += 1

            if (
                len(prev_word) == 1
                and prev_word.isupper()
                and j < n
                and text[j].isupper()
            ):
                i += 1
                continue

        # Include closing quotation/bracket in the current sentence.
        end = i + 1
        while end < n and text[end] in "\"'”’)]}":
            end += 1

        # A punctuation candidate is an EOS when it is followed by whitespace
        # or the end of the paragraph. We deliberately do not require the next
        # sentence to start with an uppercase letter because biomedical text can
        # start with gene names, symbols or lowercase technical terms.
        if end >= n or text[end].isspace():
            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)

            start = end
            while start < n and text[start].isspace():
                start += 1
            i = start
            continue

        i += 1

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_sentences(text: str):
    """
    Rule-based sentence segmentation.

    Paragraph boundaries are handled separately, then EOS rules are applied
    within each paragraph. Guards cover decimals, common abbreviations,
    initials and closing quotes/brackets.
    """
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [
        p.strip()
        for p in re.split(r"(?:\r?\n){2,}", text)
        if p.strip()
    ]

    sentences = []
    for paragraph in paragraphs:
        sentences.extend(_split_paragraph_sentences(paragraph))
    return sentences


def document_stats(text: str):
    raw_text = text or ""
    visible_text = re.sub(r"\s+", " ", raw_text).strip()
    word_count = len(tokenize(visible_text))
    sentence_count = len(split_sentences(raw_text))
    return {
        "char_count": len(visible_text),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_words_per_sentence": round(word_count / sentence_count, 2) if sentence_count else 0,
    }


def bm25_score(tf, df, doc_len, avg_doc_len, total_docs, k1=1.5, b=0.75):
    """Classic BM25 contribution for one query term/document pair."""
    if tf <= 0 or df <= 0 or total_docs <= 0:
        return 0.0
    avg_doc_len = avg_doc_len or 1
    idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
    denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
    return idf * ((tf * (k1 + 1)) / denom)
