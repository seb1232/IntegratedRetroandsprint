import streamlit as st
import tokenize
from io import StringIO

def safe_exec(file_path, tab_name=""):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Completely remove any line containing st.set_page_config
        # Preserve indentation by checking with tokenizer
        cleaned_lines = []
        skip_next_indent = False

        for line in lines:
            if "st.set_page_config" in line:
                continue  # skip the config line

            # Skip if previous line indicated an indent block (avoid incomplete indents)
            if skip_next_indent and (line.startswith(" ") or line.startswith("\t")):
                continue
            else:
                skip_next_indent = False

            cleaned_lines.append(line)

        cleaned_code = "".join(cleaned_lines)
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
