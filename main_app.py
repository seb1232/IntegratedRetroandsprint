import streamlit as st
from app import run_retrospective  # Import the retrospective function
from 4.0AIchatbotsprint_FINAL_FULL import run_sprint_planner  # Import the sprint planner function

# Set the page config (only need to do this once)
st.set_page_config(page_title="Agile Suite", layout="wide")
st.title("🛠️ Agile Sprint Planner + Retrospective + AI Insights")

# Create tabs
tab1, tab2, tab3 = st.tabs(["📅 Sprint Planner", "📊 Retrospective", "🤖 AI Suggestions"])

# Shared state
if "retrospective_feedback" not in st.session_state:
    st.session_state.retrospective_feedback = None
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None

# Sprint Planner
with tab1:
    run_sprint_planner()

# Retrospective
with tab2:
    run_retrospective()

# AI Suggestions
with tab3:
    st.markdown("### AI Suggestions Based on Feedback + Tasks")
    retro_df = st.session_state.get("retrospective_feedback")
    task_df = st.session_state.get("df_tasks")

    if retro_df is not None and not retro_df.empty:
        top = retro_df.sort_values(by="Votes", ascending=False).iloc[0]
        st.success(f"Top Feedback: **{top['Feedback']}** ({top['Votes']} votes)")
    else:
        st.info("No retrospective feedback available yet.")

    if task_df is not None and not task_df.empty:
        st.markdown("#### Sample Sprint Tasks")
        st.dataframe(task_df.head(5))
    else:
        st.info("No sprint tasks loaded yet.")
