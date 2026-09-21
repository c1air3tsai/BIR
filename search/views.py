import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg
from django.db.models.functions import Lower
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .forms import ArticleFetchForm, UploadDocumentForm
from .indexer import (
    DuplicateDocumentError,
    find_duplicate_document,
    index_file,
    parse_document,
)
from .models import Document, Term
from .pmc_client import download_article_xml
from .text_processing import (
    bm25_score,
    document_stats,
    iter_token_matches,
    preprocess,
    split_sentences,
    stem_tokens,
    tokenize,
)


def _corpus_dir():
    path = Path(settings.BASE_DIR) / "data" / "corpus"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetched_dir():
    """Temporary holding area for XML fetched from NCBI before the user uploads it."""
    path = Path(settings.BASE_DIR) / "data" / "fetched"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_fetched_file(name):
    """Return a staged XML path only when it stays inside data/fetched/."""
    if not name:
        return None
    safe_name = Path(name).name
    if Path(safe_name).suffix.lower() != ".xml":
        return None
    candidate = (_fetched_dir() / safe_name).resolve()
    root = _fetched_dir().resolve()
    if root not in candidate.parents or not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _query_terms(raw_query):
    return preprocess(raw_query)


def _build_snippet(text, raw_query, length=760):
    """Return a longer, query-centered result snippet."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""

    lowered = clean.lower()
    raw_terms = list(dict.fromkeys(tokenize(raw_query)))
    positions = []
    for term in raw_terms:
        match = re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", lowered)
        if match:
            positions.append(match.start())

    anchor = min(positions) if positions else 0
    start = max(0, anchor - 180)
    snippet = clean[start:start + length]
    return ("…" if start else "") + snippet + ("…" if start + length < len(clean) else "")


def _highlight(text, raw_query, match_state=None):
    """
    Highlight exact query words and Porter-equivalent word forms safely.

    When match_state is supplied, matching words also receive stable IDs so the
    article page can navigate Previous/Next matches without changing the text.
    """
    if not text or not raw_query:
        return escape(text or "")

    query_tokens = list(dict.fromkeys(tokenize(raw_query)))
    if not query_tokens:
        return escape(text)

    query_exact = set(query_tokens)
    query_stems = set(stem_tokens(query_tokens))
    output = []
    last = 0
    for match in iter_token_matches(text):
        output.append(escape(text[last:match.start()]))
        word = text[match.start():match.end()]
        lower = word.lower()
        word_stem = stem_tokens([lower])[0]
        safe_word = escape(word)

        if lower in query_exact or word_stem in query_stems:
            if match_state is not None:
                match_state["count"] += 1
                idx = match_state["count"]
                output.append(
                    f'<mark class="search-highlight keyword-match" '
                    f'id="match-{idx}" data-match-index="{idx}">{safe_word}</mark>'
                )
            else:
                output.append(f'<mark class="search-highlight">{safe_word}</mark>')
        else:
            output.append(safe_word)
        last = match.end()

    output.append(escape(text[last:]))
    return mark_safe("".join(output))


def _keyword_match_count(text, raw_query):
    """Count query-word matches using the same exact/stem logic as highlighting."""
    if not text or not raw_query:
        return 0
    query_tokens = list(dict.fromkeys(tokenize(raw_query)))
    if not query_tokens:
        return 0
    query_exact = set(query_tokens)
    query_stems = set(stem_tokens(query_tokens))
    count = 0
    for token in tokenize(text):
        token_stem = stem_tokens([token])[0]
        if token in query_exact or token_stem in query_stems:
            count += 1
    return count


def _basic_stats(text, include_sentences=True):
    """Display statistics based on visible text while preserving EOS paragraph rules."""
    stats = document_stats(text)
    result = {
        "characters": stats["char_count"],
        "characters_no_space": stats["char_count_no_space"],
        "words": stats["word_count"],
    }
    if include_sentences:
        result["sentences"] = stats["sentence_count"]
    return result


def _active_search_text(doc):
    """Search Abstract + Keywords + supplied body, never the article title."""
    return (doc.raw_text or doc.abstract or "").strip()


def _available_years():
    """Publication years that actually occur in the current collection."""
    years = (
        Document.objects.exclude(publication_year="")
        .values_list("publication_year", flat=True)
        .distinct()
    )
    # Year is stored as text; valid 4-digit years sort naturally as integers.
    return sorted(
        {str(year).strip() for year in years if str(year).strip()},
        key=lambda value: (not value.isdigit(), -(int(value) if value.isdigit() else 0), value),
    )


def _normalize_year_filter(raw_year, available_years):
    year = (raw_year or "").strip()
    return year if year in set(available_years) else ""


def _search_stopword_fallback(raw_query, year=""):
    """
    Fallback for queries such as 'on the' after stop-word removal leaves no
    indexed terms.
    A year filter, when selected, is applied before matching.
    """
    query_tokens = list(dict.fromkeys(tokenize(raw_query)))
    if not query_tokens:
        return []

    documents = Document.objects.all()
    if year:
        documents = documents.filter(publication_year=year)

    results = []
    for doc in documents:
        counts = Counter(tokenize(_active_search_text(doc)))
        if all(counts[token] > 0 for token in query_tokens):
            hit_count = sum(counts[token] for token in query_tokens)
            results.append((doc, hit_count))

    results.sort(key=lambda item: (-item[1], item[0].title.lower()))
    output = []
    for doc, score in results:
        output.append({
            "doc": doc,
            "score": score,
            "snippet": _build_snippet(doc.abstract, raw_query),
            "keyword_count": _keyword_match_count(doc.abstract, raw_query),
            "abstract_stats": _basic_stats(doc.abstract, include_sentences=True),
        })
    return output


def _search_bm25(raw_query, year=""):
    terms = list(dict.fromkeys(_query_terms(raw_query)))
    if not terms:
        return _search_stopword_fallback(raw_query, year=year), terms

    document_qs = Document.objects.all()
    if year:
        document_qs = document_qs.filter(publication_year=year)

    documents = list(document_qs)
    total_docs = len(documents)
    if not total_docs:
        return [], terms

    docs = {doc.id: doc for doc in documents}
    allowed_doc_ids = set(docs)
    search_lengths = {
        doc.id: len(preprocess(_active_search_text(doc))) for doc in documents
    }
    avg_len = sum(search_lengths.values()) / total_docs or 1
    score_map = {}

    for word in terms:
        term = Term.objects.filter(word=word).first()
        if not term:
            continue
        postings = [
            posting
            for posting in term.postings.all()
            if posting.document_id in allowed_doc_ids
        ]
        df = len(postings)
        for posting in postings:
            doc = docs[posting.document_id]
            score_map[posting.document_id] = score_map.get(posting.document_id, 0) + bm25_score(
                posting.term_freq, df, search_lengths[doc.id], avg_len, total_docs
            )

    ranked = sorted(score_map, key=score_map.get, reverse=True)
    results = []
    for doc_id in ranked:
        doc = docs[doc_id]
        results.append({
            "doc": doc,
            "score": round(score_map[doc_id], 4),
            "snippet": _build_snippet(doc.abstract, raw_query),
            # Keyword count is intentionally Abstract-only for the current assignment stage.
            "keyword_count": _keyword_match_count(doc.abstract, raw_query),
            "abstract_stats": _basic_stats(doc.abstract, include_sentences=True),
        })
    return results, terms


def search_view(request):
    query = request.GET.get("q", "").strip()
    collection_count = Document.objects.count()
    available_years = _available_years()
    year = _normalize_year_filter(request.GET.get("year", ""), available_years)
    page_obj = None

    if query:
        all_results, _ = _search_bm25(query, year=year)
        paginator = Paginator(all_results, 10)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        for result in page_obj.object_list:
            result["highlighted_title"] = _highlight(result["doc"].title, query)
            result["highlighted_snippet"] = _highlight(result["snippet"], query)

    return render(request, "search/home.html", {
        "query": query,
        "year": year,
        "available_years": available_years,
        "page_obj": page_obj,
        "collection_count": collection_count,
        "page_title": "Biomedical Literature Search",
    })


def _article_body_for_display(doc):
    """Fallback body text when the source XML is not available."""
    text = (doc.raw_text or "").strip()
    title = (doc.title or "").strip()
    abstract = (doc.abstract or "").strip()

    if title and text.startswith(title):
        text = text[len(title):].lstrip()
    if abstract and text.startswith(abstract):
        text = text[len(abstract):].lstrip()
    return text


def _local_name(tag):
    return str(tag).split("}")[-1]


def _xml_source_path(doc):
    if not doc.source_file.lower().endswith(".xml"):
        return None
    candidate = (_corpus_dir() / Path(doc.source_file).name).resolve()
    root = _corpus_dir().resolve()
    if root not in candidate.parents or not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _xml_body_blocks(doc):
    """
    Preserve JATS/PMC body structure for reading: section title -> paragraph.
    Each paragraph is later segmented into sentences by the rule-based EOS logic.
    """
    source = _xml_source_path(doc)
    if not source:
        return [], 0

    try:
        root = ET.parse(source).getroot()
    except (ET.ParseError, OSError):
        return [], 0

    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), None)
    if body is None:
        return [], 0

    blocks = []
    for node in body.iter():
        tag = _local_name(node.tag)
        if tag not in {"title", "p"}:
            continue
        text = " ".join("".join(node.itertext()).split())
        if not text:
            continue
        if tag == "title":
            blocks.append({"type": "section", "text": text})
        else:
            blocks.append({"type": "paragraph", "text": text})

    paragraph_count = sum(1 for node in body.iter() if _local_name(node.tag) == "p")
    return blocks, paragraph_count


def _build_reading_blocks(doc, query):
    xml_blocks, paragraph_count = _xml_body_blocks(doc)

    if not xml_blocks:
        fallback = _article_body_for_display(doc)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", fallback) if p.strip()]
        if not paragraphs and fallback:
            paragraphs = [fallback]
        xml_blocks = [{"type": "paragraph", "text": p} for p in paragraphs]
        if not paragraph_count:
            paragraph_count = len(paragraphs)

    match_state = {"count": 0}
    reading_blocks = []
    sentence_number = 0
    body_stat_parts = []

    for block in xml_blocks:
        body_stat_parts.append(block["text"])

        if block["type"] == "section":
            reading_blocks.append({
                "type": "section",
                "html": _highlight(block["text"], query),
            })
            continue

        sentences = split_sentences(block["text"])
        rendered = []
        for sentence in sentences:
            sentence_number += 1
            rendered.append({
                "number": sentence_number,
                "html": _highlight(sentence, query, match_state),
            })
        if rendered:
            reading_blocks.append({"type": "paragraph", "sentences": rendered})

    return (
        reading_blocks,
        paragraph_count,
        match_state["count"],
        sentence_number,
        "\n\n".join(body_stat_parts),
    )


def _build_abstract_sentences(abstract, query):
    """Render the Abstract sentence-by-sentence with optional keyword navigation IDs."""
    match_state = {"count": 0}
    rendered = []
    for number, sentence in enumerate(split_sentences(abstract), start=1):
        rendered.append({
            "number": number,
            "html": _highlight(sentence, query, match_state),
        })
    return rendered, match_state["count"]


def document_detail_view(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    query = request.GET.get("q", "").strip()
    result_page = request.GET.get("page", "").strip()
    result_year = request.GET.get("year", "").strip()

    abstract_stats = _basic_stats(doc.abstract, include_sentences=True)
    abstract_sentences, abstract_match_count = _build_abstract_sentences(doc.abstract, query)
    keyword_count = _keyword_match_count(doc.abstract, query) if query else None

    # ----------------------------------------------------------------------
    # FUTURE FULL-TEXT SUPPORT (currently disabled for this assignment stage)
    # To restore full-text display/statistics later, uncomment this block and
    # the matching FUTURE FULL TEXT block in document_detail.html.
    #
    # (
    #     reading_blocks,
    #     paragraph_count,
    #     match_count,
    #     body_sentence_count,
    #     body_stat_text,
    # ) = _build_reading_blocks(doc, query)
    #
    # body_stats = _basic_stats(body_stat_text, include_sentences=False)
    # visible_parts = [part for part in [doc.title, doc.abstract, body_stat_text] if part]
    # overall_visible_text = re.sub(r"\s+", " ", "\n\n".join(visible_parts)).strip()
    # overall_stats = {
    #     "words": len(tokenize(overall_visible_text)),
    #     "sentences": abstract_stats.get("sentences", 0) + body_sentence_count,
    #     "characters": len(overall_visible_text),
    #     "paragraphs": paragraph_count,
    # }
    # ----------------------------------------------------------------------

    return render(request, "search/document_detail.html", {
        "doc": doc,
        "query": query,
        "result_page": result_page,
        "result_year": result_year,
        "highlighted_title": _highlight(doc.title, query),
        "abstract_sentences": abstract_sentences,
        "abstract_match_count": abstract_match_count,
        "keyword_count": keyword_count,
        "abstract_stats": abstract_stats,
        "page_title": doc.title,
        # FUTURE FULL-TEXT context (restore with the block above):
        # "reading_blocks": reading_blocks,
        # "match_count": match_count,
        # "overall_stats": overall_stats,
    })


def articles_view(request):
    # Newest-added is the default collection order.
    sort = request.GET.get("sort", "newest")
    available_years = _available_years()
    year = _normalize_year_filter(request.GET.get("year", ""), available_years)

    documents = Document.objects.all()
    if year:
        documents = documents.filter(publication_year=year)

    if sort == "az":
        documents = documents.order_by(Lower("title"))
    elif sort == "za":
        documents = documents.order_by(Lower("title").desc())
    elif sort == "oldest":
        documents = documents.order_by("indexed_at", Lower("title"))
    else:
        sort = "newest"
        documents = documents.order_by("-indexed_at", Lower("title"))

    filtered_count = documents.count()
    paginator = Paginator(documents, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    for doc in page_obj.object_list:
        doc.abstract_stats = _basic_stats(doc.abstract, include_sentences=True)

    return render(request, "search/articles.html", {
        "page_obj": page_obj,
        "sort": sort,
        "year": year,
        "available_years": available_years,
        "filtered_count": filtered_count,
        "total_docs": Document.objects.count(),
        "page_title": "Articles",
    })


def _available_corpus_path(filename):
    """Choose a safe non-conflicting filename in data/corpus/."""
    safe_name = Path(filename).name
    stem = Path(safe_name).stem or "article"
    suffix = Path(safe_name).suffix.lower() or ".xml"
    candidate = _corpus_dir() / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = _corpus_dir() / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _set_import_result(request, uploaded=None, duplicates=None, errors=None):
    uploaded = uploaded or []
    duplicates = duplicates or []
    errors = errors or []
    if uploaded and (duplicates or errors):
        kind = "partial"
    elif uploaded:
        kind = "success"
    elif duplicates:
        kind = "duplicate"
    else:
        kind = "error"
    request.session["import_result"] = {
        "kind": kind,
        "uploaded": [{"id": d.pk, "title": d.title} for d in uploaded],
        "duplicates": [{"id": d.pk, "title": d.title} for d in duplicates],
        "errors": [str(x) for x in errors],
    }


def _staged_files_from_session(request):
    names = request.session.get("fetched_files", [])
    valid = []
    cleaned_names = []
    for name in names:
        staged = _safe_fetched_file(name)
        if staged:
            cleaned_names.append(staged.name)
            valid.append({
                "name": staged.name,
                "size_kb": max(1, round(staged.stat().st_size / 1024)),
            })
    if cleaned_names != names:
        request.session["fetched_files"] = cleaned_names
    return valid


def _remove_staged_name(request, name):
    names = request.session.get("fetched_files", [])
    request.session["fetched_files"] = [n for n in names if n != name]


def _duplicate_for_path(path, source_name=None):
    title, _text, meta = parse_document(str(path))
    return find_duplicate_document(title, meta, source_name or Path(path).name)


def import_view(request):
    upload_form = UploadDocumentForm()
    fetch_form = ArticleFetchForm()
    import_result = request.session.pop("import_result", None)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "upload":
            upload_form = UploadDocumentForm(request.POST, request.FILES)
            if upload_form.is_valid():
                uploaded_docs = []
                duplicate_docs = []
                errors = []

                for uploaded in upload_form.cleaned_data["files"]:
                    safe_name = Path(uploaded.name).name
                    temp_path = None
                    target = None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="wb", suffix=".xml", dir=_fetched_dir(), delete=False
                        ) as temp:
                            temp_path = Path(temp.name)
                            for chunk in uploaded.chunks():
                                temp.write(chunk)

                        duplicate = _duplicate_for_path(temp_path, safe_name)
                        if duplicate:
                            duplicate_docs.append(duplicate)
                            temp_path.unlink(missing_ok=True)
                            temp_path = None
                            continue

                        target = _available_corpus_path(safe_name)
                        shutil.move(str(temp_path), target)
                        temp_path = None
                        uploaded_docs.append(index_file(str(target), replace=False))
                    except DuplicateDocumentError as exc:
                        duplicate_docs.append(exc.document)
                        if target:
                            target.unlink(missing_ok=True)
                    except Exception as exc:
                        errors.append(f"{safe_name}: {exc}")
                        if target:
                            target.unlink(missing_ok=True)
                    finally:
                        if temp_path:
                            temp_path.unlink(missing_ok=True)

                _set_import_result(
                    request,
                    uploaded=uploaded_docs,
                    duplicates=duplicate_docs,
                    errors=errors,
                )
                return redirect("search:import")

        elif action in {"article_fetch", "pmc_fetch"}:
            fetch_form = ArticleFetchForm(request.POST)
            if fetch_form.is_valid():
                fetched_names = request.session.get("fetched_files", [])
                errors = []
                fetched_count = 0
                for identifier in fetch_form.cleaned_data["identifiers"]:
                    try:
                        path = Path(download_article_xml(identifier, str(_fetched_dir())))
                        if path.name not in fetched_names:
                            fetched_names.append(path.name)
                        fetched_count += 1
                    except Exception as exc:
                        errors.append(f"{identifier}: {exc}")
                request.session["fetched_files"] = fetched_names
                if fetched_count:
                    messages.success(
                        request,
                        f"Fetched {fetched_count} XML file{'s' if fetched_count != 1 else ''}. You can upload them below."
                    )
                for error in errors:
                    messages.error(request, f"Fetch failed — {error}")
                return redirect("search:import")

        elif action in {"upload_fetched", "upload_all_fetched"}:
            if action == "upload_fetched":
                requested_names = [request.POST.get("fetched_name", "")]
            else:
                requested_names = list(request.session.get("fetched_files", []))

            uploaded_docs = []
            duplicate_docs = []
            errors = []

            for name in requested_names:
                staged = _safe_fetched_file(name)
                if not staged:
                    errors.append(f"{name or 'Fetched XML'} could not be found.")
                    _remove_staged_name(request, name)
                    continue

                try:
                    duplicate = _duplicate_for_path(staged, staged.name)
                    if duplicate:
                        duplicate_docs.append(duplicate)
                        staged.unlink(missing_ok=True)
                        _remove_staged_name(request, staged.name)
                        continue

                    target = _available_corpus_path(staged.name)
                    shutil.copy2(staged, target)
                    try:
                        doc = index_file(str(target), replace=False)
                    except Exception:
                        target.unlink(missing_ok=True)
                        raise
                    uploaded_docs.append(doc)
                    staged.unlink(missing_ok=True)
                    _remove_staged_name(request, staged.name)
                except DuplicateDocumentError as exc:
                    duplicate_docs.append(exc.document)
                    staged.unlink(missing_ok=True)
                    _remove_staged_name(request, staged.name)
                except Exception as exc:
                    errors.append(f"{staged.name}: {exc}")

            _set_import_result(
                request,
                uploaded=uploaded_docs,
                duplicates=duplicate_docs,
                errors=errors,
            )
            return redirect("search:import")

    fetched_files = _staged_files_from_session(request)
    return render(request, "search/import.html", {
        "upload_form": upload_form,
        "fetch_form": fetch_form,
        "fetched_files": fetched_files,
        "import_result": import_result,
        "page_title": "Upload Article",
    })


@require_POST
def delete_document_view(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    title = doc.title
    source = _xml_source_path(doc)
    doc.delete()  # Posting rows are removed by cascade.
    Term.objects.filter(postings__isnull=True).delete()
    if source:
        source.unlink(missing_ok=True)
    messages.success(request, f'"{title}" was deleted from the collection.')
    return redirect("search:articles")

def download_xml_view(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    file_path = _xml_source_path(doc)
    if not file_path:
        raise Http404("XML source not found")
    return FileResponse(file_path.open("rb"), as_attachment=True, filename=file_path.name)
