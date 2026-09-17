# Biomedical Literature Search — Abstract Stage

A Django-based biomedical information retrieval system for PubMed Central (PMC) XML articles.
The current homework stage focuses on **Title + Abstract**. Full body text is still stored and the code is preserved for later use, but full-text display/statistics are temporarily disabled.

## Run

```bash
docker compose up --build
```

Open: `http://localhost:8000/`

## Current functions

- Search article **titles and abstracts** with an inverted index + BM25 ranking.
- Porter stemming and stop-word handling; stop-word-only queries such as `on the` still have a fallback search.
- Search-result keyword highlighting and **Abstract keyword match count**.
- Article collection with A–Z/Z–A/date sorting, Abstract preview, and deletion.
- Upload PMC XML or fetch one/multiple PMCIDs from PubMed Central.
- Duplicate detection by PMCID, DOI, source filename, then title/year.
- Article detail page shows metadata, Title statistics, and a sentence-segmented Abstract.

## Text counting rules

### Characters
- Count visible text after repeated spaces/newlines are normalized to one space.
- Letters, digits, punctuation, and the remaining spaces are counted.

### Words / tokens
Word statistics use the **original tokens before stop-word removal or stemming**.

- `COVID-19`, `SARS-CoV-2`, `IL-6`, `well-known`, `patient's` → **1 word** each.
- `48.1%`, `0.05` → **1 word** each.
- Dotted forms such as `e.g.` / `i.e.` → **1 token**.
- `/` is a separator, so `activity/exercise` → **2 words**.
- An en dash/range separator also separates tokens unless it is part of the recognized token pattern.

The shared token rule is in `search/text_processing.py` → `TOKEN_PATTERN` and `tokenize()`.

### Sentences / EOS
`split_sentences()` in `search/text_processing.py` uses `.`, `!`, `?` as candidate EOS (End Of Sentence) markers, while protecting:

- decimals such as `3.14` / `0.05`;
- common abbreviations such as `Dr.`, `Fig.`, `Prof.`;
- multi-dot abbreviations such as `e.g.` / `i.e.`;
- initials such as `J. Smith`;
- closing quotation marks/brackets after sentence punctuation.

Paragraph boundaries are handled separately. The next sentence is **not required to start with an uppercase letter**, which is useful for biomedical terms such as `p53`.

## Search preprocessing

```text
Tokenization
→ Stop-word removal
→ Porter stemming
→ Inverted index
→ BM25 ranking
```

Statistics do **not** remove stop words or stem words.

## Current Abstract-only scope

The XML parser still extracts and stores full body text in `Document.raw_text`, but the active search index currently uses:

```text
Title + Abstract
```

This avoids returning an article only because a keyword appears in hidden body text.

## Restore Full Text later

Full-text code was intentionally kept rather than deleted.

1. **`search/indexer.py`** → `_index_one()`
   - Comment the current `search_text = Title + Abstract` block.
   - Uncomment the marked line: `# search_text = text`.

2. **`search/views.py`** → `document_detail_view()`
   - Uncomment the block marked `FUTURE FULL-TEXT SUPPORT`.
   - Restore the corresponding context variables.

3. **`search/templates/search/document_detail.html`**
   - Remove the `{% comment %} ... {% endcomment %}` wrapper around `FUTURE FULL TEXT DISPLAY`.

4. Rebuild the index:

```bash
docker compose exec web python manage.py build_index
```

No model migration is needed just to restore the full-text display/search scope.
