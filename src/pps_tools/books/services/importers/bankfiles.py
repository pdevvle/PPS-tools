"""Reading bank and card statement downloads: CSV, OFX, QFX and QBO (Web Connect).

Every parser returns a :class:`Statement` of :class:`BankLine` rows with a
stable ``external_id`` so importing the same file twice adds nothing.
Amounts are signed from the account holder's side: positive is money in
(a deposit, a card refund), negative is money out.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from pps_tools.books.money import MoneyError, cents


@dataclass
class BankLine:
    date: date
    amount_cents: int
    description: str
    payee: Optional[str] = None
    memo: Optional[str] = None
    check_number: Optional[str] = None
    external_id: str = ""
    category: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class Statement:
    lines: list[BankLine]
    balance_cents: Optional[int] = None
    balance_date: Optional[date] = None
    account_hint: Optional[str] = None  # last digits of the account number, if the file says


class ParseError(ValueError):
    pass


def parse(filename: str, data: bytes, card: bool = False, csv_options: Optional[dict] = None) -> Statement:
    text = _decode(data)
    name = (filename or "").lower()
    if name.endswith((".ofx", ".qfx", ".qbo")) or "<OFX>" in text.upper()[:5000] or "OFXHEADER" in text[:500]:
        return parse_ofx(text)
    return parse_csv(text, card=card, **(csv_options or {}))


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _fingerprint(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


# -- OFX / QFX / QBO --------------------------------------------------------------------------

_OFX_TAG = re.compile(r"<(\w+)>([^<\r\n]*)")


def _ofx_date(value: str) -> date:
    digits = re.sub(r"[^0-9]", "", value or "")[:8]
    if len(digits) < 8:
        raise ParseError(f"bad OFX date {value!r}")
    return datetime.strptime(digits, "%Y%m%d").date()


def parse_ofx(text: str) -> Statement:
    """OFX 1.x (SGML, unclosed tags) and 2.x (XML) both parse here."""
    body = text[text.upper().find("<OFX>"):] if "<OFX>" in text.upper() else text
    lines: list[BankLine] = []
    for block in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", body,
                            flags=re.S | re.I):
        fields = {k.upper(): v.strip() for k, v in _OFX_TAG.findall(block)}
        try:
            when = _ofx_date(fields.get("DTPOSTED") or fields.get("DTUSER") or "")
            amount = cents(fields.get("TRNAMT", "0"))
        except (ParseError, MoneyError):
            continue
        name = _unescape(fields.get("NAME") or fields.get("PAYEE") or "")
        memo = _unescape(fields.get("MEMO") or "")
        fitid = fields.get("FITID") or _fingerprint(when, amount, name, memo)
        lines.append(BankLine(date=when, amount_cents=amount, description=(name + (" " + memo if memo and memo not in name else "")).strip(),
                              payee=name or None, memo=memo or None, check_number=fields.get("CHECKNUM") or None,
                              external_id=f"ofx:{fitid}", raw=fields))
    balance = balance_date = None
    m = re.search(r"<LEDGERBAL>(.*?)(?:</LEDGERBAL>|<AVAILBAL>|</STMTRS>|</CCSTMTRS>)", body, flags=re.S | re.I)
    if m:
        fields = {k.upper(): v.strip() for k, v in _OFX_TAG.findall(m.group(1))}
        try:
            balance = cents(fields.get("BALAMT"))
            balance_date = _ofx_date(fields.get("DTASOF", "")) if fields.get("DTASOF") else None
        except (ParseError, MoneyError):
            balance = None
    acct = re.search(r"<ACCTID>([^<\r\n]+)", body, flags=re.I)
    hint = acct.group(1).strip()[-4:] if acct else None
    if not lines and "<STMTTRN>" not in body.upper():
        raise ParseError("No transactions found in this OFX file.")
    return Statement(lines, balance, balance_date, hint)


def _unescape(text: str) -> str:
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'") \
        .replace("&quot;", '"').strip()


# -- CSV --------------------------------------------------------------------------------------

DATE_HEADERS = ("date", "posted date", "posting date", "transaction date", "trans date", "post date", "posted")
DESC_HEADERS = ("description", "payee", "name", "merchant", "details", "transaction", "memo", "narrative")
AMOUNT_HEADERS = ("amount", "transaction amount", "amt", "value")
DEBIT_HEADERS = ("debit", "withdrawal", "withdrawals", "money out", "debit amount", "charges", "payment")
CREDIT_HEADERS = ("credit", "deposit", "deposits", "money in", "credit amount", "payments/credits")
CHECK_HEADERS = ("check", "check number", "check no", "check #", "chk ref", "reference", "ref")
CATEGORY_HEADERS = ("category", "type")
BALANCE_HEADERS = ("balance", "running balance", "running bal.")


def _find(headers: list[str], names: tuple[str, ...]) -> Optional[int]:
    norm = [h.strip().lower() for h in headers]
    for want in names:
        if want in norm:
            return norm.index(want)
    for i, h in enumerate(norm):
        if any(h.startswith(w) for w in names):
            return i
    return None


def _parse_date(value: str, fmt: Optional[str] = None) -> date:
    value = (value or "").strip()
    fmts = [fmt] if fmt else ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%Y/%m/%d",
                              "%b %d, %Y", "%d %b %Y", "%d-%b-%Y", "%Y%m%d"]
    # "01/15/2026 12:00:00" and ISO timestamps: try the date part too.
    for candidate in dict.fromkeys([value, value.split(" ")[0], value.split("T")[0]]):
        for f in fmts:
            try:
                return datetime.strptime(candidate, f).date()
            except ValueError:
                continue
    raise ParseError(f"Couldn't read the date {value!r}.")


def parse_csv(text: str, card: bool = False, date_col: Optional[int] = None, desc_col: Optional[int] = None,
              amount_col: Optional[int] = None, debit_col: Optional[int] = None, credit_col: Optional[int] = None,
              date_format: Optional[str] = None, flip_sign: Optional[bool] = None,
              has_header: Optional[bool] = None) -> Statement:
    """CSV statements. Columns are detected from the header row; pass column
    indexes to override. Card exports often list charges as positive — those
    are flipped when ``card`` is set (or ``flip_sign`` forces it)."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in r)]
    if not rows:
        raise ParseError("The file is empty.")
    headers = rows[0]
    if has_header is None:
        has_header = not any(re.search(r"\d{1,4}[/-]\d{1,2}[/-]\d{1,4}", c) for c in headers) and any(
            c.strip().lower() in DATE_HEADERS + DESC_HEADERS + AMOUNT_HEADERS + DEBIT_HEADERS for c in headers)
    data_rows = rows[1:] if has_header else rows
    if has_header:
        date_col = date_col if date_col is not None else _find(headers, DATE_HEADERS)
        desc_col = desc_col if desc_col is not None else _find(headers, DESC_HEADERS)
        amount_col = amount_col if amount_col is not None else _find(headers, AMOUNT_HEADERS)
        if amount_col is None:
            debit_col = debit_col if debit_col is not None else _find(headers, DEBIT_HEADERS)
            credit_col = credit_col if credit_col is not None else _find(headers, CREDIT_HEADERS)
        check_col = _find(headers, CHECK_HEADERS)
        cat_col = _find(headers, CATEGORY_HEADERS)
        memo_col = _find(headers, ("memo", "notes")) if desc_col != _find(headers, ("memo",)) else None
        bal_col = _find(headers, BALANCE_HEADERS)
    else:
        # Headerless (Wells Fargo style): date, amount, *, *, description
        date_col = 0 if date_col is None else date_col
        amount_col = 1 if amount_col is None and debit_col is None else amount_col
        desc_col = (len(headers) - 1) if desc_col is None else desc_col
        check_col = cat_col = memo_col = bal_col = None
    if date_col is None or (amount_col is None and debit_col is None and credit_col is None):
        raise ParseError("Couldn't find the date and amount columns. Choose them in the import options.")
    lines: list[BankLine] = []
    seen: dict[str, int] = {}
    last_balance = last_date = None
    for r in data_rows:
        def cell(i):
            return r[i].strip() if i is not None and i < len(r) else ""
        if not cell(date_col):
            continue
        try:
            when = _parse_date(cell(date_col), date_format)
        except ParseError:
            continue
        try:
            if amount_col is not None:
                amount = cents(cell(amount_col))
            else:
                out = cents(cell(debit_col)) if cell(debit_col) else 0
                inn = cents(cell(credit_col)) if cell(credit_col) else 0
                amount = abs(inn) - abs(out)
        except MoneyError:
            continue
        if (flip_sign if flip_sign is not None else (card and amount_col is not None and _charges_positive(
                data_rows, amount_col))):
            amount = -amount
        desc = cell(desc_col) or cell(memo_col) or "(no description)"
        base = _fingerprint(when, amount, desc.lower())
        n = seen.get(base, 0)
        seen[base] = n + 1
        line = BankLine(date=when, amount_cents=amount, description=desc, payee=None,
                        memo=cell(memo_col) or None, check_number=cell(check_col) or None,
                        external_id=f"csv:{base}:{n}", category=cell(cat_col) or None,
                        raw={headers[i] if has_header and i < len(headers) else str(i): v for i, v in enumerate(r)})
        lines.append(line)
        if bal_col is not None and cell(bal_col):
            try:
                if last_date is None or when >= last_date:
                    last_balance, last_date = cents(cell(bal_col)), when
            except MoneyError:
                pass
    if not lines:
        raise ParseError("No transactions could be read from this file.")
    return Statement(lines, last_balance, last_date)


