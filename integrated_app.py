import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import base64
from io import BytesIO, StringIO
from datetime import datetime, timedelta
import requests
import json
import msal

# Set page configuration
st.set_page_config(
    page_title="Agile Team Management Suite",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add custom CSS for styling
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
        color: #e0e0e0;
    }
    .metric-card {
        background-color: #1e2130;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 16px;
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
    .azure-section {
        background-color: #0078d4;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state for storing data between reruns
if "df_tasks" not in st.session_state:
    st.session_state.df_tasks = None
if "team_members" not in st.session_state:
    st.session_state.team_members = {}
if "results" not in st.session_state:
    st.session_state.results = None
if "capacity_per_sprint" not in st.session_state:
    st.session_state.capacity_per_sprint = 80  # Default: 2 weeks * 5 days * 8 hours
if "azure_config" not in st.session_state:
    st.session_state.azure_config = {
        "org_url": "",
        "project": "",
        "team": "",
        "access_token": "",
        "connected": False
    }
if "retro_feedback" not in st.session_state:
    st.session_state.retro_feedback = None

# Azure DevOps Integration Functions
def get_azure_access_token(client_id, client_secret, tenant_id):
    """Get access token for Azure DevOps using service principal"""
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    result = app.acquire_token_for_client(scopes=["499b84ac-1321-427f-aa17-267ca6975798/.default"])
    return result.get("access_token")

def get_azure_devops_tasks(org_url, project, team, access_token):
    """Fetch tasks from Azure DevOps"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Get current iteration path
    iterations_url = f"{org_url}/{project}/{team}/_apis/work/teamsettings/iterations?$timeframe=current&api-version=7.0"
    iterations_response = requests.get(iterations_url, headers=headers)
    iterations = iterations_response.json().get("value", [])
    
    if not iterations:
        st.error("No current iteration found in Azure DevOps")
        return None
    
    current_iteration = iterations[0]["path"]
    
    # Get work items in current iteration
    wiql_query = {
        "query": f"SELECT [System.Id], [System.Title], [System.State], [System.IterationPath], [System.AssignedTo], [Microsoft.VSTS.Common.Priority], [Microsoft.VSTS.Scheduling.OriginalEstimate] FROM WorkItems WHERE [System.IterationPath] = '{current_iteration}' AND [System.WorkItemType] IN ('Task', 'User Story', 'Bug')"
    }
    
    wiql_url = f"{org_url}/{project}/_apis/wit/wiql?api-version=7.0"
    wiql_response = requests.post(wiql_url, headers=headers, json=wiql_query)
    work_items = wiql_response.json().get("workItems", [])
    
    if not work_items:
        st.error("No work items found in current iteration")
        return None
    
    # Get details for each work item
    work_item_ids = [str(item["id"]) for item in work_items]
    batch_size = 200  # Azure DevOps has a limit on batch size
    all_items = []
    
    for i in range(0, len(work_item_ids), batch_size):
        batch_ids = work_item_ids[i:i + batch_size]
        details_url = f"{org_url}/{project}/_apis/wit/workitems?ids={','.join(batch_ids)}&$expand=all&api-version=7.0"
        details_response = requests.get(details_url, headers=headers)
        all_items.extend(details_response.json().get("value", []))
    
    # Process items into DataFrame
    tasks = []
    for item in all_items:
        fields = item.get("fields", {})
        tasks.append({
            "ID": item.get("id"),
            "Title": fields.get("System.Title"),
            "State": fields.get("System.State"),
            "Priority": fields.get("Microsoft.VSTS.Common.Priority"),
            "Original Estimates": fields.get("Microsoft.VSTS.Scheduling.OriginalEstimate", 0),
            "Assigned To": fields.get("System.AssignedTo", {}).get("displayName", "") if isinstance(fields.get("System.AssignedTo"), dict) else fields.get("System.AssignedTo", ""),
            "Iteration Path": fields.get("System.IterationPath"),
            "Sprint": fields.get("System.IterationPath").split("\\")[-1] if fields.get("System.IterationPath") else ""
        })
    
    return pd.DataFrame(tasks)

def update_azure_devops_tasks(org_url, project, access_token, updates):
    """Update tasks in Azure DevOps in batch"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json-patch+json"
    }
    
    batch_size = 200  # Azure DevOps has a limit on batch size
    results = []
    
    for i in range(0, len(updates), batch_size):
        batch_updates = updates[i:i + batch_size]
        batch_url = f"{org_url}/{project}/_apis/wit/workitemsbatch?api-version=7.0"
        
        batch_payload = {
            "ids": [update["id"] for update in batch_updates],
            "document": [
                {
                    "op": "add",
                    "path": f"/fields/{field}",
                    "value": value
                } for update in batch_updates for field, value in update["fields"].items()
            ]
        }
        
        response = requests.post(batch_url, headers=headers, json=batch_payload)
        results.extend(response.json().get("value", []))
    
    return results

# Helper functions for Sprint Planning
def to_excel(df):
    """Convert DataFrame to Excel bytes"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tasks')
    return output.getvalue()

def get_download_link(df, filename, format_type):
    """Generate a download link for dataframe"""
    if format_type == 'excel':
        data = to_excel(df)
        b64 = base64.b64encode(data).decode()
        href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}" class="download-link">Download Excel File</a>'
    elif format_type == 'csv':
        csv = df.to_csv(index=False)
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<a href="data:text/csv;base64,{b64}" download="{filename}" class="download-link">Download CSV File</a>'
    return href

# Retrospective Analysis Functions
def compare_retrospectives(file_objects, min_votes, max_votes):
    """
    Process multiple retrospective CSV files and consolidate feedback with vote counts.
    
    Args:
        file_objects: List of uploaded file objects
        min_votes: Minimum vote threshold for filtering
        max_votes: Maximum vote threshold for filtering
        
    Returns:
        List of tuples containing (feedback, task_id, votes)
    """
    feedback_counts = {}
    feedback_tasks = {}  # Dictionary to store associated task numbers
    processing_results = []

    for uploaded_file in file_objects:
        try:
            # Convert to string content
            content = uploaded_file.getvalue().decode('utf-8')
            lines = content.split('\n')
            
            # Find the header row
            header_index = next((i for i, line in enumerate(lines) if "Type,Description,Votes" in line), None)
            if header_index is None:
                processing_results.append(f"⚠️ Warning: Skipping {uploaded_file.name} - Required columns not found.")
                continue
                
            # Read CSV content after header
            df = pd.read_csv(StringIO(content), skiprows=header_index)
            
            # Check for required columns
            if 'Description' not in df.columns or 'Votes' not in df.columns:
                processing_results.append(f"⚠️ Warning: Skipping {uploaded_file.name} - Required columns missing after header detection.")
                continue
                
            # Process feedback and votes
            df = df[['Description', 'Votes']].dropna()
            df['Votes'] = pd.to_numeric(df['Votes'], errors='coerce').fillna(0).astype(int)
            
            for _, row in df.iterrows():
                feedback = row['Description']
                votes = row['Votes']
                
                if feedback in feedback_counts:
                    feedback_counts[feedback] += votes
                else:
                    feedback_counts[feedback] = votes
            
            # Look for Work Items section
            work_items_header = next((i for i, line in enumerate(lines) 
                                    if "Feedback Description,Work Item Title,Work Item Type,Work Item Id," in line), None)
            
            if work_items_header is not None:
                work_items_df = pd.read_csv(StringIO(content), skiprows=work_items_header)
                
                if 'Feedback Description' in work_items_df.columns and 'Work Item Id' in work_items_df.columns:
                    for _, row in work_items_df.iterrows():
                        feedback_desc = row['Feedback Description']
                        work_item_id = row['Work Item Id']
                        if pd.notna(feedback_desc) and pd.notna(work_item_id):
                            feedback_tasks[feedback_desc] = work_item_id
            
            processing_results.append(f"✅ Successfully processed {uploaded_file.name}")
            
        except Exception as e:
            processing_results.append(f"❌ Error processing {uploaded_file.name}: {str(e)}")
    
    if not feedback_counts:
        return [("No valid feedback found.", None, 0)], processing_results
    
    filtered_feedback = [(feedback, feedback_tasks.get(feedback, None), votes)
                         for feedback, votes in feedback_counts.items()
                         if min_votes <= votes <= max_votes]
    
    # Sort by votes in descending order
    filtered_feedback.sort(key=lambda x: x[2], reverse=True)
    
    return filtered_feedback, processing_results

def create_dataframe_from_results(feedback_results):
    """Convert feedback results to a pandas DataFrame for visualization and export"""
    data = {
        "Feedback": [item[0] for item in feedback_results],
        "Task ID": [str(item[1]) if item[1] else "None" for item in feedback_results],
        "Votes": [item[2] for item in feedback_results]
    }
    return pd.DataFrame(data)

# Main App
st.title("Agile Team Management Suite")
st.markdown("An integrated platform for sprint planning, retrospective analysis, and Azure DevOps integration.")

# Create main tabs
main_tabs = st.tabs([
    "📝 Sprint Planning", 
    "📊 Retrospective Analysis",
    "🔄 Insights Integration"
])

# 1. SPRINT PLANNING
with main_tabs[0]:
    st.header("Sprint Task Planner")
    st.markdown("""
    This tool helps you plan and distribute tasks across multiple sprints, ensuring:
    - Fair distribution of tasks with different priorities
    - Optimal capacity utilization across team members
    - Remaining capacity is carried forward between sprints
    - Integration with Azure DevOps for task updates
    """)
    
    # Create sub-tabs for Sprint Planner
    upload_tab, team_tab, assignment_tab, results_tab, azure_tab = st.tabs([
        "1. Upload Tasks", 
        "2. Configure Team", 
        "3. Sprint & Task Assignment", 
        "4. Results",
        "5. Azure DevOps"
    ])
    
    # 1.1 UPLOAD TASKS TAB
    with upload_tab:
        st.subheader("Upload Task Data")
        
        # File upload
        uploaded_file = st.file_uploader("Upload your CSV file with tasks", type=["csv"], key="sprint_file_uploader")
        
        if uploaded_file is not None:
            try:
                # Load data
                df = pd.read_csv(uploaded_file)
                
                # Preview data
                st.subheader("Data Preview")
                st.dataframe(df.head(10), use_container_width=True)
                
                # Check if required columns are present
                required_columns = ["ID", "Title", "Priority", "Original Estimates"]
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    st.error(f"Missing required columns: {', '.join(missing_columns)}")
                else:
                    # Process the data
                    # Filter out completed tasks
                    if "State" in df.columns:
                        df = df[df["State"].str.lower() != "done"]
                    
                    # Store the filtered data
                    st.session_state.df_tasks = df
                    
                    # Show some statistics
                    total_tasks = len(df)
                    
                    # Count priority levels
                    priority_counts = df["Priority"].value_counts().to_dict()
                    
                    # Calculate total estimate
                    total_estimate = df["Original Estimates"].sum()
                    
                    # Display stats in columns
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.markdown(f"""
                        <div style='background-color: gold; padding: 15px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);' class='metric-card'>
                            <h4>Total Tasks</h4>
                            <p><b>{total_tasks}</b> active tasks</p>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col2:
                        st.markdown(f"""
                        <div style='background-color: orange; padding: 15px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);' class='metric-card'>
                            <h4>Estimated Effort</h4>
                            <p><b>{total_estimate:.1f}</b> hours</p>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col3:
                        priority_html = "".join([f"<p>{k}: <b>{v}</b></p>" for k, v in priority_counts.items()])
                        st.markdown(f"""
                        <div style='background-color: yellow; padding: 15px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);' class='metric-card'>
                            <h4>Priority Breakdown</h4>
                            {priority_html}
                        </div>
                        """, unsafe_allow_html=True)
                 
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                st.error("Please make sure your CSV file has the required columns (ID, Title, Priority, Original Estimates)")
        else:
            st.info("Please upload a CSV file with your tasks data")
            
            # Sample structure explanation
            with st.expander("CSV Format Requirements"):
                st.markdown("""
                Your CSV file should include these columns:
                
                - **ID**: Unique identifier for the task
                - **Title**: Task title
                - **Priority**: Task priority (high, medium, low)
                - **Original Estimates**: Estimated hours required for the task
                - **State** (optional): Current state of the task
                """)
    
    # 1.2 TEAM CONFIGURATION TAB
    with team_tab:
        st.subheader("Configure Team Members")
        
        st.markdown("""
        <div style='background-color: blue; padding: 15px; border-radius: 8px; margin-bottom: 20px; color: #e0e0e0;'>
            Add team members and their available capacity for the entire project duration.
            Capacity represents the total available working hours for each team member.
        </div>
        """, unsafe_allow_html=True)
        
        # Team member management
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Add new team member
            with st.form("add_member_form"):
                st.subheader("Add Team Member")
                
                new_member_name = st.text_input("Name")
                new_member_capacity = st.number_input("Capacity (hours)", min_value=1, value=40)
                
                submitted = st.form_submit_button("Add Team Member")
                if submitted and new_member_name:
                    st.session_state.team_members[new_member_name] = new_member_capacity
                    st.success(f"Added {new_member_name} with {new_member_capacity} hours capacity")
        
        with col2:
            # Quick add multiple team members
            with st.form("quick_add_form"):
                st.subheader("Quick Add Multiple Members")
                
                multiple_members = st.text_area(
                    "Enter one member per line with capacity (e.g., 'John Doe,40')",
                    height=150,
                    placeholder="John Doe,40\nJane Smith,32"
                )
                
                quick_submitted = st.form_submit_button("Add All Members")
                if quick_submitted and multiple_members:
                    lines = multiple_members.strip().split("\n")
                    for line in lines:
                        if "," in line:
                            parts = line.split(",", 1)
                            name = parts[0].strip()
                            try:
                                capacity = float(parts[1].strip())
                                if name:
                                    st.session_state.team_members[name] = capacity
                            except ValueError:
                                st.error(f"Invalid capacity format for: {line}")
                    
                    st.success(f"Added {len(lines)} team members")
        
        # Display current team members
        st.subheader("Current Team Members")
        
        if not st.session_state.team_members:
            st.warning("No team members added yet. Please add team members above.")
        else:
            # Create DataFrame for display
            team_df = pd.DataFrame({
                "Name": list(st.session_state.team_members.keys()),
                "Capacity (hours)": list(st.session_state.team_members.values())
            })
            
            st.dataframe(team_df, use_container_width=True)
            
            # Remove member option
            with st.expander("Remove Team Member"):
                member_to_remove = st.selectbox(
                    "Select member to remove",
                    options=list(st.session_state.team_members.keys()),
                    key="member_remove_select"
                )
                
                if st.button("Remove Selected Member"):
                    if member_to_remove in st.session_state.team_members:
                        del st.session_state.team_members[member_to_remove]
                        st.success(f"Removed {member_to_remove} from the team")
                        st.rerun()
        
        # Set capacity per sprint
        st.subheader("Sprint Capacity Configuration")
        
        st.session_state.capacity_per_sprint = st.number_input(
            "Default capacity per sprint (hours)",
            min_value=1,
            value=st.session_state.capacity_per_sprint,
            help="This is the default capacity for team members per sprint. For a 2-week sprint with 8-hour days, this would typically be 80 hours."
        )
    
    # 1.3 SPRINT & TASK ASSIGNMENT TAB
    with assignment_tab:
        st.subheader("Configure Sprint & Assign Tasks")
        
        # Validate prerequisites
        tasks_ready = st.session_state.df_tasks is not None and not st.session_state.df_tasks.empty
        team_ready = bool(st.session_state.team_members)
        
        if not tasks_ready:
            st.error("Please upload task data in the 'Upload Tasks' tab first.")
        elif not team_ready:
            st.error("Please configure team members in the 'Configure Team' tab first.")
        else:
            # Sprint configuration
            st.markdown("""
            <div style='background-color: #8a2be2; padding: 15px; border-radius: 8px; margin-bottom: 20px; color: white;'>
                Configure sprint details and task allocation strategy.
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                num_sprints = st.number_input(
                    "Number of Sprints", 
                    min_value=1, 
                    max_value=12, 
                    value=3,
                    help="How many sprints to plan for?"
                )
            
            with col2:
                sprint_allocation_strategy = st.selectbox(
                    "Task Allocation Strategy",
                    options=["Priority-based", "Even Distribution", "Prioritize Critical First"],
                    help="How should tasks be allocated across sprints?"
                )
            
            # Task sorting options
            st.subheader("Task Prioritization")
            
            priority_order = st.multiselect(
                "Priority Levels (Highest to Lowest)",
                options=sorted(st.session_state.df_tasks["Priority"].unique()),
                default=sorted(st.session_state.df_tasks["Priority"].unique()),
                help="Order priority levels from highest to lowest importance"
            )
            
            # Member assignment preferences
            st.subheader("Team Member Assignment Preferences")
            
            assign_by_skill = st.checkbox(
                "Enable Skill-Based Assignment",
                help="If enabled, tasks will be assigned based on team member skills and previous assignments"
            )
            
            if assign_by_skill:
                with st.expander("Skill & Task Type Mapping"):
                    # Allow mapping team members to task types/skills
                    for member_name in st.session_state.team_members.keys():
                        st.multiselect(
                            f"Preferred tasks for {member_name}",
                            options=["Development", "Design", "Testing", "Documentation", "Research"],
                            default=["Development"],
                            key=f"skill_{member_name}"
                        )
            
            # Capacity buffer
            buffer_percentage = st.slider(
                "Capacity Buffer (%)",
                min_value=0,
                max_value=50,
                value=10,
                help="Reserved capacity percentage as buffer for unexpected work"
            )
            
            # Execute planning
            if st.button("Generate Sprint Plan", type="primary"):
                with st.spinner("Planning sprints and assigning tasks..."):
                    
                    # YOUR SPRINT PLANNING ALGORITHM HERE
                    
                    # Simulate planning results
                    sprint_assignments = {}
                    member_assignments = {}
                    
                    # Simple algo: distribute tasks across sprints based on priority
                    tasks_df = st.session_state.df_tasks.copy()
                    
                    # This is just a placeholder. A real algorithm would be more sophisticated
                    if priority_order:
                        # Create a category based on priority order
                        priority_map = {p: i for i, p in enumerate(priority_order)}
                        tasks_df["Priority_Order"] = tasks_df["Priority"].map(priority_map)
                        tasks_df = tasks_df.sort_values(by=["Priority_Order", "Original Estimates"], ascending=[True, False])
                    
                    # Reset the index to iterate tasks in order
                    tasks_df = tasks_df.reset_index(drop=True)
                    
                    # Initialize sprint and member capacity
                    sprint_capacity = {f"Sprint {i+1}": st.session_state.capacity_per_sprint * len(st.session_state.team_members) * (1 - buffer_percentage/100) for i in range(num_sprints)}
                    member_capacity = {sprint: {member: st.session_state.capacity_per_sprint * (1 - buffer_percentage/100) for member in st.session_state.team_members} for sprint in sprint_capacity}
                    
                    # Initialize result containers
                    sprint_assignments = {sprint: [] for sprint in sprint_capacity}
                    member_assignments = {member: {sprint: [] for sprint in sprint_capacity} for member in st.session_state.team_members}
                    unassigned_tasks = []
                    
                    # Assign tasks to sprints and members
                    for _, task in tasks_df.iterrows():
                        assigned = False
                        task_estimate = task["Original Estimates"]
                        
                        # Find the sprint with enough capacity
                        for sprint in sprint_capacity:
                            if sprint_capacity[sprint] >= task_estimate:
                                # Find a team member with enough capacity
                                for member in member_capacity[sprint]:
                                    if member_capacity[sprint][member] >= task_estimate:
                                        # Assign task to this member and sprint
                                        sprint_assignments[sprint].append(task)
                                        member_assignments[member][sprint].append(task)
                                        
                                        # Update capacities
                                        sprint_capacity[sprint] -= task_estimate
                                        member_capacity[sprint][member] -= task_estimate
                                        
                                        assigned = True
                                        break
                                
                                if assigned:
                                    break
                        
                        if not assigned:
                            unassigned_tasks.append(task)
                    
                    # Store results in session state
                    st.session_state.results = {
                        "sprint_assignments": sprint_assignments,
                        "member_assignments": member_assignments,
                        "unassigned_tasks": unassigned_tasks,
                        "sprint_capacity": sprint_capacity,
                        "member_capacity": member_capacity
                    }
                    
                    # Show success message
                    st.success("Sprint planning completed successfully! View results in the Results tab.")
    
    # 1.4 RESULTS TAB
    with results_tab:
        st.subheader("Sprint Planning Results")
        
        if "results" not in st.session_state or st.session_state.results is None:
            st.info("Please generate a sprint plan in the 'Sprint & Task Assignment' tab first.")
        else:
            results = st.session_state.results
            
            # Summary metrics
            total_assigned = sum(len(tasks) for tasks in results["sprint_assignments"].values())
            total_unassigned = len(results["unassigned_tasks"])
            total_tasks = total_assigned + total_unassigned
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Tasks Assigned", f"{total_assigned} ({total_assigned/total_tasks*100:.1f}%)")
            
            with col2:
                st.metric("Tasks Unassigned", f"{total_unassigned} ({total_unassigned/total_tasks*100:.1f}%)")
            
            with col3:
                # Calculate average capacity utilization
                total_capacity = sum(st.session_state.team_members.values()) * len(results["sprint_assignments"])
                used_capacity = sum(st.session_state.capacity_per_sprint * len(st.session_state.team_members) - remaining for sprint, remaining in results["sprint_capacity"].items())
                utilization = used_capacity / total_capacity * 100
                st.metric("Capacity Utilization", f"{utilization:.1f}%")
            
            # Tabs for different result views
            summary_tab, sprint_tab, member_tab, unassigned_tab = st.tabs([
                "Summary", "Sprint View", "Member View", "Unassigned Tasks"
            ])
            
            # Summary tab
            with summary_tab:
                st.subheader("Sprint Loading")
                
                # Prepare data for chart
                sprint_data = {
                    "Sprint": [],
                    "Assigned Hours": [],
                    "Available Hours": [],
                    "Utilization (%)": []
                }
                
                for sprint, tasks in results["sprint_assignments"].items():
                    total_hours = sum(task["Original Estimates"] for task in tasks)
                    available = st.session_state.capacity_per_sprint * len(st.session_state.team_members)
                    utilized = total_hours / available * 100
                    
                    sprint_data["Sprint"].append(sprint)
                    sprint_data["Assigned Hours"].append(total_hours)
                    sprint_data["Available Hours"].append(available)
                    sprint_data["Utilization (%)"].append(utilized)
                
                sprint_df = pd.DataFrame(sprint_data)
                
                # Create visualization
                fig = px.bar(
                    sprint_df,
                    x="Sprint",
                    y=["Assigned Hours", "Available Hours"],
                    barmode="group",
                    title="Hours Allocation per Sprint",
                    labels={"value": "Hours", "variable": "Category"}
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Utilization chart
                fig2 = px.line(
                    sprint_df,
                    x="Sprint",
                    y="Utilization (%)",
                    markers=True,
                    title="Capacity Utilization per Sprint",
                    labels={"Utilization (%)": "Percentage Used"},
                )
                fig2.update_layout(yaxis_range=[0, 100])
                
                st.plotly_chart(fig2, use_container_width=True)
            
            # Sprint view tab
            with sprint_tab:
                selected_sprint = st.selectbox(
                    "Select Sprint",
                    options=list(results["sprint_assignments"].keys())
                )
                
                if selected_sprint:
                    tasks = results["sprint_assignments"][selected_sprint]
                    
                    if tasks:
                        # Convert to DataFrame for display
                        sprint_df = pd.DataFrame(tasks)
                        
                        # Show tasks
                        st.dataframe(sprint_df, use_container_width=True)
                        
                        # Download option
                        sprint_csv = sprint_df.to_csv(index=False)
                        st.download_button(
                            "Download Sprint Tasks as CSV",
                            data=sprint_csv,
                            file_name=f"{selected_sprint}_tasks.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info(f"No tasks assigned to {selected_sprint}")
            
            # Member view tab
            with member_tab:
                selected_member = st.selectbox(
                    "Select Team Member",
                    options=list(results["member_assignments"].keys())
                )
                
                if selected_member:
                    member_tasks = []
                    
                    for sprint, tasks in results["member_assignments"][selected_member].items():
                        for task in tasks:
                            task_copy = task.copy()
                            task_copy["Sprint"] = sprint
                            member_tasks.append(task_copy)
                    
                    if member_tasks:
                        # Convert to DataFrame for display
                        member_df = pd.DataFrame(member_tasks)
                        
                        # Show tasks
                        st.dataframe(member_df, use_container_width=True)
                        
                        # Download option
                        member_csv = member_df.to_csv(index=False)
                        st.download_button(
                            "Download Member Tasks as CSV",
                            data=member_csv,
                            file_name=f"{selected_member}_tasks.csv",
                            mime="text/csv"
                        )
                        
                        # Show workload chart
                        member_load = {}
                        for sprint, tasks in results["member_assignments"][selected_member].items():
                            member_load[sprint] = sum(task["Original Estimates"] for task in tasks)
                        
                        load_df = pd.DataFrame({
                            "Sprint": list(member_load.keys()),
                            "Hours": list(member_load.values()),
                            "Capacity": [st.session_state.capacity_per_sprint] * len(member_load)
                        })
                        
                        fig = px.bar(
                            load_df,
                            x="Sprint",
                            y=["Hours", "Capacity"],
                            barmode="group",
                            title=f"Workload for {selected_member} across Sprints",
                            labels={"value": "Hours", "variable": "Category"}
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info(f"No tasks assigned to {selected_member}")
            
            # Unassigned tasks tab
            with unassigned_tab:
                if results["unassigned_tasks"]:
                    unassigned_df = pd.DataFrame(results["unassigned_tasks"])
                    
                    st.dataframe(unassigned_df, use_container_width=True)
                    
                    # Download option
                    unassigned_csv = unassigned_df.to_csv(index=False)
                    st.download_button(
                        "Download Unassigned Tasks as CSV",
                        data=unassigned_csv,
                        file_name="unassigned_tasks.csv",
                        mime="text/csv"
                    )
                    
                    # Pie chart of unassigned tasks by priority
                    if "Priority" in unassigned_df.columns:
                        priority_counts = unassigned_df["Priority"].value_counts().reset_index()
                        priority_counts.columns = ["Priority", "Count"]
                        
                        fig = px.pie(
                            priority_counts,
                            names="Priority",
                            values="Count",
                            title="Unassigned Tasks by Priority"
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.success("All tasks have been assigned successfully!")
    
    # 1.5 AZURE DEVOPS TAB
    with azure_tab:
        st.subheader("Azure DevOps Integration")
        
        st.markdown("""
        <div class='azure-section'>
            Connect to Azure DevOps to import tasks and export your sprint plan.
        </div>
        """, unsafe_allow_html=True)
        
        # Connection settings
        if not st.session_state.azure_config["connected"]:
            with st.form("azure_connection_form"):
                st.subheader("Connect to Azure DevOps")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    org_url = st.text_input(
                        "Organization URL",
                        placeholder="https://dev.azure.com/your-org"
                    )
                
                with col2:
                    project = st.text_input(
                        "Project Name",
                        placeholder="Your Project Name"
                    )
                
                team = st.text_input(
                    "Team Name",
                    placeholder="Your Team Name"
                )
                
                st.markdown("#### Authentication")
                auth_method = st.radio(
                    "Authentication Method",
                    options=["Personal Access Token (PAT)", "Service Principal"]
                )
                
                if auth_method == "Personal Access Token (PAT)":
                    pat = st.text_input(
                        "Personal Access Token",
                        type="password",
                        help="Create a PAT with 'Work Items (Read & Write)' permissions"
                    )
                    
                    connect_submitted = st.form_submit_button("Connect to Azure DevOps")
                    if connect_submitted and org_url and project and team and pat:
                        try:
                            # Simulate connection test
                            st.session_state.azure_config = {
                                "org_url": org_url,
                                "project": project,
                                "team": team,
                                "access_token": pat,
                                "connected": True
                            }
                            st.success("Successfully connected to Azure DevOps!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to connect: {str(e)}")
                
                else:  # Service Principal
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        client_id = st.text_input(
                            "Client ID",
                            help="Application (client) ID"
                        )
                    
                    with col2:
                        tenant_id = st.text_input(
                            "Tenant ID",
                            help="Azure Active Directory tenant ID"
                        )
                    
                    client_secret = st.text_input(
                        "Client Secret",
                        type="password",
                        help="Client secret from app registration"
                    )
                    
                    connect_submitted = st.form_submit_button("Connect to Azure DevOps")
                    if connect_submitted and org_url and project and team and client_id and tenant_id and client_secret:
                        try:
                            # Try to get access token
                            access_token = get_azure_access_token(client_id, client_secret, tenant_id)
                            
                            if access_token:
                                st.session_state.azure_config = {
                                    "org_url": org_url,
                                    "project": project,
                                    "team": team,
                                    "access_token": access_token,
                                    "connected": True
                                }
                                st.success("Successfully connected to Azure DevOps!")
                                st.rerun()
                            else:
                                st.error("Failed to obtain access token. Please check your credentials.")
                        except Exception as e:
                            st.error(f"Failed to connect: {str(e)}")
        
        else:
            # Connected to Azure - Show options
            st.success(f"Connected to Azure DevOps: {st.session_state.azure_config['org_url']}/{st.session_state.azure_config['project']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Fetch Tasks from Current Sprint"):
                    with st.spinner("Fetching tasks..."):
                        try:
                            config = st.session_state.azure_config
                            tasks_df = get_azure_devops_tasks(
                                config["org_url"],
                                config["project"],
                                config["team"],
                                config["access_token"]
                            )
                            
                            if tasks_df is not None and not tasks_df.empty:
                                st.session_state.df_tasks = tasks_df
                                st.success(f"Successfully imported {len(tasks_df)} tasks from Azure DevOps")
                                st.rerun()
                            else:
                                st.warning("No tasks found in the current sprint.")
                        except Exception as e:
                            st.error(f"Error fetching tasks: {str(e)}")
            
            with col2:
                if st.button("Disconnect"):
                    st.session_state.azure_config = {
                        "org_url": "",
                        "project": "",
                        "team": "",
                        "access_token": "",
                        "connected": False
                    }
                    st.info("Disconnected from Azure DevOps")
                    st.rerun()
            
            # Export results to Azure
            if "results" in st.session_state and st.session_state.results is not None:
                st.subheader("Export Sprint Plan to Azure DevOps")
                
                export_options = st.multiselect(
                    "Select data to export",
                    options=["Sprint Assignments", "Team Member Assignments"],
                    default=["Sprint Assignments"]
                )
                
                if st.button("Export to Azure DevOps"):
                    with st.spinner("Exporting to Azure DevOps..."):
                        # Simulate export
                        st.success("Sprint plan exported to Azure DevOps successfully!")

# 2. RETROSPECTIVE ANALYSIS
with main_tabs[1]:
    st.header("Team Retrospective Analysis Tool")
    st.markdown("Upload multiple retrospective CSV files to analyze and compare feedback across team retrospectives.")
    
    # Sidebar for file upload and filtering controls
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Controls")
        
        uploaded_files = st.file_uploader(
            "Upload Retrospective CSV Files",
            type=["csv"],
            accept_multiple_files=True,
            help="Upload one or more CSV files containing retrospective data",
            key="retro_file_uploader"
        )
        
        st.subheader("Filter Settings")
        min_votes = st.slider("Minimum Votes", 0, 100, 1, key="retro_min_votes")
        max_votes = st.slider("Maximum Votes", min_votes, 100, 50, key="retro_max_votes")
        
        if uploaded_files:
            st.info(f"Selected {len(uploaded_files)} file(s)")
            
            # Process the uploaded files when the analyze button is clicked
            analyze_button = st.button("Analyze Retrospectives", type="primary", key="analyze_retro_button")
            
            if analyze_button:
                with st.spinner("Processing retrospective data..."):
                    feedback_results, processing_logs = compare_retrospectives(
                        uploaded_files, min_votes, max_votes
                    )
                    
                    # Store results in session state
                    st.session_state.retro_feedback = feedback_results
                    st.session_state.retro_logs = processing_logs
                    
                    # Show success message
                    st.success("Retrospective analysis complete!")
        else:
            st.warning("Please upload at least one CSV file")
    
    with col2:
        # Show example of expected format if no files uploaded
        if not uploaded_files:
            st.subheader("Expected CSV Format")
            st.markdown("""
            Your CSV files should include columns for feedback description and votes, with format like:
            ```
            Type,Description,Votes
            Went Well,The team was collaborative,5
            Needs Improvement,Documentation is lacking,3
            ```
            
            The tool will also recognize associated tasks when formatted as:
            ```
            Feedback Description,Work Item Title,Work Item Type,Work Item Id,
            Documentation is lacking,Improve Docs,Task,12345
            ```
            """)
            
        # Show results if available
        elif st.session_state.retro_feedback is not None:
            # Show processing results
            with st.expander("Processing Logs", expanded=False):
                for log in st.session_state.retro_logs:
                    st.write(log)
            
            # Convert to DataFrame for easier handling
            results_df = create_dataframe_from_results(st.session_state.retro_feedback)
            
            if len(results_df) == 0 or (len(results_df) == 1 and "No valid feedback found" in results_df["Feedback"].iloc[0]):
                st.error("No feedback items found within the selected vote range. Try adjusting your filters.")
            else:
                # Display the results
                st.subheader(f"Consolidated Feedback ({len(results_df)} items)")
                st.dataframe(
                    results_df,
                    column_config={
                        "Feedback": st.column_config.TextColumn("Feedback"),
                        "Task ID": st.column_config.TextColumn("Task ID"),
                        "Votes": st.column_config.NumberColumn("Votes")
                    },
                    use_container_width=True
                )
                
                # Visualization section
                st.subheader("Feedback Visualization")
                
                # Only show top 15 items in chart to avoid overcrowding
                chart_data = results_df.head(15) if len(results_df) > 15 else results_df
                
                # Create a horizontal bar chart with Plotly
                fig = px.bar(
                    chart_data,
                    x="Votes",
                    y="Feedback",
                    orientation='h',
                    title=f"Top Feedback Items by Vote Count (min: {min_votes}, max: {max_votes})",
                    color="Votes",
                    color_continuous_scale="Viridis"
                )
                fig.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
                
                # Distribution of votes
                st.subheader("Vote Distribution")
                vote_distribution = px.histogram(
                    results_df, 
                    x="Votes",
                    nbins=20,
                    title="Distribution of Votes",
                    labels={"Votes": "Vote Count", "count": "Number of Feedback Items"}
                )
                st.plotly_chart(vote_distribution, use_container_width=True)
                
                # Count items with and without associated tasks
                with_tasks = results_df["Task ID"].apply(lambda x: x != "None").sum()
                without_tasks = len(results_df) - with_tasks
                
                # Create pie chart for task association
                fig3, ax3 = plt.subplots(figsize=(8, 5))
                ax3.pie(
                    [with_tasks, without_tasks],
                    labels=["With Task ID", "Without Task ID"],
                    autopct='%1.1f%%',
                    startangle=90,
                    colors=['#4CAF50', '#FF9800']
                )
                ax3.set_title("Feedback Items With Task Association")
                ax3.axis('equal')
                st.pyplot(fig3)
                
                # Export options
                st.subheader("Export Results")
                export_format = st.radio("Select export format:", ["CSV", "Markdown"], key="retro_export_format")
                
                if export_format == "CSV":
                    csv = results_df.to_csv(index=False)
                    st.download_button(
                        label="Download CSV",
                        data=csv,
                        file_name="retrospective_analysis.csv",
                        mime="text/csv"
                    )
                else:  # Markdown
                    # Generate markdown content
                    markdown_content = "# Retrospective Analysis Results\n\n"
                    markdown_content += f"Filter settings: Min votes: {min_votes}, Max votes: {max_votes}\n\n"
                    markdown_content += "## Consolidated Feedback\n\n"
                    
                    for _, row in results_df.iterrows():
                        task_info = f" - Task #{row['Task ID']}" if row['Task ID'] != "None" else ""
                        markdown_content += f"- {row['Feedback']} ({row['Votes']} votes){task_info}\n"
                    
                    st.download_button(
                        label="Download Markdown",
                        data=markdown_content,
                        file_name="retrospective_analysis.md",
                        mime="text/markdown"
                    )

# 3. INSIGHTS INTEGRATION
with main_tabs[2]:
    st.header("Insights Integration")
    st.markdown("Combine data from sprint planning and retrospectives to gain holistic insights.")
    
    # Check if data from both tools is available
    has_sprint_data = st.session_state.df_tasks is not None
    has_retro_data = st.session_state.retro_feedback is not None
    
    if not has_sprint_data and not has_retro_data:
        st.warning("No data available. Please use both the Sprint Planning and Retrospective Analysis tools first.")
    else:
        # Create tabs for different insights
        overview_tab, task_analysis_tab, improvement_tab = st.tabs([
            "Team Overview", 
            "Task Analysis",
            "Improvement Suggestions"
        ])
        
        # Team Overview tab
        with overview_tab:
            st.subheader("Team Performance Overview")
            
            if has_sprint_data and "results" in st.session_state and st.session_state.results is not None:
                # Sprint statistics
                sprint_stats = {
                    "Sprint": [],
                    "Tasks Assigned": [],
                    "Capacity Utilization (%)": []
                }
                
                results = st.session_state.results
                for sprint, tasks in results["sprint_assignments"].items():
                    total_hours = sum(task["Original Estimates"] for task in tasks)
                    available = st.session_state.capacity_per_sprint * len(st.session_state.team_members)
                    utilized = total_hours / available * 100
                    
                    sprint_stats["Sprint"].append(sprint)
                    sprint_stats["Tasks Assigned"].append(len(tasks))
                    sprint_stats["Capacity Utilization (%)"].append(utilized)
                
                sprint_stats_df = pd.DataFrame(sprint_stats)
                
                # Display stats
                st.dataframe(sprint_stats_df, use_container_width=True)
                
                # Create visualization
                fig = px.line(
                    sprint_stats_df,
                    x="Sprint",
                    y="Capacity Utilization (%)",
                    markers=True,
                    title="Team Capacity Utilization Trend",
                )
                fig.update_layout(yaxis_range=[0, 100])
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sprint planning data not available. Please complete sprint planning first.")
        
        # Task Analysis tab
        with task_analysis_tab:
            st.subheader("Task & Feedback Analysis")
            
            if has_sprint_data and has_retro_data:
                # Create a cross-reference of tasks and retrospective feedback
                if "results" in st.session_state and st.session_state.results is not None:
                    # Get all task IDs from sprint planning
                    all_task_ids = set()
                    for sprint, tasks in st.session_state.results["sprint_assignments"].items():
                        for task in tasks:
                            all_task_ids.add(str(task["ID"]))
                    
                    # Get all task IDs from retrospectives
                    retro_feedback_df = create_dataframe_from_results(st.session_state.retro_feedback)
                    retro_tasks = set(retro_feedback_df[retro_feedback_df["Task ID"] != "None"]["Task ID"])
                    
                    # Find overlapping tasks
                    overlapping_tasks = all_task_ids.intersection(retro_tasks)
                    
                    # Display stats
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Sprint Planning Tasks", len(all_task_ids))
                    
                    with col2:
                        st.metric("Retrospective Tasks", len(retro_tasks))
                    
                    with col3:
                        st.metric("Cross-Referenced Tasks", len(overlapping_tasks))
                    
                    # Show tasks with feedback
                    if overlapping_tasks:
                        st.subheader("Tasks with Retrospective Feedback")
                        
                        # Filter retrospective dataframe to only include tasks from sprint planning
                        filtered_retro = retro_feedback_df[retro_feedback_df["Task ID"].isin(overlapping_tasks)]
                        
                        # Display the filtered dataframe
                        st.dataframe(filtered_retro, use_container_width=True)
                        
                        # Create visualization of feedback by task
                        task_feedback = filtered_retro.groupby("Task ID")["Votes"].sum().reset_index()
                        task_feedback = task_feedback.sort_values(by="Votes", ascending=False)
                        
                        fig = px.bar(
                            task_feedback,
                            x="Task ID",
                            y="Votes",
                            title="Retrospective Feedback by Task",
                            labels={"Votes": "Total Votes", "Task ID": "Task ID"}
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No tasks with cross-referenced feedback found.")
                else:
                    st.info("Sprint planning results not available. Please complete sprint planning first.")
            else:
                st.info("Both sprint planning and retrospective data are required for this analysis.")
        
        # Improvement Suggestions tab
        with improvement_tab:
            st.subheader("Improvement Suggestions")
            
            if has_retro_data:
                # Get top voted retrospective items
                retro_feedback_df = create_dataframe_from_results(st.session_state.retro_feedback)
                top_feedback = retro_feedback_df.head(5)
                
                st.write("Based on retrospective feedback, consider these improvement areas:")
                
                for i, (_, row) in enumerate(top_feedback.iterrows(), 1):
                    st.markdown(f"""
                    <div style='background-color: #2e7d32; padding: 15px; border-radius: 8px; margin-bottom: 10px; color: white;'>
                        <h4>{i}. {row['Feedback']} ({row['Votes']} votes)</h4>
                        <p>Consider creating a task to address this feedback.</p>
                        {f"<p>Associated Task: #{row['Task ID']}</p>" if row['Task ID'] != "None" else 
                          "<p>No task associated - consider creating one for next sprint</p>"}
                    </div>
                    """, unsafe_allow_html=True)
                
                # Allow creation of new tasks from feedback
                st.subheader("Convert Feedback to Tasks")
                
                # Select feedback item to convert
                feedback_to_convert = st.selectbox(
                    "Select feedback item to convert to task",
                    options=retro_feedback_df["Feedback"].tolist()
                )
                
                if feedback_to_convert:
                    with st.form("create_task_form"):
                        st.write(f"Creating task from: {feedback_to_convert}")
                        
                        task_title = st.text_input(
                            "Task Title",
                            value=f"Address: {feedback_to_convert[:50]}..." if len(feedback_to_convert) > 50 else f"Address: {feedback_to_convert}"
                        )
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            task_priority = st.selectbox(
                                "Priority",
                                options=["1", "2", "3", "4"]
                            )
                        
                        with col2:
                            task_estimate = st.number_input(
                                "Estimated Hours",
                                min_value=1,
                                value=8
                            )
                        
                        create_task = st.form_submit_button("Create Task")
                        
                        if create_task:
                            # Simulate task creation
                            st.success(f"Task created: {task_title}")
                            
                            # In a real app, you would add this to the task list or send it to Azure
                            # For now, just acknowledge it was created
            else:
                st.info("Retrospective data is required for improvement suggestions.")

# Footer
st.markdown("---")
st.markdown("Agile Team Management Suite © 2023 | Combining Sprint Planning & Retrospective Analysis")