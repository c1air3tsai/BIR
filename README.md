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
- Article collection defaults to **Newest added**, with optional Title A–Z / Z–A / Oldest sorting, publication-year filtering, Abstract statistics, and deletion. The collection list does not display Abstract text; open the article to read the segmented Abstract.
- Articles and Search Results both show 10 records per page. Both support publication-year filtering using only years that actually exist in the local collection. Abstract statistics are displayed as **Sentences → Words → Characters**; Search Results additionally show the Abstract snippet and Abstract keyword matches.
- Upload PubMed/PMC XML or fetch one/multiple PMID/PMCID values directly from NCBI.
- Duplicate detection by PMCID, PMID, DOI, source filename, then title/year.
- Article detail page shows metadata, Title statistics, and a sentence-segmented Abstract.

## Text counting rules

### Characters
- Count visible text after repeated spaces/newlines are normalized to one space.
- Letters, digits, punctuation, and the remaining spaces are counted.

### Words / tokens
Word statistics use the **original tokens before stop-word removal or stemming**.

- ASCII letters/digits (`A-Z`, `a-z`, `0-9`) are valid token characters.
- ASCII whitespace (space/tab/newline) separates words and is never a word itself.
- ASCII punctuation such as commas, semicolons, brackets, and `/` acts as a separator unless specifically protected by the token rule.
- `COVID-19`, `SARS-CoV-2`, `IL-6`, `well-known`, `patient's` → **1 word** each because internal `-` / `'` are retained.
- `48.1%`, `0.05` → **1 word** each; a decimal point inside a number is retained.
- Dotted forms such as `e.g.` / `i.e.` → **1 token**.
- `/` is a separator, so `activity/exercise` → **2 words**; `/` itself is not a word.
- An en dash/range separator also separates tokens unless it is part of the recognized token pattern.
- Non-ASCII Unicode letters are retained rather than discarded, so biomedical terms containing Greek letters such as `α` / `β` can still form tokens.

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


## Collection, filters, preview and pagination

- **Articles**: 10 articles per page. The default order is **Newest added**; users can switch to Title A–Z, Title Z–A, or Oldest added.
- The old A/B/C/D alphabet filter is removed. A **Year** dropdown shows only publication years that exist in the current collection.
- The Articles list shows Abstract statistics but intentionally does **not** show Abstract text; open an article to read its sentence-segmented Abstract.
- **Search Results**: 10 results per page; each result shows an Abstract snippet, Abstract statistics, and Abstract keyword matches. The same Year dropdown restricts retrieval to that publication year.
- Abstract statistics order is **Sentences → Words → Characters**.
- Retrieval behavior is otherwise unchanged: queries use the existing Porter stemming + inverted-index/BM25 logic. **No prefix/partial-word search is enabled.**
- When full-text display is restored later, retain the Abstract statistics and add full-article statistics rather than replacing the Abstract information.

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

## PMID / PMCID fetch

The Upload page accepts both identifiers in the same box:

- `PMC12503546` → fetched from **PubMed Central** as PMC/JATS XML.
- `42724776` or `PMID42724776` → fetched from **PubMed** as PubMed XML.
- Plain numeric IDs are treated as **PMID**; use the `PMC` prefix for a PMCID.
- Multiple IDs can be separated by spaces, commas, semicolons, or new lines.
- PubMed XML is enough for the current Abstract-only stage even when no PMC full text exists.

