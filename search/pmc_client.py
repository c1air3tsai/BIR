import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "biomedir_student_ir"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "BioMedIR-Student-Project/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def normalize_pmcid(pmcid: str):
    value = (pmcid or "").strip().upper()
    if not value.startswith("PMC"):
        value = "PMC" + value
    if not re.fullmatch(r"PMC\d+", value):
        raise ValueError("PMCID 格式錯誤，請輸入例如 PMC8270360")
    return value


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
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError("NCBI 回傳的資料不是有效 XML") from exc
    if root.find(".//article") is None and root.tag != "article":
        raise RuntimeError("找不到 PMC 文章內容；請確認 PMCID 是否存在且可由 EFetch 取得")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pmcid}.xml"
    out_path.write_bytes(data)
    return str(out_path)


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
