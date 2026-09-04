
"""IDSP Kerala - Query Router & SQL Retrieval Module"""

import sqlite3
import pandas as pd
import re
from typing import Optional


DISTRICT_ALIASES = {
    "tvm": "Thiruvananthapuram", "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "klm": "Kollam", "kollam": "Kollam", "quilon": "Kollam",
    "pta": "Pathanamthitta", "pathanamthitta": "Pathanamthitta",
    "idk": "Idukki", "idukki": "Idukki",
    "ktm": "Kottayam", "kottayam": "Kottayam",
    "alp": "Alappuzha", "alappuzha": "Alappuzha", "alleppey": "Alappuzha",
    "ekm": "Ernakulam", "ernakulam": "Ernakulam", "kochi": "Ernakulam",
    "tsr": "Thrissur", "thrissur": "Thrissur", "trichur": "Thrissur",
    "pkd": "Palakkad", "palakkad": "Palakkad", "palghat": "Palakkad",
    "mpm": "Malappuram", "malappuram": "Malappuram",
    "kkd": "Kozhikode", "kozhikode": "Kozhikode", "calicut": "Kozhikode",
    "wyd": "Wayanad", "wayanad": "Wayanad",
    "knr": "Kannur", "kannur": "Kannur", "cannanore": "Kannur",
    "ksd": "Kasaragod", "kasaragod": "Kasaragod",
}

DISEASE_ALIASES = {
    "dengue": "Dengue", "dengue fever": "Dengue",
    "lepto": "Leptospirosis", "leptospirosis": "Leptospirosis",
    "chikungunya": "Chikungunya", "chik": "Chikungunya", "cg": "Chikungunya",
    "malaria": "Malaria",
    "fever": "Fever",
    "cholera": "Cholera",
    "chickenpox": "Chickenpox", "chicken pox": "Chickenpox",
    "hepatitis a": "Hepatitis A", "hep a": "Hepatitis A",
    "diarrhoea": "Acute Diarrhoeal Disease", "diarrhoeal": "Acute Diarrhoeal Disease",
    "add": "Acute Diarrhoeal Disease", "acute diarrhoeal disease": "Acute Diarrhoeal Disease",
    "aes": "Acute Encephalitis Syndrome", "encephalitis": "Acute Encephalitis Syndrome",
    "japanese encephalitis": "Japanese Encephalitis", "je": "Japanese Encephalitis",
    "scrub typhus": "Scrub Typhus", "typhus": "Scrub Typhus",
    "influenza": "Influenza", "h1n1": "Influenza", "flu": "Influenza",
}


