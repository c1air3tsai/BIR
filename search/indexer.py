import os
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from django.db import transaction

from .models import Document, Posting, Term
from .text_processing import document_stats, preprocess


def _first_text(root, xpath):
    el = root.find(xpath)
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _article_id(root, kind):
    el = root.find(f".//article-id[@pub-id-type='{kind}']")
    return (el.text or "").strip() if el is not None else ""


def _local_name(tag):
    return str(tag).split("}")[-1]


def _clean_node_text(node):
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _extract_abstract(root):
    """Extract the main PMC/JATS abstract while preserving paragraph boundaries."""
    abstracts = [
        node for node in root.iter()
        if _local_name(node.tag) == "abstract"
    ]
    if not abstracts:
        return ""

    def abstract_score(node):
        abstract_type = (node.attrib.get("abstract-type", "") or "").strip().lower()
        penalty = -100000 if abstract_type in {"toc", "graphical", "teaser", "short"} else 0
        return penalty + len(_clean_node_text(node))

    abstract = max(abstracts, key=abstract_score)
    paragraphs = []
    for node in abstract.iter():
        if _local_name(node.tag) != "p":
            continue
        text = _clean_node_text(node)
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs) if paragraphs else _clean_node_text(abstract)


def _body_text(root):
    """Keep PMC/JATS section titles and paragraphs separated for later reading."""
    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), None)
    if body is None:
        return ""

    blocks = []
    for node in body.iter():
        tag = _local_name(node.tag)
        if tag not in {"title", "p"}:
            continue
        text = " ".join("".join(node.itertext()).split())
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


def _extract_text_from_xml(path: str):
    tree = ET.parse(path)
    root = tree.getroot()

    title = _first_text(root, ".//article-title") or os.path.basename(path)
    abstract = _extract_abstract(root)
    body = _body_text(root) or _first_text(root, ".//body")
    full_text = "\n\n".join(x for x in [title, abstract, body] if x).strip()
    if not full_text:
        full_text = " ".join("".join(root.itertext()).split())

    author_names = []
    for contrib in root.findall(".//contrib[@contrib-type='author']"):
        surname = _first_text(contrib, ".//surname")
        given = _first_text(contrib, ".//given-names")
        name = " ".join(x for x in [given, surname] if x)
        if name:
            author_names.append(name)

    meta = {
        "pmcid": _article_id(root, "pmcid") or _article_id(root, "pmcaid") or _article_id(root, "pmc"),
        "doi": _article_id(root, "doi"),
        "journal": _first_text(root, ".//journal-title"),
        "publication_year": _first_text(root, ".//pub-date/year") or _first_text(root, ".//year"),
        "authors": ", ".join(author_names),
        "abstract": abstract,
    }
    return title, full_text, meta


def parse_document(path: str):
    if path.lower().endswith(".xml"):
        return _extract_text_from_xml(path)
    raise ValueError("Only .xml files are supported")


def load_corpus(corpus_dir: str):
    documents = []
    if not os.path.isdir(corpus_dir):
        return documents
    for fname in sorted(os.listdir(corpus_dir)):
        fpath = os.path.join(corpus_dir, fname)
        if not os.path.isfile(fpath) or not fname.lower().endswith(".xml"):
            continue
        try:
            title, text, meta = parse_document(fpath)
        except ET.ParseError:
            continue
        if text:
            documents.append((title, text, fname, meta))
    return documents




class DuplicateDocumentError(ValueError):
    def __init__(self, document):
        self.document = document
        super().__init__(f"Article already exists: {document.title}")


def find_duplicate_document(title, meta, fname):
    """Find an existing article using stable metadata before indexing a new copy."""
    pmcid = (meta.get("pmcid") or "").strip()
    if pmcid:
        existing = Document.objects.filter(pmcid__iexact=pmcid).first()
        if existing:
            return existing

    doi = (meta.get("doi") or "").strip()
    if doi:
        existing = Document.objects.filter(doi__iexact=doi).first()
        if existing:
            return existing

    if fname:
        existing = Document.objects.filter(source_file__iexact=Path(fname).name).first()
        if existing:
            return existing

    # Fallback for XML files that contain neither PMCID nor DOI.
    title = (title or "").strip()
    if title:
        candidates = Document.objects.filter(title__iexact=title)
        year = (meta.get("publication_year") or "").strip()
        if year:
            candidates = candidates.filter(publication_year=year)
        existing = candidates.first()
        if existing:
            return existing
    return None


def inspect_document(path: str):
    """Parse a file and return metadata plus any matching existing document."""
    title, text, meta = parse_document(path)
    fname = Path(path).name
    return title, text, meta, find_duplicate_document(title, meta, fname)

def _index_one(title, text, fname, meta):
    # Current assignment stage indexes Title + Abstract only.
    # Full XML/body text is still preserved in Document.raw_text for future use.
    search_text = "\n\n".join(
        part for part in [title, meta.get("abstract") or ""] if part
    ).strip()

    # FUTURE FULL-TEXT SEARCH: comment the search_text block above and uncomment:
    # search_text = text

    stats = document_stats(search_text)
    doc = Document.objects.create(
        title=title[:500],
        source_file=fname,
        raw_text=text,
        char_count=stats["char_count"],
        word_count=stats["word_count"],
        sentence_count=stats["sentence_count"],
        avg_words_per_sentence=stats["avg_words_per_sentence"],
        pmcid=(meta.get("pmcid") or "")[:40],
        doi=(meta.get("doi") or "")[:200],
        journal=(meta.get("journal") or "")[:300],
        publication_year=(meta.get("publication_year") or "")[:10],
        authors=meta.get("authors") or "",
        abstract=meta.get("abstract") or "",
    )

    # UI stays simple; preprocessing and the inverted index happen silently here.
    freq = Counter(preprocess(search_text))
    postings = []
    for word, tf in freq.items():
        term, _ = Term.objects.get_or_create(word=word[:100])
        postings.append(Posting(term=term, document=doc, term_freq=tf))
    Posting.objects.bulk_create(postings, batch_size=1000)
    return doc


@transaction.atomic
def build_index(corpus_dir: str, reset: bool = True):
    if reset:
        Posting.objects.all().delete()
        Term.objects.all().delete()
        Document.objects.all().delete()

    raw_documents = load_corpus(corpus_dir)
    for title, text, fname, meta in raw_documents:
        _index_one(title, text, fname, meta)
    return len(raw_documents), Term.objects.count()


@transaction.atomic
def index_file(path: str, replace=False):
    title, text, meta = parse_document(path)
    fname = Path(path).name
    duplicate = find_duplicate_document(title, meta, fname)
    if duplicate and not replace:
        raise DuplicateDocumentError(duplicate)
    if duplicate and replace:
        duplicate.delete()
    doc = _index_one(title, text, fname, meta)
    Term.objects.filter(postings__isnull=True).delete()
    return doc
