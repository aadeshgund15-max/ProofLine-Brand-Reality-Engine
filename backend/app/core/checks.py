"""Deterministic brand checks (review Stage A).

Pure functions: no database, no network. Inputs are the exact fact/rule *versions*
loaded by the caller; outputs are findings plus the dependency links that the
Brand Time Machine later uses.

Semantics of the fact fields
  value_type = money   approved_value like "₹4,999"; sentences mentioning a subject term
                       are scanned for money amounts and any different amount is flagged.
  value_type = date    approved_value like "12 March 2026"; different dates in a sentence that
                       mentions a subject term are flagged. Numeric dates are read as dd/mm/yyyy.
  value_type = number  approved_value like "5000 mAh" or "42". With a unit, only numbers with
                       the same unit are compared; without a unit every plain number in the
                       sentence is compared (reported as a *possible* inconsistency only).
  value_type = text    approved_value is the canonical wording. Occurrences that differ from it
                       in casing/spacing/hyphenation are flagged, and every subject term is a
                       known wrong variant that is flagged when present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

ENGINE_VERSION = "deterministic-1.0"


# ----------------------------------------------------------------- inputs
@dataclass(frozen=True)
class FactV:
    fact_id: str
    version_id: str
    key: str
    name: str
    approved_value: str
    value_type: str
    subject_terms: tuple[str, ...] = ()
    status: str = "approved"


@dataclass(frozen=True)
class RuleV:
    rule_id: str
    version_id: str
    key: str
    rule_type: str
    description: str
    patterns: tuple[str, ...] = ()
    severity: str = "medium"
    applies_to: tuple[str, ...] = ()
    status: str = "approved"


# ---------------------------------------------------------------- outputs
@dataclass
class RawFinding:
    origin: str
    category: str
    title: str
    explanation: str
    severity: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    excerpt: Optional[str] = None
    fact_version_id: Optional[str] = None
    rule_version_id: Optional[str] = None
    verification_status: str = "not_applicable"


@dataclass(frozen=True)
class Dependency:
    kind: str  # 'violation' | 'matched' | 'applicable'
    fact_id: Optional[str] = None
    fact_version_id: Optional[str] = None
    rule_id: Optional[str] = None
    rule_version_id: Optional[str] = None


@dataclass
class CheckResult:
    findings: list[RawFinding] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    evaluated_fact_versions: list[str] = field(default_factory=list)
    evaluated_rule_versions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_CUR = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR", "rupee": "INR",
        "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}

_MONEY_PREFIX = re.compile(
    r"(?P<cur>₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)\s?(?P<num>\d[\d,]*(?:\.\d+)?)", re.I)
_MONEY_SUFFIX = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<cur>INR|USD|EUR|GBP|rupees?)\b", re.I)

_DATE_ISO = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
_DATE_DMY = re.compile(
    rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RE})\.?,?\s+(?P<y>\d{{4}})\b", re.I)
_DATE_MDY = re.compile(
    rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I)
_DATE_SLASH = re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b")

_NUMBER = re.compile(r"(?<![\w.,])(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<unit>%|[A-Za-z][A-Za-z/]*))?")


def _to_decimal(s: str) -> Optional[Decimal]:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class Found:
    start: int
    end: int
    text: str
    value: object  # normalized comparable


def find_money(text: str) -> list[Found]:
    out: list[Found] = []
    taken: list[tuple[int, int]] = []
    for rx in (_MONEY_PREFIX, _MONEY_SUFFIX):
        for m in rx.finditer(text):
            if any(m.start() < e and m.end() > s for s, e in taken):
                continue
            d = _to_decimal(m.group("num"))
            if d is None:
                continue
            cur = _CUR.get(m.group("cur").lower(), m.group("cur").upper())
            out.append(Found(m.start(), m.end(), m.group(0), (cur, d)))
            taken.append((m.start(), m.end()))
    return sorted(out, key=lambda f: f.start)


def find_dates(text: str) -> list[Found]:
    out: list[Found] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match, y: int, mo: int, d: int) -> None:
        if any(m.start() < e and m.end() > s for s, e in taken):
            return
        try:
            val = date(y, mo, d)
        except ValueError:
            return
        out.append(Found(m.start(), m.end(), m.group(0), val))
        taken.append((m.start(), m.end()))

    for m in _DATE_ISO.finditer(text):
        add(m, int(m["y"]), int(m["m"]), int(m["d"]))
    for m in _DATE_DMY.finditer(text):
        add(m, int(m["y"]), _MONTHS[m["mon"].lower()], int(m["d"]))
    for m in _DATE_MDY.finditer(text):
        add(m, int(m["y"]), _MONTHS[m["mon"].lower()], int(m["d"]))
    for m in _DATE_SLASH.finditer(text):
        add(m, int(m["y"]), int(m["m"]), int(m["d"]))
    return sorted(out, key=lambda f: f.start)


def _mask(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        for i in range(s, min(e, len(chars))):
            chars[i] = " "
    return "".join(chars)


def find_numbers(text: str) -> list[tuple[int, int, str, Decimal, str]]:
    """Plain numbers: (start, end, raw, value, unit_casefolded)."""
    out = []
    for m in _NUMBER.finditer(text):
        d = _to_decimal(m.group("num"))
        if d is None:
            continue
        out.append((m.start(), m.end(), m.group(0), d, (m.group("unit") or "").casefold()))
    return out


def sentences(text: str) -> list[tuple[int, int, str]]:
    """Split into (start, end, sentence) preserving character offsets."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        cursor = 0
        for m in re.finditer(r"(?<=[.!?])\s+", line):
            seg = line[cursor:m.start()]
            if seg.strip():
                out.append((line_start + cursor, line_start + m.start(), seg))
            cursor = m.end()
        seg = line[cursor:]
        if seg.strip():
            out.append((line_start + cursor, line_start + len(line), seg))
    return out


