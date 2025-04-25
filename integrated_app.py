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
        st.header("Configure Team Members")
        
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
                    "Enter one member per line with format: Name,Capacity", 
                    placeholder="John,40\nJane,35\nBob,20"
                )
                
                submitted = st.form_submit_button("Add All")
                if submitted and multiple_members:
                    lines = multiple_members.strip().split("\n")
                    for line in lines:
                        if "," in line:
                            parts = line.split(",")
                            name = parts[0].strip()
                            try:
                                capacity = float(parts[1].strip())
                                st.session_state.team_members[name] = capacity
                            except ValueError:
                                st.error(f"Invalid capacity for {name}")
                    st.success(f"Added {len(lines)} team members")
        
        # Display current team
        st.subheader("Current Team")
        
        if st.session_state.team_members:
            # Convert to DataFrame for display
            team_df = pd.DataFrame(
                {"Name": list(st.session_state.team_members.keys()),
                 "Capacity (hours)": list(st.session_state.team_members.values())}
            )
            
            # Display the dataframe with edit and delete buttons
            st.dataframe(team_df, use_container_width=True)
            
            # Total capacity
            total_capacity = sum(st.session_state.team_members.values())
            st.info(f"Total team capacity: {total_capacity} hours")
            
            # Clear team
            if st.button("Clear Team"):
                st.session_state.team_members = {}
                st.success("Team cleared")
        else:
            st.info("No team members added yet")
    
    # 1.3 SPRINT & TASK ASSIGNMENT TAB
    # 3. TASK ASSIGNMENT TAB
    with assignment_tab:
        st.header("Sprint & Task Assignment")
        
        if st.session_state.df_tasks is None:
            st.warning("Please upload tasks data in the Upload Tasks tab first.")
        elif not st.session_state.team_members:
            st.warning("Please add team members in the Configure Team tab first.")
        else:
            st.markdown("""
            <div style='background-color: #1b5e20; padding: 15px; border-radius: 8px; margin-bottom: 20px; color: #e0e0e0;'>
                <h3 style='margin-top: 0;'>Sprint-Based Priority-Balanced Task Assignment</h3>
                <p>This algorithm distributes work to ensure team members get a fair mix of high, medium, and low priority tasks across multiple sprints.</p>
                <p>Every team member will receive tasks from all priority levels rather than one person getting all high-priority tasks.</p>
                <p>Remaining capacity from earlier sprints will be carried forward to subsequent sprints.</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Sprint Configuration Section
            st.subheader("Sprint Configuration")
            
            # Default sprint duration in weeks
            sprint_duration = st.number_input(
                "Sprint Duration (weeks)",
                min_value=1,
                max_value=4,
                value=2,
                help="Duration of each sprint in weeks"
            )
            
            # Number of sprints
            num_sprints = st.number_input(
                "Number of Sprints",
                min_value=1,
                max_value=12,
                value=3,
                help="Number of sprints to plan for"
            )
            
            # Working days per week
            days_per_week = st.number_input(
                "Working Days per Week",
                min_value=1,
                max_value=7,
                value=5,
                help="Number of working days per week"
            )
            
            # Hours per day
            hours_per_day = st.number_input(
                "Working Hours per Day",
                min_value=1,
                max_value=24,
                value=8,
                help="Number of working hours per day"
            )
            
            # Calculate total hours per sprint
            # This will be used to adjust the team members' capacities for each sprint
            st.session_state.capacity_per_sprint = sprint_duration * days_per_week * hours_per_day
            
            # Let user know how many hours each sprint represents
            st.info(f"Each sprint represents {st.session_state.capacity_per_sprint} working hours per team member (assuming full capacity).")
            
            # Assignment Options
            st.subheader("Assignment Options")
            
            col1, col2 = st.columns(2)
            
            with col1:
                priority_balance = st.slider(
                    "Priority Balance",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.7,
                    step=0.1,
                    help="Higher values (0.7-1.0) ensure everyone gets a mix of high/medium/low tasks. Lower values focus more on capacity utilization. Default (0.7) gives a good balance."
                )
            
            with col2:
                respect_category = st.checkbox(
                    "Consider Category Specialization",
                    value=False,
                    help="When enabled, members will be assigned tasks from their specialized categories when possible"
                )
                
            # Assignment button
            if st.button("Run Assignment", type="primary", use_container_width=True):
                # Get the data
                df = st.session_state.df_tasks.copy()
                team_members = st.session_state.team_members
                
                # Check for required columns
                required_columns = ["Priority", "Original Estimates"]
                if not all(col in df.columns for col in required_columns):
                    st.error(f"CSV must contain these columns: {', '.join(required_columns)}")
                else:
                    with st.spinner("Assigning tasks across sprints..."):
                        # Prepare data
                        assigned_hours = {member: 0 for member in team_members}
                        assigned_priorities = {member: {"high": 0, "medium": 0, "low": 0, "other": 0} for member in team_members}
                        
                        # Add columns if missing or reset them
                        if "Assigned To" not in df.columns:
                            df["Assigned To"] = ""
                        else:
                            df["Assigned To"] = ""  # Reset assignments
                            
                        if "Iteration Path" not in df.columns:
                            df["Iteration Path"] = ""
                        else:
                            df["Iteration Path"] = ""  # Reset iteration paths
                        
                        if "Sprint" not in df.columns:
                            df["Sprint"] = ""
                        else:
                            df["Sprint"] = ""  # Reset sprint assignments
                        
                        # Define priority order and sort tasks
                        priority_order = {"high": 1, "medium": 2, "low": 3}
                        df["PriorityOrder"] = df["Priority"].str.lower().map(priority_order).fillna(4)
                        df = df.sort_values("PriorityOrder")  # Sort by priority
                        
                        # Calculate priorities distribution targets per member
                        priorities_list = ["high", "medium", "low", "other"]
                        priority_counts = {}
                        for priority in priorities_list:
                            if priority == "other":
                                count = len(df[~df["Priority"].str.lower().isin(["high", "medium", "low"])])
                            else:
                                count = len(df[df["Priority"].str.lower() == priority])
                            priority_counts[priority] = count
                        
                        # Calculate target distribution per member
                        member_count = len(team_members)
                        target_distribution = {
                            priority: max(1, round(count / member_count)) 
                            for priority, count in priority_counts.items() if count > 0
                        }
                        
                        # Create a more detailed info message about sprint planning
                        st.info(f"""
                        Planning {num_sprints} sprints with capacity of {st.session_state.capacity_per_sprint} hours per person per sprint.
                        Total capacity across all sprints: {num_sprints * st.session_state.capacity_per_sprint} hours per person.
                        
                        The algorithm will distribute tasks to ensure:
                        1. Team members get a fair mix of high, medium, and low priority tasks
                        2. Remaining capacity from each sprint is carried forward to the next sprint
                        3. High priority tasks are assigned first
                        """)
                        
                        # Initialize sprint-specific tracking data
                        sprint_assignments = {}
                        sprint_capacities = {}
                        members_sprint_capacity = {}
                        
                        # Set up tracking for each sprint
                        for sprint in range(1, num_sprints + 1):
                            sprint_name = f"Sprint {sprint}"
                            sprint_assignments[sprint_name] = []
                            sprint_capacities[sprint_name] = {member: 0 for member in team_members}
                        
                        # Initialize remaining capacity for each member based on their capacity percentage
                        # This tracks how much capacity is carried forward between sprints
                        remaining_capacity = {member: 0 for member in team_members}
                        
                        # Process each sprint
                        for sprint_num in range(1, num_sprints + 1):
                            sprint_name = f"Sprint {sprint_num}"
                            
                            # Calculate each member's capacity for this sprint
                            # Base capacity + any remaining capacity from previous sprint
                            for member, full_capacity in team_members.items():
                                # Calculate what percentage of full time this person is
                                capacity_percentage = full_capacity / (num_sprints * st.session_state.capacity_per_sprint)
                                # Capacity for this sprint is the percentage of the sprint's total hours + remaining from previous
                                members_sprint_capacity[member] = (capacity_percentage * st.session_state.capacity_per_sprint) + remaining_capacity[member]
                            
                            # For logging/debugging: show the capacity for each member in each sprint
                            capacity_summary = ", ".join([f"{m}: {c:.1f}h" for m, c in members_sprint_capacity.items()])
                            st.text(f"{sprint_name} - Available capacity: {capacity_summary}")
                            
                            # Create a copy of tasks that haven't been assigned yet
                            unassigned_tasks = df[df["Assigned To"] == ""].copy()
                            
                            # Skip if no tasks left to assign
                            if len(unassigned_tasks) == 0:
                                continue
                            
                            # Create priority task groups for this sprint
                            task_groups = {}
                            for priority in priorities_list:
                                if priority == "other":
                                    task_groups[priority] = unassigned_tasks[~unassigned_tasks["Priority"].str.lower().isin(["high", "medium", "low"])].copy()
                                else:
                                    task_groups[priority] = unassigned_tasks[unassigned_tasks["Priority"].str.lower() == priority].copy()
                                
                                # Sort by estimate within priority group (smaller tasks first for better distribution)
                                if len(task_groups[priority]) > 0:
                                    task_groups[priority] = task_groups[priority].sort_values("Original Estimates")
                            
                            # Track assigned priorities for this sprint
                            sprint_assigned_priorities = {member: {"high": 0, "medium": 0, "low": 0, "other": 0} for member in team_members}
                            
                            # First pass: ensure everyone gets a mix of priorities
                            available_priorities = [p for p in priorities_list if len(task_groups[p]) > 0]
                            current_priority_index = 0
                            cycle_count = 0
                            
                            while available_priorities and cycle_count < 100:  # Safety limit
                                cycle_count += 1
                                current_priority = available_priorities[current_priority_index]
                                
                                if len(task_groups[current_priority]) == 0:
                                    # No more tasks of this priority
                                    available_priorities.pop(current_priority_index)
                                    if not available_priorities:
                                        break
                                    current_priority_index = current_priority_index % len(available_priorities)
                                    continue
                                
                                # Sort members by who has the least of this priority in this sprint and most remaining capacity
                                members_sorted = sorted(
                                    team_members.keys(),
                                    key=lambda m: (
                                        sprint_assigned_priorities[m][current_priority],
                                        assigned_priorities[m][current_priority],  # Consider overall assignments too
                                        -members_sprint_capacity[m]  # Negated so higher capacity is first
                                    )
                                )
                                
                                # Try to assign to first member with capacity
                                task_assigned = False
                                for member in members_sorted:
                                    # If no capacity left in this sprint for this member, skip
                                    if members_sprint_capacity[member] <= 0:
                                        continue
                                        
                                    # Try to find a task that fits the member's remaining sprint capacity
                                    for idx in task_groups[current_priority].index:
                                        task = task_groups[current_priority].loc[idx]
                                        estimate = task["Original Estimates"]
                                        
                                        if pd.isna(estimate) or estimate <= 0:
                                            continue
                                            
                                        if estimate <= members_sprint_capacity[member]:
                                            task_id = task["ID"]
                                            
                                            # Assign in the original dataframe
                                            df.loc[df["ID"] == task_id, "Assigned To"] = member
                                            df.loc[df["ID"] == task_id, "Sprint"] = sprint_name
                                            df.loc[df["ID"] == task_id, "Iteration Path"] = f"/{sprint_name}/{current_priority}"
                                            
                                            # Update member statistics (both sprint-specific and overall)
                                            members_sprint_capacity[member] -= estimate
                                            sprint_capacities[sprint_name][member] += estimate
                                            assigned_hours[member] += estimate
                                            
                                            # Update priority counts
                                            sprint_assigned_priorities[member][current_priority] += 1
                                            assigned_priorities[member][current_priority] += 1
                                            
                                            # Add to sprint assignments
                                            sprint_assignments[sprint_name].append(task_id)
                                            
                                            # Remove task from the group
                                            task_groups[current_priority] = task_groups[current_priority].drop(idx)
                                            
                                            task_assigned = True
                                            break
                                    
                                    if task_assigned:
                                        break
                                
                                # If no task assigned this round, move to next priority
                                current_priority_index = (current_priority_index + 1) % len(available_priorities)
                                
                                # If we've gone through all priorities and can't assign any more, break
                                if not task_assigned and current_priority_index == 0:
                                    break
                            
                            # Second pass - assign remaining tasks with balanced approach
                            for priority_level in priorities_list:
                                remaining_tasks = task_groups[priority_level]
                                
                                if len(remaining_tasks) == 0:
                                    continue
                                    
                                for idx in remaining_tasks.index:
                                    task = remaining_tasks.loc[idx]
                                    task_id = task["ID"]
                                    estimate = task["Original Estimates"]
                                    
                                    if pd.isna(estimate) or estimate <= 0:
                                        continue
                                    
                                    # Sort members by who has the least of this priority and most remaining capacity
                                    shuffled_members = sorted(
                                        team_members.keys(),
                                        key=lambda m: (
                                            sprint_assigned_priorities[m][priority_level],
                                            -members_sprint_capacity[m]  # Negated so higher capacity is first
                                        )
                                    )
                                    
                                    # Try to assign to the best-fit member with capacity
                                    for member in shuffled_members:
                                        if members_sprint_capacity[member] <= 0:
                                            continue
                                            
                                        if estimate <= members_sprint_capacity[member]:
                                            # Assign in the original dataframe
                                            df.loc[df["ID"] == task_id, "Assigned To"] = member
                                            df.loc[df["ID"] == task_id, "Sprint"] = sprint_name
                                            df.loc[df["ID"] == task_id, "Iteration Path"] = f"/{sprint_name}/{priority_level}"
                                            
                                            # Update member statistics
                                            members_sprint_capacity[member] -= estimate
                                            sprint_capacities[sprint_name][member] += estimate
                                            assigned_hours[member] += estimate
                                            
                                            # Update priority counts
                                            sprint_assigned_priorities[member][priority_level] += 1
                                            assigned_priorities[member][priority_level] += 1
                                            
                                            # Add to sprint assignments
                                            sprint_assignments[sprint_name].append(task_id)
                                            break
                            
                            # At the end of the sprint, update the remaining capacity that gets carried forward
                            for member in team_members:
                                remaining_capacity[member] = members_sprint_capacity[member]
                                
                            # Log how much capacity is being carried forward
                            remaining_summary = ", ".join([f"{m}: {c:.1f}h" for m, c in remaining_capacity.items()])
                            st.text(f"{sprint_name} - Remaining capacity carried forward: {remaining_summary}")
                        
                        # Clean up
                        if "PriorityOrder" in df.columns:
                            df = df.drop(columns=["PriorityOrder"])
                        
                        # Store results with sprint data
                        st.session_state.results = {
                            "df": df,
                            "assigned_hours": assigned_hours,
                            "assigned_priorities": assigned_priorities,
                            "team_members": team_members,
                            "sprint_data": {
                                "sprint_assignments": sprint_assignments,
                                "sprint_capacities": sprint_capacities,
                                "num_sprints": num_sprints
                            }
                        }
                        
                        # Switch to results tab
                        st.success("Tasks assigned successfully across sprints! See the Results tab for sprint-by-sprint details.")
    
# 4. RESULTS TAB
    with results_tab:
        st.header("Assignment Results")
        
        if st.session_state.results is None:
            st.warning("No assignment results available. Please run the assignment algorithm first.")
        else:
            results = st.session_state.results
            df = results["df"]
            assigned_hours = results["assigned_hours"]
            assigned_priorities = results["assigned_priorities"]
            team_members = results["team_members"]
            
            # Assignment summary
            st.subheader("Summary")
            
            total_assigned = sum(assigned_hours.values())
            total_capacity = sum(team_members.values())
            percent_utilized = (total_assigned / total_capacity * 100) if total_capacity > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Tasks Assigned", len(df[df["Assigned To"] != ""]))
                
            with col2:
                st.metric("Hours Assigned", f"{total_assigned:.1f}/{total_capacity:.1f}")
                
            with col3:
                st.metric("Capacity Utilized", f"{percent_utilized:.1f}%")
                
            # Detailed results
            st.subheader("Assigned Tasks")
            st.dataframe(
                df,
                column_config={
                    "Priority": st.column_config.Column(
                        "Priority",
                        help="Task priority level",
                        width="medium",
                    ),
                    "Original Estimates": st.column_config.NumberColumn(
                        "Hours",
                        help="Estimated work hours",
                        format="%.1f",
                    ),
                    "Assigned To": st.column_config.Column(
                        "Assigned To",
                        help="Team member assigned to the task",
                        width="medium",
                    ),
                    "Sprint": st.column_config.Column(
                        "Sprint",
                        help="Sprint assignment",
                        width="medium",
                    ),
                },
                use_container_width=True
            )
            
            # Visualizations
            st.subheader("Capacity Utilization")
            
            # Prepare data for visualization
            members = list(team_members.keys())
            capacities = [team_members[m] for m in members]
            used_capacities = [assigned_hours[m] for m in members]
            remaining_capacities = [capacities[i] - used_capacities[i] for i in range(len(members))]
            
            # Create capacity chart with dark theme
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(10, 5))
            bar_width = 0.35
            x = np.arange(len(members))
            
            # Use more vibrant colors for dark theme
            ax.bar(x, used_capacities, bar_width, label='Used', color='#81c784')
            ax.bar(x, remaining_capacities, bar_width, bottom=used_capacities, label='Remaining', color='#455a64')
            
            ax.set_ylabel('Hours', color='#e0e0e0')
            ax.set_title('Overall Capacity Utilization by Team Member', color='#81c784')
            ax.set_xticks(x)
            ax.set_xticklabels(members, rotation=45, ha='right', color='#e0e0e0')
            ax.tick_params(axis='y', colors='#e0e0e0')
            ax.spines['bottom'].set_color('#555555')
            ax.spines['top'].set_color('#555555')
            ax.spines['left'].set_color('#555555')
            ax.spines['right'].set_color('#555555')
            ax.grid(color='#333333', linestyle='-', linewidth=0.5, alpha=0.7)
            ax.legend(facecolor='#2d2d2d', edgecolor='#555555', labelcolor='#e0e0e0')
            
            fig.patch.set_facecolor('#1e1e1e')
            plt.tight_layout()
            st.pyplot(fig)
            
            # Priority distribution
            st.subheader("Priority Distribution")
            
            # Prepare data for priority chart
            priorities = ["high", "medium", "low", "other"]
            priority_data = {member: [assigned_priorities[member].get(p, 0) for p in priorities] for member in members}
            
            # Create stacked bar chart with dark theme
            # We're already using dark_background style from the previous chart
            fig, ax = plt.subplots(figsize=(10, 5))
            bottom = np.zeros(len(members))
            
            # Enhanced colors for better visibility on dark background
            colors = {'high': '#ef5350', 'medium': '#ffb74d', 'low': '#81c784', 'other': '#b0bec5'}
            
            for i, priority in enumerate(priorities):
                priority_counts = [priority_data[member][i] for member in members]
                ax.bar(members, priority_counts, bottom=bottom, label=priority.capitalize(), color=colors[priority])
                bottom += priority_counts
            
            ax.set_ylabel('Number of Tasks', color='#e0e0e0')
            ax.set_title('Overall Priority Distribution by Team Member', color='#81c784')
            ax.set_xticks(range(len(members)))
            ax.set_xticklabels(members, rotation=45, ha='right', color='#e0e0e0')
            ax.tick_params(axis='y', colors='#e0e0e0')
            ax.spines['bottom'].set_color('#555555')
            ax.spines['top'].set_color('#555555')
            ax.spines['left'].set_color('#555555')
            ax.spines['right'].set_color('#555555')
            ax.grid(color='#333333', linestyle='-', linewidth=0.5, alpha=0.7)
            ax.legend(facecolor='#2d2d2d', edgecolor='#555555', labelcolor='#e0e0e0')
            
            fig.patch.set_facecolor('#1e1e1e')
            plt.tight_layout()
            st.pyplot(fig)
            
            # Add detailed priority distribution as tables
            st.subheader("Detailed Priority Mix by Team Member")
            st.write("This table shows exactly how many tasks of each priority level were assigned to each team member:")
            
            # Create a dataframe showing the priority distribution
            priority_df = pd.DataFrame(assigned_priorities).T
            priority_df.index.name = "Team Member"
            priority_df.columns = [col.capitalize() for col in priority_df.columns]
            
            # Add percentage columns to show proportion of each priority
            for member in priority_df.index:
                total = priority_df.loc[member].sum()
                if total > 0:
                    for col in priority_df.columns:
                        priority_df.loc[member, f"{col} %"] = round(priority_df.loc[member, col] / total * 100, 1)
                else:
                    for col in priority_df.columns:
                        priority_df.loc[member, f"{col} %"] = 0.0
            
            # Display the dataframe
            st.dataframe(priority_df, use_container_width=True)
            
            # Add a color legend explaining the priority levels
            st.markdown("""
            <div style="margin-top: 10px; padding: 10px; background-color: #2d2d2d; border-radius: 5px;">
                <h4 style="color: #e0e0e0;">Priority Legend</h4>
                <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                    <div style="display: flex; align-items: center;">
                        <div style="width: 20px; height: 20px; background-color: #ef5350; margin-right: 5px;"></div>
                        <span style="color: #e0e0e0;">High</span>
                    </div>
                    <div style="display: flex; align-items: center;">
                        <div style="width: 20px; height: 20px; background-color: #ffb74d; margin-right: 5px;"></div>
                        <span style="color: #e0e0e0;">Medium</span>
                    </div>
                    <div style="display: flex; align-items: center;">
                        <div style="width: 20px; height: 20px; background-color: #81c784; margin-right: 5px;"></div>
                        <span style="color: #e0e0e0;">Low</span>
                    </div>
                    <div style="display: flex; align-items: center;">
                        <div style="width: 20px; height: 20px; background-color: #b0bec5; margin-right: 5px;"></div>
                        <span style="color: #e0e0e0;">Other</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Check if we have sprint data and display it
            if "sprint_data" in results:
                sprint_data = results["sprint_data"]
                num_sprints = sprint_data["num_sprints"]
                sprint_assignments = sprint_data["sprint_assignments"]
                sprint_capacities = sprint_data["sprint_capacities"]
                
                st.header("Sprint Planning")
                st.markdown("""
                <div style="background-color: #1e3f20; padding: 10px; border-radius: 5px; margin-bottom: 20px;">
                    <p style="color: #e0e0e0; margin: 0;">
                        Tasks are distributed across sprints with remaining capacity carried forward. 
                        Each sprint balances priority distribution while respecting capacity constraints.
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                # Create sprint tabs for detailed view
                sprint_tabs = st.tabs([f"Sprint {i}" for i in range(1, num_sprints + 1)])
                
                for i, sprint_tab in enumerate(sprint_tabs):
                    sprint_name = f"Sprint {i+1}"
                    
                    with sprint_tab:
                        st.subheader(f"{sprint_name} Assignments")
                        
                        # Sprint Statistics
                        sprint_tasks = df[df["Sprint"] == sprint_name]
                        
                        if len(sprint_tasks) == 0:
                            st.info(f"No tasks assigned to {sprint_name}.")
                            continue
                        
                        # Display key metrics for this sprint
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Tasks", len(sprint_tasks))
                        
                        with col2:
                            sprint_hours = sum(sprint_capacities[sprint_name].values())
                            st.metric("Hours", f"{sprint_hours:.1f}")
                        
                        with col3:
                            # Calculate how much capacity was utilized in this sprint
                            total_sprint_capacity = sum([team_members[m] / num_sprints for m in team_members])
                            sprint_percent = (sprint_hours / total_sprint_capacity * 100) if total_sprint_capacity > 0 else 0
                            st.metric("Sprint Capacity Used", f"{sprint_percent:.1f}%")
                        
                        # Tasks assigned to this sprint
                        st.subheader("Tasks")
                        st.dataframe(
                            sprint_tasks,
                            column_config={
                                "Priority": st.column_config.Column(
                                    "Priority",
                                    help="Task priority level",
                                    width="medium"
                                ),
                                "Original Estimates": st.column_config.NumberColumn(
                                    "Hours",
                                    help="Estimated work hours",
                                    format="%.1f"
                                ),
                                "Assigned To": st.column_config.Column(
                                    "Assigned To",
                                    help="Team member assigned to the task",
                                    width="medium"
                                )
                            },
                            use_container_width=True
                        )
                        
                        # Create visualization of capacity used in this sprint
                        st.subheader("Sprint Capacity")
                        
                        # Prepare data
                        members = list(team_members.keys())
                        sprint_used = [sprint_capacities[sprint_name].get(m, 0) for m in members]
                        
                        # Calculate carried over capacity from previous sprint
                        carried_over = []
                        if i > 0:
                            prev_sprint = f"Sprint {i}"
                            for m in members:
                                member_capacity = team_members[m] / num_sprints  # Base capacity per sprint
                                used_in_prev = sprint_capacities[prev_sprint].get(m, 0)
                                carried = max(0, member_capacity - used_in_prev)
                                carried_over.append(carried)
                        else:
                            carried_over = [0] * len(members)
                        
                        # Create sprint capacity chart
                        plt.style.use('dark_background')
                        fig, ax = plt.subplots(figsize=(10, 5))
                        bar_width = 0.35
                        x = np.arange(len(members))
                        
                        # Member's standard capacity for this sprint
                        standard_capacity = [team_members[m] / num_sprints for m in members]
                        
                        # Visualize standard capacity, carried over capacity, and used capacity
                        ax.bar(x, standard_capacity, bar_width, label='Standard Capacity', color='#455a64', alpha=0.6)
                        if any(c > 0 for c in carried_over):
                            ax.bar(x, carried_over, bar_width, bottom=standard_capacity, label='Carried Over', color='#5c6bc0')
                        ax.bar(x, sprint_used, bar_width/1.5, label='Used', color='#81c784')
                        
                        # Styling
                        ax.set_ylabel('Hours', color='#e0e0e0')
                        ax.set_title(f'{sprint_name} Capacity Utilization', color='#81c784')
                        ax.set_xticks(x)
                        ax.set_xticklabels(members, rotation=45, ha='right', color='#e0e0e0')
                        ax.tick_params(axis='y', colors='#e0e0e0')
                        ax.spines['bottom'].set_color('#555555')
                        ax.spines['top'].set_color('#555555')
                        ax.spines['left'].set_color('#555555')
                        ax.spines['right'].set_color('#555555')
                        ax.grid(color='#333333', linestyle='-', linewidth=0.5, alpha=0.7)
                        ax.legend(facecolor='#2d2d2d', edgecolor='#555555', labelcolor='#e0e0e0')
                        
                        fig.patch.set_facecolor('#1e1e1e')
                        plt.tight_layout()
                        st.pyplot(fig)
                        
                        # Create priority breakdown for this sprint
                        st.subheader("Sprint Priority Distribution")
                        
                        # Get priority distribution for this sprint
                        sprint_priority_counts = {}
                        for member in members:
                            sprint_priority_counts[member] = {"high": 0, "medium": 0, "low": 0, "other": 0}
                        
                        for _, task in sprint_tasks.iterrows():
                            member = task["Assigned To"]
                            priority = task["Priority"].lower()
                            if priority not in ["high", "medium", "low"]:
                                priority = "other"
                            sprint_priority_counts[member][priority] += 1
                        
                        # Create stacked bar chart for sprint priority distribution
                        priority_data = {m: [sprint_priority_counts[m].get(p, 0) for p in priorities] for m in members}
                        
                        fig, ax = plt.subplots(figsize=(10, 5))
                        bottom = np.zeros(len(members))
                        
                        for i, priority in enumerate(priorities):
                            priority_counts = [priority_data[member][i] for member in members]
                            ax.bar(members, priority_counts, bottom=bottom, label=priority.capitalize(), color=colors[priority])
                            bottom += priority_counts
                        
                        ax.set_ylabel('Number of Tasks', color='#e0e0e0')
                        ax.set_title(f'{sprint_name} Priority Distribution', color='#81c784')
                        ax.set_xticks(range(len(members)))
                        ax.set_xticklabels(members, rotation=45, ha='right', color='#e0e0e0')
                        ax.tick_params(axis='y', colors='#e0e0e0')
                        ax.spines['bottom'].set_color('#555555')
                        ax.spines['top'].set_color('#555555')
                        ax.spines['left'].set_color('#555555')
                        ax.spines['right'].set_color('#555555')
                        ax.grid(color='#333333', linestyle='-', linewidth=0.5, alpha=0.7)
                        ax.legend(facecolor='#2d2d2d', edgecolor='#555555', labelcolor='#e0e0e0')
                        
                        fig.patch.set_facecolor('#1e1e1e')
                        plt.tight_layout()
                        st.pyplot(fig)
                
                # Create a Gantt chart visualization of tasks across sprints
                st.header("Sprint Timeline")
                
                # Prepare data for Gantt chart
                gantt_data = []
                for _, task in df.iterrows():
                    if task["Assigned To"] and task["Sprint"]:
                        sprint_num = int(task["Sprint"].split(" ")[1])
                        gantt_data.append({
                            "Task": f"{task['ID']}: {task['Title']}",
                            "Start": sprint_num,
                            "Duration": 1,  # Each task takes 1 sprint
                            "Member": task["Assigned To"],
                            "Priority": task["Priority"]
                        })
                
                if gantt_data:
                    # Convert to DataFrame for easier plotting
                    gantt_df = pd.DataFrame(gantt_data)
                    
                    # Sort by Member and Sprint
                    gantt_df = gantt_df.sort_values(["Member", "Start"])
                    
                    # Create figure and axes - adjust height based on task count
                    max_height = max(8, min(20, len(gantt_df) * 0.3))  # Limit max height 
                    fig, ax = plt.subplots(figsize=(12, max_height))
                    
                    # Plot each task as a horizontal bar
                    y_pos = np.arange(len(gantt_df))
                    
                    # Use colors based on priority
                    task_colors = [colors.get(task["Priority"].lower(), colors.get("other")) for _, task in gantt_df.iterrows()]
                    
                    # Plot bars
                    ax.barh(y_pos, gantt_df["Duration"], left=gantt_df["Start"], color=task_colors, alpha=0.9)
                    
                    # Add vertical lines for sprint boundaries
                    for sprint in range(1, num_sprints + 1):
                        ax.axvline(sprint, color='white', linestyle='--', alpha=0.3)
                    
                    # Set y-axis labels to task names
                    ax.set_yticks(y_pos)
                    ax.set_yticklabels(gantt_df["Task"], fontsize=8, color='#e0e0e0')
                    
                    # Set x-axis labels to sprint numbers
                    ax.set_xticks(range(1, num_sprints + 2))
                    ax.set_xticklabels([f"Sprint {i}" for i in range(1, num_sprints + 2)], color='#e0e0e0')
                    
                    # Add member name annotations
                    for i, (_, task) in enumerate(gantt_df.iterrows()):
                        ax.text(task["Start"] + 0.5, i, task["Member"], 
                               ha='center', va='center', color='#1e1e1e', fontweight='bold')
                    
                    # Add labels
                    ax.set_xlabel('Sprints', color='#e0e0e0')
                    ax.set_title('Task Timeline Across Sprints', color='#81c784')
                    
                    # Style the chart
                    ax.tick_params(axis='x', colors='#e0e0e0')
                    ax.spines['bottom'].set_color('#555555')
                    ax.spines['top'].set_color('#555555')
                    ax.spines['left'].set_color('#555555')
                    ax.spines['right'].set_color('#555555')
                    ax.grid(color='#333333', linestyle='-', linewidth=0.5, alpha=0.7)
                    
                    fig.patch.set_facecolor('#1e1e1e')
                    plt.tight_layout()
                    st.pyplot(fig)
                else:
                    st.info("No tasks have been assigned to sprints yet.")
            
            # Download options
            st.subheader("Export Results")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown(get_download_link(df, "Task_Assignments.xlsx", "excel"), unsafe_allow_html=True)
                
            with col2:
                st.markdown(get_download_link(df, "Task_Assignments.csv", "csv"), unsafe_allow_html=True)

    
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
    # 6. AI SUGGESTIONS TAB
    ai_tab = st.tabs(["6. AI Suggestions"])[0]

    with ai_tab:
        st.header("AI Suggestions and Insights")
        st.markdown("Powered by OpenRouter + OpenAI")

        if "ai_messages" not in st.session_state:
            st.session_state.ai_messages = [
                {"role": "assistant", "content": "Hello! I'm your sprint planning assistant. How can I help you with your task assignments today?"}
            ]

        for message in st.session_state.ai_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        api_key = st.text_input("OpenRouter API Key", type="password", key="ai_api_key")

        if st.session_state.df_tasks is None:
            st.info("Please upload task data in the Upload Tasks tab first.")
            st.stop()

        df = st.session_state.df_tasks.copy()

        # 🔍 Extract component expertise from the task file
        expertise_col_member = "Unnamed: 15"
        expertise_col_comp = "Unnamed: 16"
        component_col = None

        if expertise_col_member in df.columns and expertise_col_comp in df.columns:
            expertise_map = df[[expertise_col_member, expertise_col_comp]].dropna()
            expertise_map.columns = ["Member", "Expertise"]
            expertise_dict = expertise_map.set_index("Member")["Expertise"].to_dict()
        else:
            expertise_dict = {}

        # 📦 Extract component name from Title (e.g., "Comp1: something")
        if "Title" in df.columns:
            df["Component"] = df["Title"].str.extract(r"(Comp\d+)", expand=False)

        # 🧠 Analyze mismatches
        df["Assigned To"] = df["Assigned To"].fillna("").str.strip()
        df["Mismatch"] = df.apply(
            lambda row: (
                row["Assigned To"] in expertise_dict and
                pd.notna(row["Component"]) and
                expertise_dict[row["Assigned To"]] != row["Component"]
            ),
            axis=1
        )
        mismatches = df[df["Mismatch"]]

        # 📬 User input
        prompt = st.chat_input("Ask about your sprint plan or say 'fix component mismatches'...")

        if prompt:
            st.session_state.ai_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # If user wants to fix mismatches
            if "fix" in prompt.lower() and "mismatch" in prompt.lower():
                with st.chat_message("assistant"):
                    st.success("Fixing tasks by component expertise...")
                    reassigned = 0
                    for idx, row in mismatches.iterrows():
                        correct_member = next((m for m, c in expertise_dict.items() if c == row["Component"]), None)
                        if correct_member:
                            df.at[idx, "Assigned To"] = correct_member
                            reassigned += 1

                    st.success(f"Reassigned {reassigned} mismatched tasks.")
                    st.dataframe(df[["ID", "Title", "Component", "Assigned To"]], use_container_width=True)

                    st.session_state.df_tasks = df  # Save back corrected

                    st.session_state.ai_messages.append({
                        "role": "assistant",
                        "content": f"I found and reassigned {reassigned} tasks to match component expertise."
                    })

            else:
                # 🧠 AI Context
                context = f"""You are an expert sprint planning assistant.

    There are {len(df)} tasks. Component expertise is as follows:\n"""
                for m, c in expertise_dict.items():
                    context += f"- {m} specializes in {c}\n"

                if not mismatches.empty:
                    context += "\n⚠️ Detected mismatches:\n"
                    for _, row in mismatches.iterrows():
                        context += f"- Task '{row['Title']}' assigned to {row['Assigned To']} but it's {row['Component']}\n"

                context += f"\nUser prompt: {prompt}"

                # 🔁 Stream response from OpenRouter
                with st.chat_message("assistant"):
                    message_placeholder = st.empty()
                    full_response = ""

                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "https://localhost",
                        "Content-Type": "application/json"
                    }

                    body = {
                        "model": "openai/gpt-3.5-turbo",
                        "messages": [{"role": "system", "content": context}] +
                                    [msg for msg in st.session_state.ai_messages if msg["role"] != "assistant"],
                        "temperature": 0.7,
                        "max_tokens": 1500,
                        "stream": True
                    }

                    try:
                        with requests.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers=headers,
                            json=body,
                            stream=True
                        ) as response:
                            if response.status_code == 200:
                                for chunk in response.iter_lines():
                                    if chunk:
                                        chunk_str = chunk.decode('utf-8')
                                        if chunk_str.startswith("data:"):
                                            try:
                                                data = json.loads(chunk_str[5:])
                                                if "choices" in data and data["choices"]:
                                                    delta = data["choices"][0].get("delta", {})
                                                    if "content" in delta:
                                                        full_response += delta["content"]
                                                        message_placeholder.markdown(full_response + "▌")
                                            except json.JSONDecodeError:
                                                continue
                            else:
                                full_response = f"Error: {response.status_code} - {response.text}"
                    except Exception as e:
                        full_response = f"An error occurred: {str(e)}"

                    message_placeholder.markdown(full_response)
                    st.session_state.ai_messages.append({"role": "assistant", "content": full_response})

# 2. RETROSPECTIVE ANALYSIS
with main_tabs[1]:
    st.header("Team Retrospective Analysis Tool")
    st.markdown("Upload multiple retrospective CSV files to analyze and compare feedback across team retrospectives.")
    retro_ai = st.tabs([
        "1. AI for retrospective Tasks"
    ])
    with retro_ai:
        st.header("🤖 AI Retrospective Assistant")
        st.markdown("Ask questions about your feedback, get summaries, or suggestions for improvement.\n\nPowered by OpenRouter + OpenAI.")

        if "ai_messages" not in st.session_state:
            st.session_state.ai_messages = [
                {"role": "assistant", "content": "Hi! I'm your retrospective assistant. Ask me about themes, issues, or improvements from your team's feedback."}
            ]

        for message in st.session_state.ai_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        api_key = st.text_input("🔑 OpenRouter API Key", type="password", key="ai_api_key")

        if "retro_feedback" not in st.session_state or st.session_state.retro_feedback is None:
            st.info("Please analyze retrospective data in the first tab before chatting.")
            st.stop()

        df = create_dataframe_from_results(st.session_state.retro_feedback)

        # Build context for the assistant
        context = "You are an assistant helping a team reflect on their sprint retrospective. Here’s a summary of feedback:\n\n"
        for _, row in df.iterrows():
            votes = row['Votes']
            task = f" (Task ID: {row['Task ID']})" if row['Task ID'] != "None" else ""
            context += f"- {row['Feedback']} [{votes} votes]{task}\n"

        prompt = st.chat_input("Ask me about themes, issues, or suggestions...")

        if prompt:
            st.session_state.ai_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://localhost",
                    "Content-Type": "application/json"
                }

                body = {
                    "model": "openai/gpt-3.5-turbo",
                    "messages": [{"role": "system", "content": context}] +
                                [msg for msg in st.session_state.ai_messages if msg["role"] != "assistant"],
                    "temperature": 0.7,
                    "max_tokens": 1500,
                    "stream": True
                }

                try:
                    with requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=body,
                        stream=True
                    ) as response:
                        if response.status_code == 200:
                            for chunk in response.iter_lines():
                                if chunk:
                                    chunk_str = chunk.decode('utf-8')
                                    if chunk_str.startswith("data:"):
                                        try:
                                            data = json.loads(chunk_str[5:])
                                            if "choices" in data and data["choices"]:
                                                delta = data["choices"][0].get("delta", {})
                                                if "content" in delta:
                                                    full_response += delta["content"]
                                                    message_placeholder.markdown(full_response + "▌")
                                        except json.JSONDecodeError:
                                            continue
                        else:
                            full_response = f"Error: {response.status_code} - {response.text}"
                except Exception as e:
                    full_response = f"An error occurred: {str(e)}"

                message_placeholder.markdown(full_response)
                st.session_state.ai_messages.append({"role": "assistant", "content": full_response})


    
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
                for sprint, tasks in results["sprint_data"]["sprint_assignments"].items():
                    df = results["df"]
                    sprint_tasks = df[df["ID"].isin(tasks)]
                    total_hours = sprint_tasks["Original Estimates"].sum()
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
                    for sprint, tasks in st.session_state.results["sprint_data"]["sprint_assignments"].items():
                        for task in tasks:
                            all_task_ids.add(str(task))  # task is already a task ID
                    
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
