"""IDSP Kerala - Automated PDF Download, Extraction, and Database Ingestion

Downloads new IDSP daily reports from https://dhs.kerala.gov.in/en/idsp-2/,
extracts structured data, validates it, and loads into SQLite + ChromaDB.

Usage:
    python ingest.py              # Fetch all new reports not yet in the DB
    python ingest.py --days 7     # Fetch only the last 7 days
    python ingest.py --date 2026-09-02  # Fetch a specific date
"""

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

PDF_FOLDER = PROJECT_ROOT / "data" / "raw" / "daily"
PROCESSED_FOLDER = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROJECT_ROOT / "notebooks" / "data" / "idsp_kerala.db"
CHROMA_PATH = PROJECT_ROOT / "data" / "chroma_db"

PDF_FOLDER.mkdir(parents=True, exist_ok=True)
PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

IDSP_URL = "https://dhs.kerala.gov.in/en/idsp-2/"
BASE_URL = "https://dhs.kerala.gov.in"

DISTRICTS = {
    "TVM": "Thiruvananthapuram", "KLM": "Kollam", "PTA": "Pathanamthitta",
    "IDK": "Idukki", "KTM": "Kottayam", "ALP": "Alappuzha",
    "EKM": "Ernakulam", "TSR": "Thrissur", "PKD": "Palakkad",
    "MPM": "Malappuram", "KKD": "Kozhikode", "WYD": "Wayanad",
    "KNR": "Kannur", "KSD": "Kasaragod",
}

DISTRICT_COLUMNS = [
    "row_number", "district_code",
    "fever_op", "fever_ip",
    "chikungunya_suspected", "chikungunya_confirmed", "chikungunya_deaths",
    "dengue_suspected", "dengue_confirmed", "dengue_deaths",
    "leptospirosis_suspected", "leptospirosis_confirmed", "leptospirosis_deaths",
    "add_confirmed", "chickenpox_confirmed", "hepatitis_a_confirmed",
    "cholera_suspected_cases", "cholera_suspected_deaths",
    "cholera_confirmed_cases", "cholera_confirmed_deaths",
    "aes_confirmed", "je_confirmed",
    "malaria_pv_imported", "malaria_pv_indigenous",
    "malaria_pf_imported", "malaria_pf_indigenous",
    "malaria_mixed_imported", "malaria_mixed_indigenous", "malaria_deaths",
    "scrub_typhus_confirmed", "influenza_confirmed",
]

COLUMN_MEANINGS = {
    "fever_op": ("Fever", "outpatient", None),
    "fever_ip": ("Fever", "inpatient", None),
    "chikungunya_suspected": ("Chikungunya", "suspected", None),
    "chikungunya_confirmed": ("Chikungunya", "confirmed", None),
    "chikungunya_deaths": ("Chikungunya", "deaths", None),
    "dengue_suspected": ("Dengue", "suspected", None),
    "dengue_confirmed": ("Dengue", "confirmed", None),
    "dengue_deaths": ("Dengue", "deaths", None),
    "leptospirosis_suspected": ("Leptospirosis", "suspected", None),
    "leptospirosis_confirmed": ("Leptospirosis", "confirmed", None),
    "leptospirosis_deaths": ("Leptospirosis", "deaths", None),
    "add_confirmed": ("Acute Diarrhoeal Disease", "confirmed", None),
    "chickenpox_confirmed": ("Chickenpox", "confirmed", None),
    "hepatitis_a_confirmed": ("Hepatitis A", "confirmed", None),
    "cholera_suspected_cases": ("Cholera", "suspected", None),
    "cholera_suspected_deaths": ("Cholera", "suspected_deaths", None),
    "cholera_confirmed_cases": ("Cholera", "confirmed", None),
    "cholera_confirmed_deaths": ("Cholera", "deaths", None),
    "aes_confirmed": ("Acute Encephalitis Syndrome", "confirmed", None),
    "je_confirmed": ("Japanese Encephalitis", "confirmed", None),
    "malaria_pv_imported": ("Malaria", "confirmed", "PV imported"),
    "malaria_pv_indigenous": ("Malaria", "confirmed", "PV indigenous"),
    "malaria_pf_imported": ("Malaria", "confirmed", "PF imported"),
    "malaria_pf_indigenous": ("Malaria", "confirmed", "PF indigenous"),
    "malaria_mixed_imported": ("Malaria", "confirmed", "Mixed imported"),
    "malaria_mixed_indigenous": ("Malaria", "confirmed", "Mixed indigenous"),
    "malaria_deaths": ("Malaria", "deaths", None),
    "scrub_typhus_confirmed": ("Scrub Typhus", "confirmed", None),
    "influenza_confirmed": ("Influenza", "confirmed", None),
}

