import streamlit as st
import re

st.set_page_config(page_title="Agile Suite", layout="wide")
st.title("🛠️ Agile Sprint Planner + Retrospective + AI Insights")

tab1, tab2, tab3 = st.tabs(["📅 Sprint Planner", "📊 Retrospective", "🤖 AI Suggestions"])

def safe_exec(file_path, tab_name=""):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Remove any line that calls st.set_page_config (even if spaces or tabs exist)
        filtered_lines = [line for line in lines if ".set_page_config" not in line]
        cleaned_code = ''.join(filtered_lines)

        exec(cleaned_code, globals())
    except Exception as e:
        st.error(f"❌ Error running `{file_path}` in {tab_name} tab:\n\n`{type(e).__name__}: {e}`")


# Shared session state
if "retrospective_feedback" not in st.session_state:
    st.session_state.retrospective_feedback = None
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None

# Tab 1: Sprint Planner
with tab1:
    st.markdown("### Sprint Planner Interface")
    safe_exec("4.0AIchatbotsprint_FINAL_FULL.py", "Sprint Planner")

# Tab 2: Retrospective
with tab2:
    st.markdown("### Retrospective Feedback Analysis")
    safe_exec("app.py", "Retrospective Analysis")

# Tab 3: AI
with tab3:
    st.markdown("### AI Suggestions Based on Feedback + Sprint Data")
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