def _charges_positive(rows: list[list[str]], col: int) -> bool:
    """Card CSVs: when most amounts are positive, charges are positive."""
    vals = []
    for r in rows[:200]:
        if col < len(r):
            try:
                vals.append(cents(r[col]))
            except MoneyError:
                continue
    if not vals:
        return False
    return sum(1 for v in vals if v > 0) > len(vals) / 2


def clean_payee(description: str) -> str:
    """'SQ *BLUE BOTTLE COFFEE 123-456 CA' -> 'Blue Bottle Coffee' (best effort, for matching)."""
    text = description.upper()
    text = re.sub(r"^(POS|ACH|DEBIT|CREDIT|CHECKCARD|PURCHASE|RECURRING|ONLINE|PREAUTHORIZED|VISA|MC|DDA)\s+", "", text)
    text = re.sub(r"^(SQ|TST|SP|PY|PP|PAYPAL|IN|DD)\s*\*\s*", "", text)
    text = re.sub(r"\b(DES:|ID:|INDN:|CO ID:|WEB|PPD|CCD).*$", "", text)
    text = re.sub(r"#?\d{3,}.*$", "", text)
    text = re.sub(r"\s+[A-Z]{2}\s*$", "", text)
    text = re.sub(r"[^A-Z0-9&' ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title() if text else description.strip()
