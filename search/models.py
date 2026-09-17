from django.db import models


class Document(models.Model):
    title = models.CharField(max_length=500)
    source_file = models.CharField(max_length=300, unique=True)
    pmcid = models.CharField(max_length=40, blank=True, db_index=True)
    pmid = models.CharField(max_length=40, blank=True, db_index=True)
    doi = models.CharField(max_length=200, blank=True)
    journal = models.CharField(max_length=300, blank=True)
    publication_year = models.CharField(max_length=10, blank=True)
    authors = models.TextField(blank=True)
    abstract = models.TextField(blank=True)
    raw_text = models.TextField()
    char_count = models.IntegerField(default=0)
    word_count = models.IntegerField(default=0)
    sentence_count = models.IntegerField(default=0)
    avg_words_per_sentence = models.FloatField(default=0)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-indexed_at", "title"]

    def __str__(self):
        return self.title


class Term(models.Model):
    word = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.word


class Posting(models.Model):
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="postings")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="postings")
    term_freq = models.IntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["term", "document"], name="unique_term_document")
        ]
        indexes = [models.Index(fields=["term", "document"])]

    def __str__(self):
        return f"{self.term.word} -> doc#{self.document_id} (tf={self.term_freq})"
