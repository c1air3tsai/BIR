## Latest collection features

- Upload local PMC/JATS XML files with duplicate detection.
- Fetch one or multiple PMCIDs from PubMed Central, then upload individually or all at once.
- Duplicate articles are detected primarily by PMCID, then DOI, filename, and title/year fallback.
- Delete an article from the collection; its postings and orphan index terms are removed as well.
- Successful uploads offer **View Articles** or **Continue Uploading**.

# Biomedical Literature Search

A clean Django + Python full-text retrieval project for PubMed Central XML articles.

The web interface is intentionally simple: **Search**, **Articles**, and **Upload**. The IR algorithms run in the backend without extra index/system pages in the UI.

## Main functions

- PubMed Central / JATS XML parsing
- XML upload from the web interface
- Fetch article XML from PubMed Central by PMCID, preview the fetched XML on the same Upload page, then upload it explicitly
- Download the stored XML from an article detail page
- Tokenization and lowercasing
- Stop-word removal
- Porter stemming
- Inverted index using `Term` and `Posting`
- BM25 ranking for normal keyword searches
- Stop-word-only fallback so queries such as `on the` still return matching documents
- Search keyword highlighting in titles, abstracts/snippets, and article detail pages
- Full article text rendered sentence-by-sentence using the rule-based EOS detector
- Upload-success confirmation dialog that continues to the Articles overview
- Rule-based sentence / EOS detection
- Document statistics: characters, words, sentences, average sentence length
- Article overview with A–Z / Z–A / newest / oldest sorting and A–Z filtering

## Project structure

```text
biomedir_project/
├─ biomedir/                    # Django settings and root URLs
├─ search/
│  ├─ text_processing.py        # tokenization, stop words, Porter stemmer, EOS, BM25
│  ├─ indexer.py                # XML parser + inverted index builder
│  ├─ pmc_client.py             # NCBI ESearch / EFetch client
│  ├─ forms.py                  # XML upload and PMCID forms
│  ├─ models.py                 # Document / Term / Posting
│  ├─ views.py                  # search, articles, upload, detail, XML download
│  ├─ management/commands/
│  │  ├─ build_index.py
│  │  └─ download_pmc.py
│  ├─ templates/search/
│  └─ static/search/site.css
├─ data/corpus/                 # local XML collection
├─ Dockerfile
├─ docker-compose.yml
└─ requirements.txt
```

## Run with Docker

From the project directory:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000/
```

The container automatically runs Django migrations. If the database is empty, it also loads the XML files in `data/corpus/`.

## Rebuild the local collection

After manually adding or changing XML files in `data/corpus/`:

```bash
docker compose exec web python manage.py build_index
```

## Fetch PMC XML from the command line

By PMCID:

```bash
docker compose exec web python manage.py download_pmc --pmcid PMC8270360
```

Or search PMC and download several articles:

```bash
docker compose exec web python manage.py download_pmc --query "cancer immunotherapy" --limit 5
```

## Retrieval logic

For a normal keyword query:

```text
Query
  -> tokenize
  -> remove stop words
  -> Porter stemming
  -> inverted-index lookup
  -> BM25 ranking
  -> results
```

If a query contains only stop words, for example `on the`, stop-word removal would normally leave no indexed query terms. To keep the search usable, the system performs an exact token fallback over the local documents and still returns matching articles.

The visible website does not expose a Keyword Index or System page; the index is built and used internally.


## Current UI features

- Clean Search / Articles / Upload navigation
- Query highlighting in titles, snippets, abstracts, and sentence-segmented full text
- Previous / Next keyword match navigation inside full articles
- Paginated search results and article collection
- Article statistics: characters, words, sentences, unique words, paragraphs, and average sentence length
- XML upload plus staged PubMed Central XML fetch/upload workflow