STATE_VALUE_COLUMNS = [
    "daily_suspected_cases", "daily_suspected_deaths",
    "daily_confirmed", "daily_deaths",
    "month_suspected_cases", "month_suspected_deaths",
    "month_confirmed", "month_deaths",
    "cumulative_suspected_cases", "cumulative_suspected_deaths",
    "cumulative_confirmed", "cumulative_deaths",
]

DISEASE_ALIASES_STATE = {
    "Dengue Fever": "Dengue", "Con JE": "Japanese Encephalitis",
    "AES": "Acute Encephalitis Syndrome", "Hepatitis-A": "Hepatitis A",
    "Hepatitis-E": "Hepatitis E", "ADD": "Acute Diarrhoeal Disease",
    "Chicken Pox": "Chickenpox", "M Pox": "Mpox",
    "Amebic Meningoencephalitis": "Amoebic Meningoencephalitis",
}

DISEASE_ALIASES_LOCALITY = {
    "Lepto": "Leptospirosis", "CG": "Chikungunya",
    "Chicken Pox": "Chickenpox", "Hep A": "Hepatitis A",
    "H1N1": "Influenza A (H1N1)",
    "Amoebic Meningo Encephalitis": "Amoebic Meningoencephalitis",
}

SUBTYPE_ALIASES = {"Ind.": "indigenous", "Imp.": "imported"}
SEX_ALIASES = {"M": "male", "MALE": "male", "F": "female", "FEMALE": "female"}

TABLE_SETTINGS = {
    "vertical_strategy": "lines", "horizontal_strategy": "lines",
    "intersection_tolerance": 5, "snap_tolerance": 3, "join_tolerance": 3,
}

DEATH_PATTERN = re.compile(
    r"^(?:(?P<district>[A-Z]{3}):\s*)?"
    r"(?P<disease>.+?)\s+Death:\s*"
    r"(?P<age>\d+)\s*/\s*(?P<sex>[^,]+),\s*"
    r"(?P<locality>.+?),\s*DOD\s*[:;]?\s*-?\s*"
    r"(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{4})\s*$",
    re.IGNORECASE
)


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def to_count(value):
    text = clean(value).replace(",", "")
    if text in ("-", ""):
        return 0
    if text.isdigit():
        return int(text)
    raise ValueError(f"Invalid number: {value!r}")


def to_state_count(value):
    text = clean(value).replace(",", "")
    if text == "-":
        return 0
    if text == "":
        return pd.NA
    if text.isdigit():
        return int(text)
    raise ValueError(f"Invalid state count: {value!r}")


# ---------------------------------------------------------------------------
# 1. SCRAPING
# ---------------------------------------------------------------------------

