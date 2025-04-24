import streamlit as st

st.set_page_config(page_title="Agile Suite", layout="wide")
st.title("🛠️ Agile Sprint Planner + Retrospective + AI Insights")

tab1, tab2, tab3 = st.tabs(["📅 Sprint Planner", "📊 Retrospective", "🤖 AI Suggestions"])

def safe_exec(path):
    with open(path, "r") as f:
        code = f.read()
    # Remove any lines with st.set_page_config
    filtered_code = "\n".join([line for line in code.splitlines() if "st.set_page_config" not in line])
    exec(filtered_code, globals())

# Session state placeholders
if "retrospective_feedback" not in st.session_state:
    st.session_state.retrospective_feedback = None
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None

# Tab 1
with tab1:
    st.markdown("### Sprint Planner Interface")
    safe_exec("4.0AIchatbotsprint_FINAL_FULL.py")

# Tab 2
with tab2:
    st.markdown("### Retrospective Feedback Analysis")
    safe_exec("app.py")

# Tab 3
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
