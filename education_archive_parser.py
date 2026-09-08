from __future__ import annotations

import base64
import html
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://xn--2z1b40gs9nlqcf0n.kr"
LIST_URL = BASE_URL + "/front/archive/archiveMainList.do"
DEFAULT_TARGETS = ("초등", "중등", "고등")
OFFICIAL_TARGETS = (
    "유아", "초등", "중등", "고등", "학부모", "성인", "고령층", "장애학생",
    "발달장애(초등)", "발달장애(중고등)", "발달장애(성인)", "군인", "교사",
    "전체 대상", "기소유예자",
)
USER_AGENT = "AI-OFF-Education-RAG/1.0 (+https://aioff-ai.duckdns.org/)"

_EXT_RE = re.compile(
    r"\.(pdf|zip|hwp|hwpx|doc|docx|ppt|pptx|xls|xlsx|txt|mp4)(?:$|\?)",
    re.I,
)
_FILEDOWN_RE = re.compile(
    r"fileDown\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*['\"]?([^'\"\),]*)['\"]?)?\s*\)",
    re.I,
)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def target_labels(value: str) -> tuple[str, ...]:
    """Return the archive's own target labels without substring inference.

    A regular elementary student must not accidentally match a distinct archive
    category such as '발달장애(초등)'. Multi-target cards such as
    '초등 / 중등 / 고등' are split into their explicit labels.
    """
    raw = norm(value)
    if not raw:
        return ()
    labels = []
    for item in re.split(r"\s*(?:/|,|·|ㆍ)\s*", raw):
        label = norm(item)
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def lines_of(node) -> list[str]:
    return [norm(x) for x in node.get_text("\n", strip=True).splitlines() if norm(x)]


def value_between(lines: list[str], label: str, next_labels: tuple[str, ...]) -> str:
    try:
        i = lines.index(label)
    except ValueError:
        return ""
    values: list[str] = []
    for item in lines[i + 1 :]:
        if item in next_labels or any(item.startswith(x) for x in next_labels):
            break
        values.append(item)
    return norm(" / ".join(values))


