import streamlit as st
import ast

st.set_page_config(page_title="Agile Suite", layout="wide")
st.title("🛠️ Agile Sprint Planner + Retrospective + AI Insights")

tab1, tab2, tab3 = st.tabs(["📅 Sprint Planner", "📊 Retrospective", "🤖 AI Suggestions"])

def safe_exec(file_path, tab_name):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Parse AST and remove st.set_page_config()
        class ConfigRemover(ast.NodeTransformer):
            def visit_Expr(self, node):
                if isinstance(node.value, ast.Call):
                    func = node.value.func
                    if isinstance(func, ast.Attribute):
                        if func.attr == "set_page_config" and getattr(func.value, 'id', '') == 'st':
                            return None
                return node

        tree = ast.parse(code, filename=file_path)
        cleaned_tree = ConfigRemover().visit(tree)
        ast.fix_missing_locations(cleaned_tree)
        cleaned_code = compile(cleaned_tree, filename="<ast>", mode="exec")
        exec(cleaned_code, globals())

    except Exception as e:
        st.error(f"❌ Error in {tab_name} tab running `{file_path}`:\n\n`{type(e).__name__}: {e}`")

# Shared state
if "retrospective_feedback" not in st.session_state:
    st.session_state.retrospective_feedback = None
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None

# Sprint Planner
with tab1:
    with st.container():
        st.markdown("### Sprint Planner")
        safe_exec("4.0AIchatbotsprint_FINAL_FULL.py", "Sprint Planner")

# Retrospective
with tab2:
    with st.container():
        st.markdown("### Retrospective Analysis")
        safe_exec("app.py", "Retrospective")

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
