import streamlit as st
import os

# Tabs for Sprint Planner, Retrospective, AI
st.set_page_config(page_title="Agile Sprint+Retrospective Suite", layout="wide")
st.title("Integrated Agile Planning & Retrospective Suite")

tab1, tab2, tab3 = st.tabs(["📅 Sprint Planner", "📊 Retrospective", "🤖 AI Suggestions"])

# Globals for sharing session state
if "retrospective_feedback" not in st.session_state:
    st.session_state.retrospective_feedback = None
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None

# Load Sprint Planner (Tab 1)
with tab1:
    st.markdown("### Sprint Planner")
    with open("4.0AIchatbotsprint_FINAL_FULL.py", "r", encoding="utf-8") as f:
        code = f.read()
        exec(code, globals())

# Load Retrospective (Tab 2)
with tab2:
    st.markdown("### Retrospective Analysis")
    with open("app.py", "r", encoding="utf-8") as f:
        code = f.read()
        exec(code, globals())

# AI Suggestions (Tab 3)
with tab3:
    st.markdown("### AI Suggestions Based on Retrospectives and Sprint Tasks")

    # Pull retrospective feedback and task data from shared state
    retro_df = st.session_state.get("retrospective_feedback", None)
    task_df = st.session_state.get("df_tasks", None)

    if retro_df is not None and not retro_df.empty:
        top_feedback = retro_df.sort_values(by="Votes", ascending=False).iloc[0]
        st.success(f"Top feedback: *{top_feedback['Feedback']}* with **{top_feedback['Votes']} votes**.")
    else:
        st.info("Please analyze retrospective data in the 'Retrospective' tab.")

    if task_df is not None and not task_df.empty:
        st.markdown("#### Sample Task Insight")
        st.write(task_df.head(5))
    else:
        st.info("Please upload tasks in the 'Sprint Planner' tab.")
