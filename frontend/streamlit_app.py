from __future__ import annotations

import os

import requests
import streamlit as st

st.set_page_config(page_title="Enterprise Knowledge Copilot", page_icon="📚", layout="wide")
DEFAULT_API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")

if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None
if "api_base" not in st.session_state:
    st.session_state.api_base = DEFAULT_API


def api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {st.session_state.token}"}


def show_api_error(response: requests.Response) -> None:
    try:
        message = response.json().get("detail", response.text)
    except ValueError:
        message = response.text
    st.error(f"Request failed ({response.status_code}): {message}")


st.title("📚 Enterprise Knowledge Copilot")
st.caption("Search enterprise policies securely. Answers are limited to documents your role is allowed to access.")

with st.sidebar:
    st.subheader("Connection")
    st.session_state.api_base = st.text_input("Backend API", st.session_state.api_base).rstrip("/")
    st.divider()
    if not st.session_state.token:
        st.subheader("Sign in")
        email = st.text_input("Work email", value="employee@example.com")
        password = st.text_input("Password", type="password")
        if st.button("Sign in", type="primary", use_container_width=True):
            try:
                response = requests.post(
                    f"{st.session_state.api_base}/auth/login",
                    json={"email": email, "password": password},
                    timeout=20,
                )
                if response.ok:
                    st.session_state.token = response.json()["access_token"]
                    profile = requests.get(
                        f"{st.session_state.api_base}/auth/me",
                        headers=api_headers(),
                        timeout=20,
                    )
                    profile.raise_for_status()
                    st.session_state.user = profile.json()
                    st.rerun()
                else:
                    show_api_error(response)
            except requests.RequestException as exc:
                st.error(f"Could not reach the API at {st.session_state.api_base}: {exc}")
    else:
        user = st.session_state.user or {}
        st.success(f"{user.get('username', 'Signed in')} · {user.get('role', 'UNKNOWN')}")
        st.caption(user.get("email", ""))
        if st.button("Sign out", use_container_width=True):
            st.session_state.token = None
            st.session_state.user = None
            st.rerun()

if not st.session_state.token:
    st.info("Sign in to search authorized enterprise documents.")
    st.markdown(
        "**Development accounts** are documented in the project README. "
        "The local extractive answer mode does not require an external LLM key."
    )
    st.stop()

chat_tab, docs_tab, admin_tab = st.tabs(["Ask a question", "Documents", "Admin & evaluation"])

with chat_tab:
    st.subheader("Ask your knowledge copilot")
    question = st.text_area(
        "Question",
        placeholder="Example: How many annual leave days do full-time employees receive?",
        height=90,
    )
    if st.button("Search authorized knowledge", type="primary", disabled=not question.strip()):
        with st.spinner("Searching authorized documents and preparing an evidence-based response..."):
            try:
                response = requests.post(
                    f"{st.session_state.api_base}/chat",
                    json={"question": question},
                    headers=api_headers(),
                    timeout=180,
                )
                if response.ok:
                    answer = response.json()
                    st.markdown("### Answer")
                    st.write(answer["answer"])
                    left, right = st.columns(2)
                    left.metric("Latency", f"{answer['latency_ms']:.0f} ms")
                    right.metric("Answer mode", answer.get("model") or "configured provider")
                    if answer.get("cache_hit"):
                        st.caption("Semantic cache hit (scoped to your role and permission set).")
                    st.markdown("### Sources")
                    if answer.get("citations"):
                        for citation in answer["citations"]:
                            st.info(citation)
                    else:
                        st.caption("No supporting source was retrieved.")
                    with st.expander("Retrieved evidence and metadata"):
                        st.json(answer.get("retrieved_chunks", []))
                else:
                    show_api_error(response)
            except requests.RequestException as exc:
                st.error(f"Question request failed: {exc}")

with docs_tab:
    st.subheader("Documents available to your role")
    try:
        response = requests.get(
            f"{st.session_state.api_base}/documents",
            headers=api_headers(),
            timeout=30,
        )
        if response.ok:
            documents = response.json().get("documents", [])
            if documents:
                st.dataframe(documents, width="stretch", hide_index=True)
            else:
                st.info("No documents are indexed yet.")
        else:
            show_api_error(response)
    except requests.RequestException as exc:
        st.error(f"Could not load documents: {exc}")

    if (st.session_state.user or {}).get("role") == "ADMIN":
        st.markdown("#### Add a document")
        with st.form("upload_document"):
            upload = st.file_uploader("PDF, TXT, or Markdown", type=["pdf", "txt", "md", "markdown"])
            access_level = st.selectbox("Access level", ["PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"])
            department = st.text_input("Department", value="General")
            submitted = st.form_submit_button("Upload and index")
        if submitted and upload is not None:
            with st.spinner("Extracting pages and indexing document..."):
                try:
                    response = requests.post(
                        f"{st.session_state.api_base}/documents/upload",
                        headers=api_headers(),
                        files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")},
                        data={"access_level": access_level, "department": department},
                        timeout=120,
                    )
                    if response.status_code == 201:
                        st.success(f"Document indexed: {response.json()['chunks']} chunks.")
                        st.rerun()
                    else:
                        show_api_error(response)
                except requests.RequestException as exc:
                    st.error(f"Upload failed: {exc}")

with admin_tab:
    if (st.session_state.user or {}).get("role") != "ADMIN":
        st.info("Admin metrics, security evaluation, and evaluation controls are restricted to administrators.")
    else:
        st.subheader("Operational overview")
        try:
            response = requests.get(
                f"{st.session_state.api_base}/admin/overview",
                headers=api_headers(),
                timeout=30,
            )
            if response.ok:
                overview = response.json()
                c1, c2, c3 = st.columns(3)
                c1.metric("Documents", overview["documents"])
                c2.metric("Chunks", overview["chunks"])
                c3.metric("Queries this process", overview["queries"])
                st.metric("Observed cache hit rate", f"{overview['cache_hit_rate']:.1%}")
                if overview.get("evaluation"):
                    st.markdown("#### Latest actual evaluation")
                    st.json(overview["evaluation"])
                else:
                    st.info("No evaluation has been run yet.")
            else:
                show_api_error(response)
        except requests.RequestException as exc:
            st.error(f"Could not load admin overview: {exc}")
        if st.button("Run retrieval and security evaluation"):
            with st.spinner("Evaluating the real retrieval pipeline; first use may download models..."):
                try:
                    response = requests.post(
                        f"{st.session_state.api_base}/evaluation/run",
                        headers=api_headers(),
                        timeout=900,
                    )
                    if response.ok:
                        st.success("Evaluation completed.")
                        st.json(response.json())
                    else:
                        show_api_error(response)
                except requests.RequestException as exc:
                    st.error(f"Evaluation request failed: {exc}")