def sql_val(v):
    """Convert pandas NA/NaN to None for SQLite binding."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def get_available_dates():
    """Scrape the IDSP listing page for all available report dates and their page URLs."""
    print("Fetching IDSP listing page...")
    resp = requests.get(IDSP_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    date_map = {}
    for link in soup.select("article a"):
        href = link.get("href", "")
        if "/wp-content/" in href:
            continue
        text = link.get_text(strip=True)
        match = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
        if match:
            d, m, y = match.groups()
            try:
                report_date = date(int(y), int(m), int(d))
                full_href = href if href.startswith("http") else BASE_URL + href
                date_map[report_date] = full_href
            except ValueError:
                continue
    return date_map


def get_pdf_url_from_page(page_url: str, report_date: date) -> str:
    """Get the PDF download URL by visiting the actual report page."""
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for link in soup.select("a[href*='wp-content/uploads']"):
        href = link.get("href", "")
        if href.endswith(".pdf"):
            if not href.startswith("http"):
                href = BASE_URL + href
            return href

    y = report_date.strftime("%Y")
    m = report_date.strftime("%m")
    date_str = report_date.strftime("%d.%m.%Y")
    return f"{BASE_URL}/wp-content/uploads/{y}/{m}/IDSP-Daily-Report-{date_str}.pdf"


def download_pdf(report_date: date, page_url: str = None) -> Path:
    """Download a PDF for the given date. Returns the local path."""
    date_str = report_date.strftime("%d.%m.%Y")
    filename = f"IDSP-Daily-Report-{date_str}.pdf"
    local_path = PDF_FOLDER / filename

    if local_path.exists():
        print(f"  PDF already exists: {filename}")
        return local_path

    if page_url:
        pdf_url = get_pdf_url_from_page(page_url, report_date)
    else:
        y = report_date.strftime("%Y")
        m = report_date.strftime("%m")
        pdf_url = f"{BASE_URL}/wp-content/uploads/{y}/{m}/IDSP-Daily-Report-{date_str}.pdf"
    print(f"  Downloading: {pdf_url}")
    resp = requests.get(pdf_url, timeout=60)
    resp.raise_for_status()

    local_path.write_bytes(resp.content)
    print(f"  Saved: {filename} ({len(resp.content) / 1024:.0f} KB)")
    return local_path


# ---------------------------------------------------------------------------
# 2. EXTRACTION (Notebooks 01-03 logic)
# ---------------------------------------------------------------------------

def extract_report_date_from_table(table):
    header_text = " ".join(clean(cell) for row in table[:3] for cell in row)
    match = re.search(r"\b(\d{2})[/.-](\d{2})[/.-](\d{2,4})\b", header_text)
    if not match:
        raise ValueError("Report date not found in table header.")
    d, m, y = match.groups()
    if len(y) == 2:
        y = "20" + y
    return date(int(y), int(m), int(d)).isoformat()


def extract_district_table(pdf_path: Path):
    """Extract district table from page 2 (Notebook 01 logic)."""
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) < 2:
            raise ValueError("PDF missing page 2.")
        tables = pdf.pages[1].extract_tables(TABLE_SETTINGS)

    if not tables:
        raise ValueError("No table on page 2.")
    table = max(tables, key=len)
    report_date = extract_report_date_from_table(table)

    valid_codes = set(DISTRICTS) | {"TOT"}
    rows = [r for r in table if len(r) == len(DISTRICT_COLUMNS) and clean(r[1]).upper() in valid_codes]
    df = pd.DataFrame(rows, columns=DISTRICT_COLUMNS)
    df["district_code"] = df["district_code"].map(clean).str.upper()

    if len(df) != 15:
        raise ValueError(f"Expected 15 rows (14 districts + TOT), got {len(df)}")

    for col in DISTRICT_COLUMNS[2:]:
        df[col] = df[col].map(to_count)

    district_df = df[df["district_code"] != "TOT"].copy()
    district_df = district_df.drop(columns="row_number")
    district_df.insert(1, "district_name", district_df["district_code"].map(DISTRICTS))

    return report_date, district_df


def extract_state_analysis(pdf_path: Path):
    """Extract statewide analysis from page 3 (Notebook 02 logic)."""
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) < 3:
            raise ValueError("PDF missing page 3.")
        tables = pdf.pages[2].extract_tables(TABLE_SETTINGS)

    if not tables:
        raise ValueError("No table on page 3.")
    table = max(tables, key=len)
    report_date = extract_report_date_from_table(table)

    records = []
    current_serial, current_disease = None, None
    for row in table[3:]:
        if len(row) != 15:
            continue
        serial_text = clean(row[0])
        disease_text = clean(row[1])
        subtype_text = clean(row[2])

        if serial_text.isdigit():
            current_serial = int(serial_text)
            current_disease = disease_text
        elif serial_text == "" and disease_text == "" and subtype_text in {"Ind.", "Imp."} and current_disease:
            pass
        else:
            continue

        record = {"serial_number": current_serial, "disease_raw": current_disease, "subtype_raw": subtype_text}
        for col, val in zip(STATE_VALUE_COLUMNS, row[3:15]):
            record[col] = to_state_count(val)
        records.append(record)

    state_df = pd.DataFrame(records)
    state_df["disease"] = state_df["disease_raw"].map(lambda d: DISEASE_ALIASES_STATE.get(d, d))
    state_df["subtype"] = state_df["subtype_raw"].map(lambda s: SUBTYPE_ALIASES.get(s, None) if s else None)
    for col in STATE_VALUE_COLUMNS:
        state_df[col] = state_df[col].astype("Int64")

    return report_date, state_df


def extract_localities_and_deaths(pdf_path: Path):
    """Extract localities from page 2 and death notes from page 3 (Notebook 03 logic)."""
    with pdfplumber.open(pdf_path) as pdf:
        page_2_tables = pdf.pages[1].extract_tables(TABLE_SETTINGS)
        page_3_tables = pdf.pages[2].extract_tables(TABLE_SETTINGS) if len(pdf.pages) >= 3 else []

    page_2_table = max(page_2_tables, key=len) if page_2_tables else []
    page_3_table = max(page_3_tables, key=len) if page_3_tables else []
    report_date = extract_report_date_from_table(page_2_table)

    # --- Localities ---
    district_code_pattern = "|".join(re.escape(c) for c in DISTRICTS)
    district_marker = re.compile(rf"\b({district_code_pattern})\s*:")

    def split_district_sections(text):
        text = clean(text)
        matches = list(district_marker.finditer(text))
        sections = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            loc = text[m.end():end].strip(" ,;")
            if loc:
                sections.append((m.group(1), loc))
        return sections

    locality_start = None
    for i, row in enumerate(page_2_table):
        if clean(row[0]).upper() == "DISEASE":
            locality_start = i + 1
            break

    locality_records = []
    if locality_start is not None:
        current_disease = None
        for row in page_2_table[locality_start:]:
            if len(row) < 7:
                continue
            disease_cell = clean(row[0])
            if disease_cell:
                current_disease = disease_cell
            if current_disease is None:
                continue

            raw_text = " | ".join(clean(c) for c in row if clean(c))
            district_cell = clean(row[4])
            possible_code = district_cell.rstrip(":").strip().upper()

            normalize = lambda d: DISEASE_ALIASES_LOCALITY.get(clean(d), clean(d))

            if possible_code in DISTRICTS:
                loc_text = clean(row[6])
                if not loc_text:
                    continue
                locality_records.append({
                    "disease_raw": current_disease, "disease": normalize(current_disease),
                    "district_code": possible_code,
                    "district_reported_count": to_state_count(row[5]) if clean(row[5]) else pd.NA,
                    "locality_text": loc_text, "raw_text": raw_text,
                })
            else:
                for code, loc in split_district_sections(district_cell):
                    locality_records.append({
                        "disease_raw": current_disease, "disease": normalize(current_disease),
                        "district_code": code, "district_reported_count": pd.NA,
                        "locality_text": loc, "raw_text": raw_text,
                    })

    locality_df = pd.DataFrame(locality_records)
    if not locality_df.empty:
        locality_df["district_reported_count"] = locality_df["district_reported_count"].astype("Int64")
        locality_df["district_name"] = locality_df["district_code"].map(DISTRICTS)

    # --- Death Notes ---
    death_lines = []
    for row in page_3_table:
        for cell in row:
            if isinstance(cell, str) and "Death:" in cell and "DOD" in cell:
                for line in cell.splitlines():
                    line = clean(line)
                    if line:
                        death_lines.append(line)

    death_records = []
    for line in death_lines:
        m = DEATH_PATTERN.match(line)
        if m is None:
            death_records.append({
                "district_code": None, "district_name": None,
                "disease_raw": None, "disease": None,
                "age": pd.NA, "sex": None, "locality": None,
                "death_date": None, "parse_status": "needs_review", "raw_text": line,
            })
            continue

        dc = m.group("district")
        if dc:
            dc = dc.upper()
        disease_raw = clean(m.group("disease"))
        normalize = lambda d: DISEASE_ALIASES_LOCALITY.get(d, d)
        sex_raw = clean(m.group("sex")).upper()
        date_text = re.sub(r"[-/]", ".", m.group("date"))
        death_date = datetime.strptime(date_text, "%d.%m.%Y").date().isoformat()

        death_records.append({
            "district_code": dc, "district_name": DISTRICTS.get(dc),
            "disease_raw": disease_raw, "disease": normalize(disease_raw),
            "age": int(m.group("age")),
            "sex": SEX_ALIASES.get(sex_raw, sex_raw.casefold()),
            "locality": clean(m.group("locality")),
            "death_date": death_date, "parse_status": "parsed", "raw_text": line,
        })

    death_df = pd.DataFrame(death_records)
    if not death_df.empty:
        death_df["age"] = death_df["age"].astype("Int64")

    return report_date, locality_df, death_df


def normalize_to_observations(district_df, report_date, pdf_name):
    """Convert wide district table to long-format observations (Notebook 04 logic)."""
    records = []
    for _, row in district_df.iterrows():
        for src_col, (disease, metric, subtype) in COLUMN_MEANINGS.items():
            records.append({
                "report_date": report_date, "period_type": "daily",
                "source_filename": pdf_name, "schema_version": "daily_v1",
                "source_page": 2, "geography_level": "district",
                "district_code": row["district_code"],
                "district_name": row["district_name"],
                "disease": disease, "metric": metric,
                "subtype": subtype, "value": int(row[src_col]),
                "source_column": src_col,
            })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 3. DATABASE LOADING (Notebook 05 logic)
# ---------------------------------------------------------------------------

def get_existing_dates():
    """Get report dates already in the database."""
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        dates = {r[0] for r in conn.execute("SELECT report_date FROM reports").fetchall()}
    except sqlite3.OperationalError:
        dates = set()
    conn.close()
    return dates


def ensure_schema(conn):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL UNIQUE,
            period_type TEXT NOT NULL,
            source_url TEXT,
            filename TEXT NOT NULL,
            file_hash TEXT,
            ingested_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS observations (
            obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            geography_level TEXT,
            district_code TEXT,
            district_name TEXT,
            disease TEXT,
            metric TEXT,
            subtype TEXT,
            value REAL NOT NULL,
            source_page INTEGER,
            FOREIGN KEY (report_id) REFERENCES reports(report_id)
        );
        CREATE TABLE IF NOT EXISTS locality_reports (
            loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            district_code TEXT,
            district_name TEXT,
            disease_raw TEXT,
            disease TEXT NOT NULL,
            district_reported_count REAL,
            locality_text TEXT NOT NULL,
            raw_text TEXT,
            source_page INTEGER,
            FOREIGN KEY (report_id) REFERENCES reports(report_id)
        );
        CREATE TABLE IF NOT EXISTS death_notes (
            death_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            district_code TEXT,
            district_name TEXT,
            disease_raw TEXT,
            disease TEXT,
            age INTEGER,
            sex TEXT,
            locality TEXT,
            death_date TEXT,
            parse_status TEXT NOT NULL,
            raw_text TEXT,
            source_page INTEGER,
            FOREIGN KEY (report_id) REFERENCES reports(report_id)
        );
        CREATE TABLE IF NOT EXISTS state_analysis (
            state_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            serial_number INTEGER,
            disease_raw TEXT,
            disease TEXT NOT NULL,
            subtype_raw TEXT,
            subtype TEXT,
            daily_suspected_cases REAL,
            daily_suspected_deaths REAL,
            daily_confirmed REAL,
            daily_deaths REAL,
            month_suspected_cases REAL,
            month_suspected_deaths REAL,
            month_confirmed REAL,
            month_deaths REAL,
            cumulative_suspected_cases REAL,
            cumulative_suspected_deaths REAL,
            cumulative_confirmed REAL,
            cumulative_deaths REAL,
            source_page INTEGER,
            FOREIGN KEY (report_id) REFERENCES reports(report_id)
        );
        CREATE TABLE IF NOT EXISTS diseases (
            canonical_name TEXT PRIMARY KEY,
            aliases TEXT
        );
    """)


