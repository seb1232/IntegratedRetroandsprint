import streamlit as st
import pandas as pd
import base64
import requests
import json
import io
import matplotlib.pyplot as plt
import numpy as np
import plotly.express as px

# === Sprint Planner Code Start ===
" + open("/mnt/data/4.0AIchatbotsprint_FINAL_FULL.py", "r", encoding="utf-8").read().replace("\"""", "\"\"\"") + "
# === Sprint Planner Code End ===

# === Retrospective Tool Code Start ===
" + open("/mnt/data/app.py", "r", encoding="utf-8").read().replace("\"""", "\"\"\"") + "
# === Retrospective Tool Code End ===

# --- Unified Page Config ---
st.set_page_config(
    page_title="Sprint + Retrospective Planner",
    layout="wide",
    page_icon="📈"
)

st.markdown("""
<style>
    .main {
        background-color: #0e1117;
        color: #e0e0e0;
    }
    .metric-card, .azure-section {
        background-color: #1e2130;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 16px;
        color: #e0e0e0;
    }
    .download-link {
        background-color: #1e8e3e;
        color: white;
        padding: 8px 16px;
        border-radius: 4px;
        text-decoration: none;
        display: inline-block;
        margin-top: 10px;
    }
    .download-link:hover {
        background-color: #166e2e;
    }
</style>
""", unsafe_allow_html=True)

# --- Unified Tabs ---
tabs = st.tabs(["📋 Sprint Planner", "📊 Retrospectives", "🤖 AI Assistant"])

# --- AI Assistant Tab ---
with tabs[2]:
    st.header("🤖 Unified Sprint & Retrospective Assistant")
    st.markdown("Ask the AI to analyze both your task planning and retrospective insights.")

    if "ai_chat" not in st.session_state:
        st.session_state.ai_chat = [
            {"role": "assistant", "content": "Hi! I can help you understand your sprint plan, team feedback, and suggest improvements. Ask me anything!"}
        ]

    for msg in st.session_state.ai_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    api_key = st.text_input("OpenRouter API Key", type="password", key="chat_key")
    user_prompt = st.chat_input("Ask me about team capacity, issues, or feedback patterns...")

    if user_prompt:
        st.session_state.ai_chat.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        context = "You are an agile assistant analyzing sprint tasks and retrospectives.\n"

        if "df_tasks" in st.session_state and st.session_state.df_tasks is not None:
            df_tasks = st.session_state.df_tasks
            context += f"\nThere are {len(df_tasks)} active tasks.\n"
            top_priorities = df_tasks["Priority"].value_counts().to_dict()
            context += f"Task Priority Breakdown: {top_priorities}\n"

        if "results_df" in locals():
            context += f"\nYou also have {len(results_df)} feedback items from team retrospectives.\n"
            top_feedback = results_df.head(5)["Feedback"].tolist()
            context += "Sample feedback: " + "; ".join(top_feedback) + "\n"

        context += f"\nUser asked: {user_prompt}"

        with st.chat_message("assistant"):
            placeholder = st.empty()
            response_txt = ""

            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://localhost",
                "Content-Type": "application/json"
            }

            body = {
                "model": "openai/gpt-3.5-turbo",
                "messages": [{"role": "system", "content": context}] + [m for m in st.session_state.ai_chat if m["role"] != "assistant"],
                "stream": True
            }

            try:
                with requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, stream=True) as response:
                    for line in response.iter_lines():
                        if line and line.decode("utf-8").startswith("data:"):
                            try:
                                delta = json.loads(line.decode("utf-8")[5:])["choices"][0]["delta"]
                                if "content" in delta:
                                    response_txt += delta["content"]
                                    placeholder.markdown(response_txt + "▌")
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                response_txt = f"Error: {str(e)}"
                placeholder.markdown(response_txt)

            st.session_state.ai_chat.append({"role": "assistant", "content": response_txt})