def term_regex(term: str) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.I)


def _mentions(sentence: str, terms: Iterable[str]) -> bool:
    return any(t.strip() and term_regex(t).search(sentence) for t in terms)


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return ("…" if s > 0 else "") + text[s:e].replace("\n", " ") + ("…" if e < len(text) else "")


def _applies(rule: RuleV, content_type: str) -> bool:
    return not rule.applies_to or content_type in rule.applies_to


# ------------------------------------------------------------ fact checks
def _check_fact(text: str, fact: FactV) -> tuple[list[RawFinding], bool]:
    """Returns (findings, matched). `matched` means the content discusses this fact's subject."""
    findings: list[RawFinding] = []
    matched = False
    vt = fact.value_type

    def mk(start: int, end: int, shown: str, category: str, why: str, sev: str) -> RawFinding:
        return RawFinding(
            origin="deterministic", category=category,
            title=f"{fact.name}: content differs from approved value",
            explanation=why, severity=sev, span_start=start, span_end=end,
            excerpt=_excerpt(text, start, end), fact_version_id=fact.version_id)

    if vt == "text":
        approved = fact.approved_value.strip()
        words = [w for w in re.split(r"[\s\-_]+", approved) if w]
        if words:
            loose = re.compile(rf"(?<!\w){r'[\s\-_]*'.join(re.escape(w) for w in words)}(?!\w)", re.I)
            for m in loose.finditer(text):
                matched = True
                if m.group(0) != approved:
                    findings.append(mk(
                        m.start(), m.end(), m.group(0), "rule_violation",
                        f"“{m.group(0)}” is written differently from the approved wording “{approved}”.",
                        "medium"))
        for term in fact.subject_terms:
            if not term.strip():
                continue
            for m in term_regex(term).finditer(text):
                matched = True
                if m.group(0) == approved:
                    continue
                if any(f.span_start == m.start() for f in findings):
                    continue
                findings.append(mk(
                    m.start(), m.end(), m.group(0), "rule_violation",
                    f"“{m.group(0)}” is a known incorrect variant; the approved wording is “{approved}”.",
                    "medium"))
        return findings, matched

    for s_start, _s_end, sent in sentences(text):
        if not _mentions(sent, fact.subject_terms):
            continue
        matched = True
        if vt == "money":
            approved = (find_money(fact.approved_value) or [None])[0]
            if approved is None:
                continue
            a_cur, a_amt = approved.value
            for f in find_money(sent):
                cur, amt = f.value
                if amt != a_amt or (a_cur and cur and cur != a_cur):
                    findings.append(mk(
                        s_start + f.start, s_start + f.end, f.text, "rule_violation",
                        f"The content states {f.text} but the approved value is {fact.approved_value}.",
                        "high"))
        elif vt == "date":
            approved = (find_dates(fact.approved_value) or [None])[0]
            if approved is None:
                continue
            for f in find_dates(sent):
                if f.value != approved.value:
                    findings.append(mk(
                        s_start + f.start, s_start + f.end, f.text, "rule_violation",
                        f"The content states {f.text} but the approved date is {fact.approved_value}.",
                        "high"))
        elif vt == "number":
            m_unit = _NUMBER.match(fact.approved_value.strip())
            if not m_unit:
                continue
            a_val = _to_decimal(m_unit.group("num"))
            a_unit = (m_unit.group("unit") or "").casefold()
            masked = _mask(sent, [(f.start, f.end) for f in find_money(sent) + find_dates(sent)])
            for (st, en, raw, val, unit) in find_numbers(masked):
                if a_unit:
                    if unit != a_unit or val == a_val:
                        continue
                    findings.append(mk(
                        s_start + st, s_start + en, raw.strip(), "rule_violation",
                        f"The content states {raw.strip()} but the approved value is {fact.approved_value}.",
                        "high"))
                else:
                    if val == a_val:
                        continue
                    findings.append(mk(
                        s_start + st, s_start + en, raw.strip(), "possible_inconsistency",
                        f"The content mentions the number {raw.strip()} near “{fact.name}”, whose approved "
                        f"value is {fact.approved_value}. This may be unrelated; please review.",
                        "low"))
    return findings, matched


