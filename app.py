"""IDSP Kerala Hybrid RAG Chatbot — Streamlit App"""

import os
import streamlit as st
from dotenv import load_dotenv
from google import genai
from query_router import QueryRouter, classify_intent, extract_district, extract_disease
from vector_search import VectorSearch

load_dotenv()

DB_PATH = os.path.join("notebooks", "data", "idsp_kerala.db")
CHROMA_PATH = os.path.join("data", "chroma_db")
LLM_MODEL = "gemini-3.6-flash"

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
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return router, vector, gemini_client


def build_context(question, router, vector):
    parts = []
    sql_desc, sql_df = router.route(question)
    parts.append(f"## SQL Query Result\n{sql_desc}")
    if not sql_df.empty:
        parts.append(sql_df.to_string(index=False))
    else:
        parts.append("(No structured data matched.)")
    vector_context = vector.get_context(question, n_results=3)
    parts.append(f"\n## Relevant Documents\n{vector_context}")
    return "\n\n".join(parts)


def get_answer(question, router, vector, gemini_client):
    context = build_context(question, router, vector)
    prompt = f"""Based on the following IDSP Kerala data, answer the user's question.

DATA CONTEXT:
{context}

USER QUESTION: {question}

ANSWER:"""
    response = gemini_client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.2,
            "max_output_tokens": 1024,
        }
    )
    return response.text


# --- Streamlit UI ---
st.set_page_config(page_title="IDSP Kerala Chatbot", page_icon="🏥")
st.title("🏥 IDSP Kerala Disease Surveillance Chatbot")
st.caption("Ask questions about disease outbreaks, cases, deaths, and localities in Kerala.")

router, vector, gemini_client = load_components()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about Kerala IDSP data..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing IDSP data..."):
            answer = get_answer(prompt, router, vector, gemini_client)
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