def extract_district(question: str) -> Optional[str]:
    q = question.lower()
    for alias, canonical in sorted(DISTRICT_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in q:
            return canonical
    return None


def extract_disease(question: str) -> Optional[str]:
    q = question.lower()
    for alias, canonical in sorted(DISEASE_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in q:
            return canonical
    return None


INTENT_PATTERNS = [
    ("latest_report",   r"\b(latest|recent|last|current|newest)\b.*\b(report|date|data)\b"),
    ("death_summary",   r"\b(death|died|fatal|mortality|dod)\b"),
    ("locality_search", r"\b(where|location|locality|localit|area|place|panchayat|village|town)\b"),
    ("compare_districts", r"\b(compare|comparison|across|between|district.?wise|all district)\b"),
    ("state_overview",  r"\b(state|statewide|kerala|overall|total|cumulative|monthly)\b"),
    ("top_diseases",    r"\b(top|highest|most|maximum|leading|major|worst|rank)\b"),
    ("district_disease_summary", r"."),
]


def classify_intent(question: str) -> str:
    q = question.lower()
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, q):
            if intent == "district_disease_summary":
                if extract_district(question):
                    return "district_disease_summary"
                else:
                    return "state_overview"
            return intent
    return "unknown"


class QueryRouter:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()

    def _latest_date(self) -> str:
        self.cur.execute("SELECT MAX(report_date) FROM reports")
        return self.cur.fetchone()[0]

    def route(self, question: str) -> tuple[str, pd.DataFrame]:
        intent = classify_intent(question)
        district = extract_district(question)
        disease = extract_disease(question)
        latest = self._latest_date()

        if intent == "latest_report":
            return self._latest_report()
        elif intent == "district_disease_summary":
            return self._district_summary(district, latest) if district else self._state_overview(disease, latest)
        elif intent == "top_diseases":
            return self._top_diseases(district, latest)
        elif intent == "locality_search":
            if not disease:
                return "Please specify a disease for locality search.", pd.DataFrame()
            return self._locality_search(disease, district, latest)
        elif intent == "death_summary":
            return self._death_summary(district, disease, latest)
        elif intent == "state_overview":
            return self._state_overview(disease, latest)
        elif intent == "compare_districts":
            if not disease:
                return "Please specify a disease to compare across districts.", pd.DataFrame()
            return self._compare_districts(disease, latest)
        else:
            return "I couldn't understand that question. Try asking about diseases, districts, deaths, or localities.", pd.DataFrame()

    def _latest_report(self):
        df = pd.read_sql_query("SELECT report_date, period_type, filename, ingested_at FROM reports ORDER BY report_date DESC LIMIT 1", self.conn)
        return f"The latest IDSP report is dated {df.iloc[0]['report_date']}.", df

    def _district_summary(self, district, latest):
        df = pd.read_sql_query("SELECT o.disease, o.metric, o.subtype, o.value FROM observations o JOIN reports r ON o.report_id = r.report_id WHERE o.district_name = ? AND r.report_date = ? AND o.value > 0 ORDER BY o.disease, o.metric", self.conn, params=[district, latest])
        return f"Diseases reported in {district} on {latest}.", df

    def _top_diseases(self, district, latest, metric="confirmed", limit=10):
        if district:
            df = pd.read_sql_query("SELECT o.disease, o.value FROM observations o JOIN reports r ON o.report_id = r.report_id WHERE o.district_name = ? AND r.report_date = ? AND o.metric = ? AND o.value > 0 ORDER BY o.value DESC LIMIT ?", self.conn, params=[district, latest, metric, limit])
            return f"Top diseases by {metric} in {district} on {latest}.", df
        df = pd.read_sql_query("SELECT o.disease, SUM(o.value) as total FROM observations o JOIN reports r ON o.report_id = r.report_id WHERE r.report_date = ? AND o.metric = ? AND o.value > 0 GROUP BY o.disease ORDER BY total DESC LIMIT ?", self.conn, params=[latest, metric, limit])
        return f"Top diseases by {metric} statewide on {latest}.", df

    def _locality_search(self, disease, district, latest):
        if district:
            df = pd.read_sql_query("SELECT lr.district_name, lr.disease, lr.district_reported_count, lr.locality_text FROM locality_reports lr JOIN reports r ON lr.report_id = r.report_id WHERE lr.disease = ? AND lr.district_name = ? AND r.report_date = ?", self.conn, params=[disease, district, latest])
            return f"{disease} localities in {district} on {latest}.", df
        df = pd.read_sql_query("SELECT lr.district_name, lr.disease, lr.district_reported_count, lr.locality_text FROM locality_reports lr JOIN reports r ON lr.report_id = r.report_id WHERE lr.disease = ? AND r.report_date = ? ORDER BY lr.district_reported_count DESC", self.conn, params=[disease, latest])
        return f"{disease} localities across all districts on {latest}.", df

    def _death_summary(self, district, disease, latest):
        conditions = ["r.report_date = ?"]
        params = [latest]
        if district:
            conditions.append("dn.district_name = ?")
            params.append(district)
        if disease:
            conditions.append("dn.disease = ?")
            params.append(disease)
        where = " AND ".join(conditions)
        df = pd.read_sql_query(f"SELECT dn.district_name, dn.disease, dn.age, dn.sex, dn.locality, dn.death_date FROM death_notes dn JOIN reports r ON dn.report_id = r.report_id WHERE {where} ORDER BY dn.death_date DESC", self.conn, params=params)
        parts = ["Death summary"]
        if disease: parts.append(f"for {disease}")
        if district: parts.append(f"in {district}")
        parts.append(f"on {latest}.")
        return " ".join(parts), df

    def _state_overview(self, disease, latest):
        if disease:
            df = pd.read_sql_query("SELECT sa.disease, sa.subtype, sa.daily_confirmed, sa.daily_deaths, sa.month_confirmed, sa.month_deaths, sa.cumulative_confirmed, sa.cumulative_deaths FROM state_analysis sa JOIN reports r ON sa.report_id = r.report_id WHERE sa.disease = ? AND r.report_date = ?", self.conn, params=[disease, latest])
            return f"Statewide {disease} summary on {latest}.", df
        df = pd.read_sql_query("SELECT sa.disease, sa.subtype, sa.daily_confirmed, sa.daily_deaths, sa.cumulative_confirmed, sa.cumulative_deaths FROM state_analysis sa JOIN reports r ON sa.report_id = r.report_id WHERE r.report_date = ? ORDER BY sa.daily_confirmed DESC", self.conn, params=[latest])
        return f"Statewide disease overview on {latest}.", df

    def _compare_districts(self, disease, latest, metric="confirmed"):
        df = pd.read_sql_query("SELECT o.district_name, o.value FROM observations o JOIN reports r ON o.report_id = r.report_id WHERE o.disease = ? AND o.metric = ? AND r.report_date = ? AND o.value > 0 ORDER BY o.value DESC", self.conn, params=[disease, metric, latest])
        return f"{disease} {metric} cases by district on {latest}.", df

    def close(self):
        self.conn.close()