# ------------------------------------------------------------ rule checks
def _check_rule(text: str, rule: RuleV) -> list[RawFinding]:
    out: list[RawFinding] = []
    pats = [p for p in rule.patterns if p.strip()]

    def mk(category: str, title: str, why: str, start=None, end=None, vstatus="not_applicable") -> RawFinding:
        return RawFinding(
            origin="deterministic", category=category, title=title, explanation=why,
            severity=rule.severity, span_start=start, span_end=end,
            excerpt=_excerpt(text, start, end) if start is not None else None,
            rule_version_id=rule.version_id, verification_status=vstatus)

    if rule.rule_type == "prohibited_phrase":
        for p in pats:
            for m in term_regex(p).finditer(text):
                out.append(mk("rule_violation", f"Prohibited wording: “{m.group(0)}”",
                              f"{rule.description} (matched “{p}”).", m.start(), m.end()))
    elif rule.rule_type == "required_term":
        if text.strip():
            for p in pats:
                if not term_regex(p).search(text):
                    out.append(mk("rule_violation", f"Required term missing: “{p}”",
                                  f"{rule.description} The term “{p}” does not appear in the content."))
    elif rule.rule_type == "approved_name":
        for p in pats:
            words = [w for w in re.split(r"[\s\-_]+", p.strip()) if w]
            if not words:
                continue
            loose = re.compile(rf"(?<!\w){r'[\s\-_]*'.join(re.escape(w) for w in words)}(?!\w)", re.I)
            for m in loose.finditer(text):
                if m.group(0) != p.strip():
                    out.append(mk("rule_violation", f"Approved name not used: “{m.group(0)}”",
                                  f"{rule.description} Use “{p.strip()}” exactly.", m.start(), m.end()))
    elif rule.rule_type == "claim_requires_evidence":
        for p in pats:
            for m in term_regex(p).finditer(text):
                out.append(mk("claim_verification", f"Claim needs supporting evidence: “{m.group(0)}”",
                              f"{rule.description} Proofline has not verified this claim; a human must "
                              f"confirm supporting evidence exists.", m.start(), m.end(),
                              vstatus="needs_human_review"))
    return out


# ------------------------------------------------------------ entry point
def run_checks(text: str, facts: Iterable[FactV], rules: Iterable[RuleV],
               content_type: str = "text") -> CheckResult:
    res = CheckResult()
    for fact in facts:
        if fact.status != "approved":
            continue
        res.evaluated_fact_versions.append(fact.version_id)
        found, matched = _check_fact(text, fact)
        res.findings.extend(found)
        if found:
            res.dependencies.append(Dependency("violation", fact.fact_id, fact.version_id))
        elif matched:
            res.dependencies.append(Dependency("matched", fact.fact_id, fact.version_id))
    for rule in rules:
        if rule.status != "approved" or not _applies(rule, content_type):
            continue
        res.evaluated_rule_versions.append(rule.version_id)
        found = _check_rule(text, rule)
        res.findings.extend(found)
        res.dependencies.append(
            Dependency("violation" if found else "applicable", rule_id=rule.rule_id,
                       rule_version_id=rule.version_id))
    return res