def value_from_text(text: str, label: str, next_label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*(.*?)\s*{re.escape(next_label)}", text, re.S)
    return norm(match.group(1)) if match else ""


def infer_target_from_title(title: str) -> tuple[str, str]:
    title = norm(title)
    if re.search(r"(?:중고등|중·고등|중고등학교|중고등용)", title):
        return "중등 / 고등", "title"
    if re.search(r"(?:초등학교|초등용|\[초등\]|\(초등\))", title):
        return "초등", "title"
    if re.search(r"(?:중학교|중등용|\[중등\]|\(중등\))", title):
        return "중등", "title"
    if re.search(r"(?:고등학교|고등용|\[고등\]|\(고등\))", title):
        return "고등", "title"
    return "", ""


def _is_single_material_container(node) -> bool:
    lines = lines_of(node)
    return (
        lines.count("대상") == 1
        and lines.count("제작년도") == 1
        and lines.count("자료유형") == 1
        and lines.count("주제") == 1
    )


def material_containers(soup: BeautifulSoup):
    seen: set[int] = set()
    containers = []

    for img in soup.find_all("img", alt=True):
        if not norm(img.get("alt") or ""):
            continue
        node = img.parent
        best = None
        for _ in range(28):
            if node is None or getattr(node, "name", None) in ("html", "body"):
                break
            if _is_single_material_container(node):
                best = node
                break
            node = node.parent
        if best is not None and id(best) not in seen:
            seen.add(id(best))
            containers.append(best)

    if containers:
        return containers

    label_re = re.compile(r"^(?:대상|제작년도|자료유형|주제)$")
    for text_node in soup.find_all(string=lambda s: bool(s and label_re.search(norm(str(s))))):
        node = text_node.parent
        best = None
        for _ in range(28):
            if node is None or getattr(node, "name", None) in ("html", "body"):
                break
            if _is_single_material_container(node):
                best = node
                break
            node = node.parent
        if best is not None and id(best) not in seen:
            seen.add(id(best))
            containers.append(best)
    return containers


def resolve_download_action(node) -> tuple[str, str]:
    href = norm(node.get("href") or "")
    onclick = norm(node.get("onclick") or "")
    data_url = norm(
        node.get("data-url")
        or node.get("data-href")
        or node.get("data-download-url")
        or ""
    )
    raw = onclick or data_url or href

    match = _FILEDOWN_RE.search(onclick)
    if match:
        token = norm(match.group(1))
        file_sn = norm(match.group(2) or "0") or "0"
        decoded = token
        if not decoded.startswith("FILE_"):
            try:
                decoded = base64.b64decode(token).decode("utf-8")
            except Exception:
                return "", raw
        atch_file_id = decoded.split(":::", 1)[0].strip()
        if not re.fullmatch(r"FILE_[A-Za-z0-9_]+", atch_file_id):
            return "", raw
        query = urlencode({"atchFileId": atch_file_id, "fileSn": file_sn})
        return f"{BASE_URL}/cmm/fms/FileDown.do?{query}", raw

    for candidate in (data_url, href):
        if not candidate or candidate == "#" or candidate.lower().startswith("javascript:"):
            continue
        if (
            any(k in candidate.lower() for k in ("download", "filedown", "file.do", "attach", "atch"))
            or _EXT_RE.search(candidate)
        ):
            return urljoin(BASE_URL, candidate), raw
    return "", raw


def parse_card(card, page_index: int) -> dict:
    lines = lines_of(card)
    if not lines:
        return {}

    full_text = norm(card.get_text(" ", strip=True))
    if not all(label in full_text for label in ("대상", "제작년도", "자료유형", "주제")):
        return {}

    img = card.find("img", alt=True)
    title = norm(img.get("alt") if img else "")
    if not title:
        try:
            target_idx = lines.index("대상")
        except ValueError:
            target_idx = len(lines)
        candidates = [x for x in lines[:target_idx] if x not in ("리스트형", "갤러리형")]
        title = candidates[-1] if candidates else ""

    target_raw = value_between(lines, "대상", ("제작년도",)) or value_from_text(full_text, "대상", "제작년도")
    year = value_between(lines, "제작년도", ("자료유형",)) or value_from_text(full_text, "제작년도", "자료유형")
    material_type = value_between(lines, "자료유형", ("주제",)) or value_from_text(full_text, "자료유형", "주제")
    topics_text = value_between(lines, "주제", ("조회수", "자세히보기", "다운로드"))
    if not topics_text:
        match = re.search(r"주제\s*(.*?)\s*(?:조회수|자세히보기|다운로드)", full_text, re.S)
        topics_text = norm(match.group(1)) if match else ""
    topics = re.findall(r"#[^\s#/]+", topics_text)

    if not title or not year:
        return {}

    inferred_target, target_basis = ("", "")
    if not target_raw:
        inferred_target, target_basis = infer_target_from_title(title)
    target = target_raw or inferred_target

    detail_url = ""
    attachments = []
    for node in card.find_all(["a", "button"]):
        text = norm(node.get_text(" ", strip=True))
        href = norm(node.get("href") or "")
        onclick = norm(node.get("onclick") or "")
        combined = " ".join((text, href, onclick)).lower()

        if node.name == "a" and not detail_url and (
            "자세히보기" in text or ("archive" in combined and ("view" in combined or "detail" in combined))
        ):
            if href and not href.lower().startswith("javascript:") and href != "#":
                detail_url = urljoin(BASE_URL, href)

        if _EXT_RE.search(text) or "filedown(" in combined or any(k in combined for k in ("download", "filedown")):
            download_url, raw = resolve_download_action(node)
            filename = text
            if not filename or not _EXT_RE.search(filename):
                parent_text = norm(node.parent.get_text(" ", strip=True)) if node.parent else ""
                match = re.search(
                    r"([^/\\]+\.(?:pdf|zip|hwp|hwpx|docx?|pptx?|xlsx?|txt|mp4))",
                    parent_text,
                    re.I,
                )
                if match:
                    filename = match.group(1)
            if filename and _EXT_RE.search(filename):
                attachments.append(
                    {"filename": filename, "download_url": download_url, "action_raw": raw}
                )

    for filename in [x for x in lines if _EXT_RE.search(x)]:
        if not any(item["filename"] == filename for item in attachments):
            attachments.append({"filename": filename, "download_url": "", "action_raw": ""})

    return {
        "title": title,
        "target": target,
        "target_raw": target_raw,
        "target_inferred": bool(inferred_target),
        "target_evidence": title if target_basis == "title" else "",
        "year": year,
        "material_type": material_type,
        "topics": topics,
        "source_url": detail_url or f"{LIST_URL}?pageIndex={page_index}",
        "list_page": page_index,
        "attachments": attachments,
    }


def school_materials(rows: list[dict], targets: tuple[str, ...]) -> list[dict]:
    wanted = set(targets)
    return [row for row in rows if wanted.intersection(target_labels(row.get("target", "")))]


def safe_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value).strip(" .")
    return value[:180] or "attachment"
