"""IDSP Kerala Hybrid RAG Chatbot — Streamlit App"""

import os
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from query_router import QueryRouter, classify_intent, extract_district, extract_disease
from vector_search import VectorSearch

load_dotenv()

DB_PATH = os.path.join("notebooks", "data", "idsp_kerala.db")
CHROMA_PATH = os.path.join("data", "chroma_db")

# Grok (xAI) — OpenAI-compatible. Set XAI_API_KEY in .env / Streamlit Secrets.
# Override GROK_MODEL if xAI's current model id differs from the default.
GROK_BASE_URL = "https://api.x.ai/v1"
GROK_MODEL = os.getenv("GROK_MODEL", "grok-2-latest")

SYSTEM_PROMPT = """You are an IDSP Kerala Disease Surveillance Assistant. You answer questions
about disease outbreaks, case counts, deaths, and localities in Kerala using
official IDSP (Integrated Disease Surveillance Programme) daily reports.

RULES:
1. Only use the data provided in the context below. Never invent numbers or facts.
2. Always mention the report date so the user knows how current the data is.
3. If the data says 0 cases, say so — do not skip diseases with zero values.
4. Reported cases are preliminary and may change after lab tests and death audits.
   Include this caveat when discussing deaths or confirmed cases.
5. If the context doesn't contain enough information to answer, say so clearly.
6. Keep answers concise but complete. Use bullet points for lists.
7. When mentioning localities, note they come from the IDSP locality section and
   represent where cases were reported, not necessarily the only affected areas.
"""


@st.cache_resource
def load_components():
    router = QueryRouter(DB_PATH)
    vector = VectorSearch(CHROMA_PATH)
    grok_client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url=GROK_BASE_URL)
    return router, vector, grok_client


def build_context(question, router, vector):
    parts = []
    sql_desc, sql_df = router.route(question)
    parts.append(f"## SQL Query Result\n{sql_desc}")
    if not sql_df.empty:
        parts.append(sql_df.to_string(index=False))
    else:
        parts.append("(No structured data matched.)")
    try:
        vector_context = vector.get_context(question, n_results=3)
        parts.append(f"\n## Relevant Documents\n{vector_context}")
    except Exception:
        parts.append("\n## Relevant Documents\n(Vector search unavailable, using SQL data only.)")
    return "\n\n".join(parts)


def get_answer(question, router, vector, grok_client):
    context = build_context(question, router, vector)
    prompt = f"""Based on the following IDSP Kerala data, answer the user's question.

DATA CONTEXT:
{context}

USER QUESTION: {question}

ANSWER:"""
    response = grok_client.chat.completions.create(
        model=GROK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    return response.choices[0].message.content


SAMPLE_QUESTIONS = [
    "What is the latest report date?",
    "What diseases are reported in Kannur?",
    "Which disease has the highest confirmed cases in Ernakulam?",
    "Where was dengue reported in Kerala?",
    "How many deaths were reported and from which diseases?",
    "Compare dengue across all districts",
    "What is the statewide situation of leptospirosis?",
    "Any H1N1 deaths reported?",
    "Which areas in Thiruvananthapuram have dengue cases?",
    "What is the cumulative confirmed count of malaria?",
    "How many chickenpox cases in Thrissur?",
    "Which districts have leptospirosis localities?",
    "What are the top diseases statewide?",
    "Are there any cholera cases reported?",
]

# --- Streamlit UI ---
st.set_page_config(page_title="IDSP Kerala Chatbot", page_icon="🏥", layout="wide")
st.title("🏥 IDSP Kerala Disease Surveillance Chatbot")
st.caption("Ask questions about disease outbreaks, cases, deaths, and localities in Kerala.")

router, vector, grok_client = load_components()

# --- Sidebar ---
with st.sidebar:
    st.header("Sample Questions")
    st.markdown("Click any question to try it out:")

    for q in SAMPLE_QUESTIONS:
        if st.button(q, key=q, use_container_width=True):
            st.session_state["selected_question"] = q

    st.divider()
    st.markdown("**Data Source:** [IDSP Kerala](https://dhs.kerala.gov.in/en/idsp-2/)")
    st.markdown("**Powered by:** Grok + bge-small (local) + ChromaDB + SQLite")

    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

selected = st.session_state.pop("selected_question", None)
prompt = st.chat_input("Ask about Kerala IDSP data...")

if selected:
    prompt = selected

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing IDSP data..."):
            answer = get_answer(prompt, router, vector, grok_client)
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