def load_into_db(report_date, pdf_path, observations_df, state_df, locality_df, death_df):
    """Insert extracted data into SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    ensure_schema(conn)
    cur = conn.cursor()

    file_hash = hashlib.md5(pdf_path.read_bytes()).hexdigest()

    cur.execute(
        "INSERT INTO reports (report_date, period_type, filename, file_hash) VALUES (?, ?, ?, ?)",
        (report_date, "daily", pdf_path.name, file_hash)
    )
    report_id = cur.lastrowid

    for _, row in observations_df.iterrows():
        cur.execute(
            "INSERT INTO observations (report_id, geography_level, district_code, district_name, disease, metric, subtype, value, source_page) VALUES (?,?,?,?,?,?,?,?,?)",
            (report_id, row.get("geography_level"), row.get("district_code"), row.get("district_name"),
             row.get("disease"), row.get("metric"), row.get("subtype"), row.get("value"), row.get("source_page"))
        )

    if not state_df.empty:
        for _, row in state_df.iterrows():
            cur.execute(
                "INSERT INTO state_analysis (report_id, serial_number, disease_raw, disease, subtype_raw, subtype, "
                "daily_suspected_cases, daily_suspected_deaths, daily_confirmed, daily_deaths, "
                "month_suspected_cases, month_suspected_deaths, month_confirmed, month_deaths, "
                "cumulative_suspected_cases, cumulative_suspected_deaths, cumulative_confirmed, cumulative_deaths, source_page) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (report_id, sql_val(row.get("serial_number")), row.get("disease_raw"), row.get("disease"),
                 row.get("subtype_raw"), sql_val(row.get("subtype")),
                 sql_val(row.get("daily_suspected_cases")), sql_val(row.get("daily_suspected_deaths")),
                 sql_val(row.get("daily_confirmed")), sql_val(row.get("daily_deaths")),
                 sql_val(row.get("month_suspected_cases")), sql_val(row.get("month_suspected_deaths")),
                 sql_val(row.get("month_confirmed")), sql_val(row.get("month_deaths")),
                 sql_val(row.get("cumulative_suspected_cases")), sql_val(row.get("cumulative_suspected_deaths")),
                 sql_val(row.get("cumulative_confirmed")), sql_val(row.get("cumulative_deaths")), 3)
            )

    if not locality_df.empty:
        for _, row in locality_df.iterrows():
            cur.execute(
                "INSERT INTO locality_reports (report_id, district_code, district_name, disease_raw, disease, "
                "district_reported_count, locality_text, raw_text, source_page) VALUES (?,?,?,?,?,?,?,?,?)",
                (report_id, row.get("district_code"), row.get("district_name"),
                 row.get("disease_raw"), row.get("disease"),
                 None if pd.isna(row.get("district_reported_count", pd.NA)) else row.get("district_reported_count"),
                 row.get("locality_text"), row.get("raw_text"), 2)
            )

    if not death_df.empty:
        for _, row in death_df.iterrows():
            cur.execute(
                "INSERT INTO death_notes (report_id, district_code, district_name, disease_raw, disease, "
                "age, sex, locality, death_date, parse_status, raw_text, source_page) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (report_id, row.get("district_code"), row.get("district_name"),
                 row.get("disease_raw"), row.get("disease"),
                 None if pd.isna(row.get("age", pd.NA)) else int(row["age"]),
                 row.get("sex"), row.get("locality"), row.get("death_date"),
                 row.get("parse_status"), row.get("raw_text"), 3)
            )

    conn.commit()
    conn.close()
    return report_id


# ---------------------------------------------------------------------------
# 4. VECTOR STORE UPDATE (local bge-small-en-v1.5 embeddings)
# ---------------------------------------------------------------------------

def build_documents(report_date, observations_df, locality_df, death_df):
    """Build RAG documents (text, metadata, id) from a report's extracted data."""
    documents, metadatas, ids = [], [], []

    district_diseases = observations_df.groupby(["district_code", "district_name", "disease"])
    for (d_code, d_name, disease), group in district_diseases:
        metrics = []
        for _, row in group.iterrows():
            sub = f" ({row['subtype']})" if row.get("subtype") else ""
            metrics.append(f"  {row['metric']}{sub}: {int(row['value'])}")
        doc = (
            f"Report date: {report_date}\n"
            f"District: {d_name} ({d_code})\n"
            f"Disease: {disease}\n" + "\n".join(metrics) +
            f"\nSource: Kerala IDSP Daily Report, page 2 (district table)."
        )
        doc_id = f"{report_date}_{d_code}_{disease}".replace(" ", "_")
        documents.append(doc)
        metadatas.append({"doc_type": "district_disease_summary", "report_date": report_date,
                          "district_code": d_code, "district_name": d_name, "disease": disease})
        ids.append(doc_id)

    if locality_df is not None and not locality_df.empty:
        for _, row in locality_df.iterrows():
            count_str = f"{int(row['district_reported_count'])} confirmed cases" if pd.notna(row.get("district_reported_count")) else "count not specified"
            doc = (
                f"Report date: {report_date}\n"
                f"District: {row['district_name']}\n"
                f"Disease: {row['disease']}\n"
                f"Confirmed cases in district: {count_str}\n"
                f"Reported localities: {row['locality_text']}\n"
                f"Source: Kerala IDSP Daily Report, page 2 (locality section)."
            )
            doc_id = f"{report_date}_loc_{row['district_code']}_{row['disease']}".replace(" ", "_")
            documents.append(doc)
            metadatas.append({"doc_type": "locality_report", "report_date": report_date,
                              "district_code": row["district_code"], "district_name": row["district_name"],
                              "disease": row["disease"]})
            ids.append(doc_id)

    if death_df is not None and not death_df.empty:
        for _, row in death_df.iterrows():
            if row.get("parse_status") != "parsed":
                continue
            doc = (
                f"Report date: {report_date}\n"
                f"Death report: {row.get('disease', 'Unknown')} death in {row.get('district_name', 'Unknown')}\n"
                f"Details: {row.get('age', '?')}/{row.get('sex', '?')}, {row.get('locality', 'Unknown')}\n"
                f"Date of death: {row.get('death_date', 'Unknown')}\n"
                f"Source: Kerala IDSP Daily Report, page 3 (death notes)."
            )
            doc_id = f"{report_date}_death_{row.get('district_code', 'UNK')}_{row.get('disease', 'UNK')}_{row.get('age', 0)}".replace(" ", "_")
            documents.append(doc)
            metadatas.append({"doc_type": "death_note", "report_date": report_date,
                              "district_code": row.get("district_code"), "disease": row.get("disease")})
            ids.append(doc_id)

    return documents, metadatas, ids


