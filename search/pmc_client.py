import re
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "biomedir_student_ir"


def _get(url, timeout=30):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BioMedIR-Student-Project/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def normalize_pmcid(pmcid: str):
    """Normalize an explicit PMC identifier."""
    value = (pmcid or "").strip().upper()
    if not value.startswith("PMC"):
        value = "PMC" + value
    if not re.fullmatch(r"PMC\d+", value):
        raise ValueError("Invalid PMCID. Example: PMC8270360")
    return value


def normalize_identifier(identifier: str):
    """
    Return (kind, normalized_id) for a PMID or PMCID.

    Rules:
    - PMC1234567 -> ("pmc", "PMC1234567")
    - PMID:42724776 / PMID42724776 -> ("pubmed", "42724776")
    - 42724776 -> ("pubmed", "42724776")

    Bare digits are treated as PMID. A PMCID should include the PMC prefix.
    """
    value = (identifier or "").strip().upper()
    value = re.sub(r"\s+", "", value)

    if re.fullmatch(r"PMC\d+", value):
        return "pmc", value

    pmid_match = re.fullmatch(r"PMID:?([0-9]+)", value)
    if pmid_match:
        return "pubmed", pmid_match.group(1)

    if re.fullmatch(r"\d+", value):
        return "pubmed", value

    raise ValueError(
        "Invalid identifier. Enter a PMID such as 42724776 or a PMCID such as PMC12503546."
    )


def _validate_pmc_xml(data: bytes):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError("NCBI returned invalid XML") from exc
    if root.find(".//article") is None and str(root.tag).split("}")[-1] != "article":
        raise RuntimeError("PMC article XML was not found for this PMCID")


def _validate_pubmed_xml(data: bytes):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError("NCBI returned invalid XML") from exc
    has_article = any(str(node.tag).split("}")[-1] == "PubmedArticle" for node in root.iter())
    if not has_article:
        raise RuntimeError("PubMed article XML was not found for this PMID")


def download_pmc_xml(pmcid: str, output_dir: str, email: str = "student@example.com"):
    pmcid = normalize_pmcid(pmcid)
    params = urllib.parse.urlencode({
        "db": "pmc",
        "id": pmcid,
        "rettype": "xml",
        "retmode": "xml",
        "tool": TOOL,
        "email": email,
    })
    data = _get(f"{EUTILS}/efetch.fcgi?{params}")
    _validate_pmc_xml(data)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pmcid}.xml"
    out_path.write_bytes(data)
    return str(out_path)


def download_pubmed_xml(pmid: str, output_dir: str, email: str = "student@example.com"):
    """Download PubMed XML for a PMID. This is sufficient for Title/Abstract metadata."""
    kind, normalized = normalize_identifier(pmid)
    if kind != "pubmed":
        raise ValueError("A PMID is required")

    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": normalized,
        "retmode": "xml",
        "tool": TOOL,
        "email": email,
    })
    data = _get(f"{EUTILS}/efetch.fcgi?{params}")
    _validate_pubmed_xml(data)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"PMID{normalized}.xml"
    out_path.write_bytes(data)
    return str(out_path)


def download_article_xml(identifier: str, output_dir: str, email: str = "student@example.com"):
    """Fetch XML using either a PMCID or PMID."""
    kind, normalized = normalize_identifier(identifier)
    if kind == "pmc":
        return download_pmc_xml(normalized, output_dir, email=email)
    return download_pubmed_xml(normalized, output_dir, email=email)


def search_pmc(query: str, retmax: int = 5, email: str = "student@example.com"):
    params = urllib.parse.urlencode({
        "db": "pmc",
        "term": query,
        "retmode": "json",
        "retmax": max(1, min(int(retmax), 20)),
        "tool": TOOL,
        "email": email,
    })
    import json
    data = json.loads(_get(f"{EUTILS}/esearch.fcgi?{params}").decode("utf-8"))
    return [f"PMC{x}" for x in data.get("esearchresult", {}).get("idlist", [])]
