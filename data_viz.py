import streamlit as st
import pandas as pd
import plotly.express as px

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gaming Session Dashboard", layout="wide")

# --- DATA LOADING ---
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    
    # Standardize column names to lowercase to be safe
    df.columns = df.columns.str.lower().str.strip()
    
    # Ensure Date format
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        # Shift dates from 2024 to 2025
        df['date'] = df['date'] + pd.DateOffset(years=1)
        # Create a Month column for trending (e.g., "January")
        df['month'] = df['date'].dt.strftime('%B')
        # Keep month number for proper sorting
        df['month_num'] = df['date'].dt.month
    
    # Clean up device names
    if 'device' in df.columns:
        def clean_device_name(name):
            # Map abbreviations to friendly names
            abbrev_map = {
                'BL': 'Bioness Left',
                'BR': 'Bioness Right'
            }
            # Check for abbreviation patterns (e.g., BL1, BR2)
            for abbrev, full_name in abbrev_map.items():
                if name.startswith(abbrev) and len(name) > len(abbrev):
                    suffix = name[len(abbrev):]
                    return f"{full_name} {suffix}"
            # Replace underscores with spaces for other names
            return name.replace('_', ' ')
        
        df['device'] = df['device'].apply(clean_device_name)
    
    return df

# --- SIDEBAR ---
st.sidebar.header("Data Source")
data_source = st.sidebar.radio(
    "Choose data source:",
    options=["Default File", "Upload Custom File"],
    index=0
)

uploaded_file = None
if data_source == "Upload Custom File":
    uploaded_file = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"])

st.sidebar.markdown("---")
st.sidebar.header("Filter Data")

# --- MAIN DASHBOARD ---
st.title("LUMOPlay Usage & Metrics Dashboard")

# Determine which file to load
file_to_load = None
if data_source == "Default File":
    file_to_load = "usage_metrics.xlsx"
elif uploaded_file is not None:
    file_to_load = uploaded_file

if file_to_load:
    df = load_data(file_to_load)

    # Check for critical columns
    required_cols = ['date', 'duration_minutes']
    if not all(col in df.columns for col in required_cols):
        st.error(f"Uploaded file is missing one of these required columns: {required_cols}")
        st.stop()

    # --- SIDEBAR FILTERS ---
    # Date Range
    min_date = df['date'].min()
    max_date = df['date'].max()
    start_date, end_date = st.sidebar.date_input("Select Date Range", [min_date, max_date])

    # Category Filters
    selected_game = st.sidebar.multiselect("Select Game", options=df['game'].unique(), default=df['game'].unique())
    selected_device = st.sidebar.multiselect("Select Device", options=df['device'].unique(), default=df['device'].unique())
    selected_area = st.sidebar.multiselect("Select Area", options=df['area'].unique(), default=df['area'].unique())

    # Apply Filters
    mask = (
        (df['date'].dt.date >= start_date) & 
        (df['date'].dt.date <= end_date) &
        (df['game'].isin(selected_game)) &
        (df['device'].isin(selected_device)) &
        (df['area'].isin(selected_area))
    )
    filtered_df = df[mask]

    # --- KPI SECTION ---
    st.subheader("Key Performance Indicators")
    
    # Calculations
    total_sessions = len(filtered_df)
    total_duration = filtered_df['duration_minutes'].sum()
    avg_duration = filtered_df['duration_minutes'].mean()
    
    # Find most popular game
    if not filtered_df.empty:
        top_game = filtered_df['game'].mode()[0]
        top_device = filtered_df['device'].mode()[0]
    else:
        top_game = "N/A"
        top_device = "N/A"

    # Display KPIs
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    kpi1.metric("Total Play Time (Hrs)", f"{total_duration/60:,.1f}")
    kpi2.metric("Avg Session (Mins)", f"{avg_duration:.1f}")
    kpi3.metric("Top Game", str(top_game))
    kpi4.metric("Top Device", str(top_device))

    st.markdown("---")
    

    # --- CHARTS SECTION ---
    
    # ROW 1: Trends
    st.subheader("Usage Trends")

    # Avg Duration per Month
    monthly_dur = filtered_df.groupby(['month_num', 'month'])['duration_minutes'].mean().reset_index()
    monthly_dur = monthly_dur.sort_values('month_num')
    fig_dur = px.line(monthly_dur, x='month', y='duration_minutes', 
                          title="Average Session Duration per Month (Minutes)",
                          markers=True)
    fig_dur.update_xaxes(categoryorder='array', categoryarray=monthly_dur['month'].tolist())
    st.plotly_chart(fig_dur, use_container_width=True)

    # ROW 2: Breakdowns
    st.subheader("Detailed Breakdown")
    col1, col2 = st.columns(2)

    with col1:
        # Game Popularity
        game_counts = filtered_df['game'].value_counts().reset_index()
        game_counts.columns = ['game', 'sessions']
        fig_game = px.pie(game_counts, names='game', values='sessions', 
                          title="Share of Sessions by Game", hole=0.4)
        st.plotly_chart(fig_game, use_container_width=True)

    with col2:
        # Device Usage
        device_counts = filtered_df['device'].value_counts().reset_index()
        device_counts.columns = ['device', 'sessions']
        fig_device = px.bar(device_counts, x='sessions', y='device', orientation='h',
                            title="Sessions by Device Type", color='sessions')
        st.plotly_chart(fig_device, use_container_width=True)

    # --- RAW DATA ---
    with st.expander("View Raw Data Source"):
        st.dataframe(filtered_df)

else:
    # Only show this when Upload is selected but no file provided
    st.info("👋 Upload your Excel file to begin.")
    st.markdown(f"""
    **Expected Column Names:**
    `date`, `game`, `start_time`, `end_time`, `duration_minutes`, `device`, `area`
    """)