def _get_collection(reset=False):
    """Open (or create) the ChromaDB collection. Cosine space suits unit-normalized bge vectors."""
    import chromadb
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    if reset:
        try:
            chroma_client.delete_collection("idsp_kerala")
        except Exception:
            pass
    return chroma_client.get_or_create_collection(
        "idsp_kerala", metadata={"hnsw:space": "cosine"}
    )


def update_embeddings(report_date, observations_df, locality_df, death_df):
    """Embed a single report's documents locally and upsert into ChromaDB."""
    from embeddings import embed_documents

    documents, metadatas, ids = build_documents(report_date, observations_df, locality_df, death_df)
    if not documents:
        return

    collection = _get_collection()
    print(f"  Embedding {len(documents)} documents (bge-small-en-v1.5)...")
    embeddings = embed_documents(documents)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"  Embedded {len(documents)} documents to ChromaDB.")


def rebuild_vectors_from_db():
    """Rebuild the entire ChromaDB vector store from data already in SQLite.

    Run this after switching embedding models (vector dimensions differ, so the
    old collection is incompatible), or to regenerate embeddings without
    re-downloading any PDFs.
    """
    from embeddings import embed_documents

    if not DB_PATH.exists():
        print("No database found; nothing to rebuild.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    reports = conn.execute("SELECT report_id, report_date FROM reports ORDER BY report_date").fetchall()
    print(f"Rebuilding vectors from {len(reports)} reports in SQLite...")

    collection = _get_collection(reset=True)

    all_docs, all_metas, all_ids = [], [], []
    for r in reports:
        report_id, report_date = r["report_id"], r["report_date"]
        observations_df = pd.read_sql_query(
            "SELECT district_code, district_name, disease, metric, subtype, value "
            "FROM observations WHERE report_id = ?", conn, params=[report_id])
        locality_df = pd.read_sql_query(
            "SELECT district_code, district_name, disease, district_reported_count, locality_text "
            "FROM locality_reports WHERE report_id = ?", conn, params=[report_id])
        death_df = pd.read_sql_query(
            "SELECT district_code, district_name, disease, age, sex, locality, death_date, parse_status "
            "FROM death_notes WHERE report_id = ?", conn, params=[report_id])

        docs, metas, ids = build_documents(report_date, observations_df, locality_df, death_df)
        all_docs.extend(docs)
        all_metas.extend(metas)
        all_ids.extend(ids)

    conn.close()

    if not all_docs:
        print("No documents to embed.")
        return

    print(f"Embedding {len(all_docs)} documents (bge-small-en-v1.5)...")
    embeddings = embed_documents(all_docs)
    batch = 500
    for i in range(0, len(all_docs), batch):
        collection.upsert(
            ids=all_ids[i:i + batch], documents=all_docs[i:i + batch],
            metadatas=all_metas[i:i + batch], embeddings=embeddings[i:i + batch],
        )
    print(f"Rebuilt vector store with {len(all_docs)} documents.")


# ---------------------------------------------------------------------------
# 5. MAIN PIPELINE
# ---------------------------------------------------------------------------

def process_date(report_date: date, page_url: str = None, skip_embeddings: bool = False):
    """Full pipeline for one report date."""
    date_str = report_date.isoformat()
    print(f"\n{'='*60}")
    print(f"Processing: {date_str}")

    pdf_path = download_pdf(report_date, page_url)

    print("  Extracting district table...")
    extracted_date, district_df = extract_district_table(pdf_path)
    print(f"    {len(district_df)} district rows")

    print("  Extracting state analysis...")
    _, state_df = extract_state_analysis(pdf_path)
    print(f"    {len(state_df)} state rows")

    print("  Extracting localities and death notes...")
    _, locality_df, death_df = extract_localities_and_deaths(pdf_path)
    print(f"    {len(locality_df)} locality rows, {len(death_df)} death notes")

    print("  Normalizing to observations...")
    observations_df = normalize_to_observations(district_df, date_str, pdf_path.name)
    print(f"    {len(observations_df)} observations")

    print("  Loading into SQLite...")
    report_id = load_into_db(date_str, pdf_path, observations_df, state_df, locality_df, death_df)
    print(f"    Inserted as report_id={report_id}")

    if skip_embeddings:
        print("  Skipping vector store update (--skip-embeddings).")
    else:
        print("  Updating vector store...")
        try:
            update_embeddings(date_str, observations_df, locality_df, death_df)
        except Exception as e:
            print(f"  WARNING: Embedding failed (data still in SQLite): {e}")

    print(f"  Done: {date_str}")
    return True


def main():
    parser = argparse.ArgumentParser(description="IDSP Kerala automated ingestion pipeline")
    parser.add_argument("--days", type=int, help="Only fetch the last N days")
    parser.add_argument("--date", type=str, help="Fetch a specific date (YYYY-MM-DD)")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip vector store update")
    parser.add_argument("--rebuild-vectors", action="store_true",
                        help="Rebuild the entire ChromaDB from data already in SQLite (use after changing embedding model)")
    args = parser.parse_args()

    if args.rebuild_vectors:
        rebuild_vectors_from_db()
        return

    existing_dates = get_existing_dates()
    print(f"Existing reports in DB: {len(existing_dates)}")

    if args.date:
        target_dates = {date.fromisoformat(args.date): None}
    else:
        available = get_available_dates()
        print(f"Reports available on IDSP site: {len(available)}")

        if args.days:
            cutoff = date.today()
            available = {d: url for d, url in available.items() if (cutoff - d).days <= args.days}

        target_dates = {d: url for d, url in available.items() if d.isoformat() not in existing_dates}

    print(f"New reports to process: {len(target_dates)}")

    if not target_dates:
        print("Nothing new to ingest.")
        return

    success, failed = 0, 0
    for d in sorted(target_dates):
        try:
            process_date(d, target_dates[d], skip_embeddings=args.skip_embeddings)
            success += 1
        except Exception as e:
            print(f"  FAILED: {d} - {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Ingestion complete: {success} succeeded, {failed} failed")

    conn = sqlite3.connect(str(DB_PATH))
    for table in ["reports", "observations", "locality_reports", "death_notes", "state_analysis"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
    conn.close()


if __name__ == "__main__":
    main()
