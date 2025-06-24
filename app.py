from flask import Flask, render_template, jsonify, request, flash, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from db_manager import create_users_table, fetch_query_logs, register_user, authenticate_user, save_query_log_to_db
from chatagent.chat_agent import execute_sql_query, generate_sql_from_question, generate_natural_language_response, suggest_follow_up_questions
import json
import os
from config import DB_NAME,client
import pandas as pd
import boto3
import os
import uuid
import sqlite3
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta

from graphqueryagent.querygraph_copilot import generate_followup_query, generate_graph_insight, generate_sql_for_graph, get_color_palette
# from chatagent.rag_synthesizer import generate_rag_response

app = Flask(__name__)
app.secret_key = "dev_zQ0xyfjkundFVF9GiR0PnT8DbTVczXd3yumese3RGlKax6OIOBWku4giwUL45LKIPhnCaxSfNNyuMUU5CgZnrplmlaHBvQAAFx0"

create_users_table()

def run_sql(sql: str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return {"columns": columns, "rows": rows}
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": []}
    finally:
        if conn:
            conn.close()

def query_db(query, params=()):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

@app.route("/")
def index():
    return render_template("landing.html")

@app.route('/auth')
def auth_page():
    return render_template('auth.html')

@app.route("/api/kpis")
def sm_kpis():
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)

    daily = query_db("SELECT COUNT(*) as count FROM samples_raw_data WHERE DATE(received_date) = DATE('now')")
    weekly = query_db(f"SELECT COUNT(*) as count FROM samples_raw_data WHERE DATE(received_date) >= {start_of_week}")
    monthly = query_db(f"SELECT COUNT(*) as count FROM samples_raw_data WHERE DATE(received_date) >= {start_of_month}")

    status_completed = query_db("""
        SELECT COUNT(*) as count
        FROM samples_raw_data
        WHERE status = 'Completed'
    """)

    status_in_testing = query_db("""
        SELECT COUNT(*) as count
        FROM samples_raw_data
        WHERE status = 'In Testing'
    """)

    status_disposed = query_db("""
        SELECT COUNT(*) as count
        FROM samples_raw_data
        WHERE status = 'Disposed'
    """)

    status_recived = query_db("""
        SELECT COUNT(*) as count
        FROM samples_raw_data
        WHERE status = 'Received'
    """)

    test_types = query_db("""
        SELECT TEST_REQUIRED, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY TEST_REQUIRED
    """)

    avg_tat = query_db("""
        SELECT AVG(julianday(final_disposal_date) - julianday(received_date)) AS avg_days
        FROM samples_raw_data
        WHERE final_disposal_date IS NOT NULL
    """)

    disposed = query_db("""
        SELECT COUNT(*) as count
        FROM samples_raw_data
        WHERE strftime('%Y-%m', final_disposal_date) = strftime('%Y-%m', 'now')
    """)

    return jsonify({
        "daily_new": daily[0]['count'],
        "weekly_new": weekly[0]['count'],
        "monthly_new": monthly[0]['count'],
        "average_tat": round(avg_tat[0]['avg_days'] or 0, 2),
        "disposed_this_month": disposed[0]['count'],
        "status_completed": status_completed[0]['count'],
        "status_recived": status_recived[0]['count'],
        "status_in_testing": status_in_testing[0]['count'],
        "status_disposed": status_disposed[0]['count'],
        "test_types": test_types
    })

@app.route("/api/chart-data")
def sm_chart_data():
    line = query_db("""
        SELECT DATE(received_date) as date, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY DATE(received_date)
        ORDER BY DATE(received_date)
    """)

    pie = query_db("""
        SELECT source, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY source
    """)

    bar = query_db("""
        SELECT status, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY status
    """)

    return jsonify({
        "line": line,
        "pie": pie,
        "bar": bar
    })

@app.route("/api/label-tracking-kpis")
def label_tracking_kpis():
    total_labeled = query_db("SELECT COUNT(*) as count FROM sample_labels_raw_data WHERE label_printed = 'Yes'")
    total_unlabeled = query_db("SELECT COUNT(*) as count FROM sample_labels_raw_data WHERE label_printed = 'No'")

    locations = query_db("""
        SELECT current_location, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY current_location
    """)

    avg_time = query_db("""
        SELECT CURRENT_LOCATION, AVG(julianday(FINAL_DISPOSAL_DATE) - julianday(RECEIVED_DATE)) as avg_days
        FROM samples_raw_data
        GROUP BY CURRENT_LOCATION
    """)

    heat_map = query_db("""
        SELECT current_location, COUNT(*) as count
        FROM samples_raw_data
        GROUP BY current_location
    """)

    summary = query_db("""
        SELECT label_printed, COUNT(*) as count
        FROM sample_labels_raw_data
        GROUP BY label_printed
    """)

    return jsonify({
        "total_labeled": total_labeled[0]['count'],
        "total_unlabeled": total_unlabeled[0]['count'],
        "location_distribution": locations,
        "average_station_time": avg_time,
        "heat_map": heat_map,
        "summary": summary
    })

@app.route("/api/inventory-kpis")
def inventory_kpis():
    total_items = query_db("SELECT SUM(quantity) AS total FROM inventory_items_raw_data")
    
    below_reorder = query_db("""
        SELECT COUNT(*) as count
        FROM stock_thresholds_raw_data st
        JOIN inventory_items_raw_data ii ON st.item_id = ii.item_id
        WHERE st.current_stock < st.threshold_limit
    """)

    expiring = query_db("""
        SELECT COUNT(*) as count
        FROM inventory_items_raw_data
        WHERE DATE(expiry_date) BETWEEN DATE('now') AND DATE('now', '+30 days')
    """)

    # monthly_usage = query_db("""
    #     SELECT item_id, SUM(used_quantity) as total_used
    #     FROM inventory_usage_log
    #     WHERE strftime('%Y-%m', used_date) = strftime('%Y-%m', 'now')
    #     GROUP BY item_id
    # """)

    return jsonify({
        "total_in_stock": total_items[0]['total'] or 0,
        "below_reorder": below_reorder[0]['count'],
        "expiring_soon": expiring[0]['count']
    })

@app.route("/api/inventory-charts")
def inventory_charts():
    # Category donut
    category_dist = query_db("""
        SELECT category, COUNT(*) as count
        FROM inventory_items_raw_data
        GROUP BY category
    """)

    # Consumption trend
    # consumption = query_db("""
    #     SELECT used_date, SUM(used_quantity) as total
    #     FROM inventory_usage_log
    #     GROUP BY DATE(used_date)
    #     ORDER BY used_date
    # """)

    consumption = [
    { "used_date": "2025-06-01", "total": 28 },
    { "used_date": "2025-06-02", "total": 35 },
    { "used_date": "2025-06-03", "total": 30 },
    { "used_date": "2025-06-04", "total": 42 },
    { "used_date": "2025-06-05", "total": 25 },
    { "used_date": "2025-06-06", "total": 40 },
    { "used_date": "2025-06-07", "total": 33 }
    ]


    monthly_usage = [
            { "item_id": "INV-1001", "item_name": "Sodium Chloride", "total_used": 35 },
            { "item_id": "INV-1002", "item_name": "Ethanol", "total_used": 50 },
            { "item_id": "INV-1003", "item_name": "Test Tubes", "total_used": 120 },
            { "item_id": "INV-1004", "item_name": "Glucose Reagent", "total_used": 20 },
            { "item_id": "INV-1005", "item_name": "pH Strips", "total_used": 75 }
        ]

    # Table for stock vs threshold
    table = query_db("""
        SELECT ii.item_name, st.current_stock, st.threshold_limit
        FROM stock_thresholds_raw_data st
        JOIN inventory_items_raw_data ii ON st.item_id = ii.item_id
    """)

    return jsonify({
        "category_distribution": category_dist,
        "consumption_trend": consumption,
        "stock_table": table,
        "monthly_usage": monthly_usage
    })

@app.route("/api/instrument-kpis")
def instrument_kpis():
    total_today = query_db("""
        SELECT COUNT(*) as count
        FROM instrument_schedule_raw_data
        WHERE DATE(scheduled_date) = DATE('now')
    """)

    # utilization = query_db("""
    #     SELECT scheduled_by, SUM(duration_hrs) as total_scheduled
    #     FROM instrument_schedule_raw_data
    #     WHERE DATE(scheduled_date) = DATE('now')
    #     GROUP BY scheduled_by
    # """)

    utilization = [
        { "scheduled_by": "John Doe", "total_scheduled": 10 },
        { "scheduled_by": "Jane Doe", "total_scheduled": 15 },
        { "scheduled_by": "Bob Smith", "total_scheduled": 8 },
            { "scheduled_by": "Dr. Riya Singh", "total_scheduled": 5.0 },
            { "scheduled_by": "Anil Mehta", "total_scheduled": 3.5 }
    ]

    delays = [
        { "instrument_id": "INS-3001", "avg_delay_mins": 12 },
        { "instrument_id": "INS-3010", "avg_delay_mins": 20 },
        { "instrument_id": "INS-3015", "avg_delay_mins": 5 },
        { "instrument_id": "INS-3020", "avg_delay_mins": 15 },
        { "instrument_id": "INS-3025", "avg_delay_mins": 8 }
    ]

    idle_time = [
        { "instrument_id": "INS-3001", "avg_idle_mins": 30 },
        { "instrument_id": "INS-3010", "avg_idle_mins": 45 },
        { "instrument_id": "INS-3015", "avg_idle_mins": 20 },
        { "instrument_id": "INS-3020", "avg_idle_mins": 35 },
        { "instrument_id": "INS-3025", "avg_idle_mins": 25 }
    ]

    # delays = query_db("""
    #     SELECT instrument_id, 
    #            AVG(julianday(actual_start_time) - julianday(scheduled_start)) * 24 * 60 AS avg_delay_mins
    #     FROM instrument_logs_raw_data
    #     JOIN instrument_schedule_raw_data USING(instrument_id)
    #     WHERE actual_start_time IS NOT NULL
    #     GROUP BY instrument_id
    # """)

    # idle_time = query_db("""
    #     SELECT instrument_id,
    #            AVG(julianday(next_start) - julianday(prev_end)) * 24 * 60 as avg_idle_mins
    #     FROM (
    #         SELECT instrument_id,
    #                LAG(actual_end_time) OVER (PARTITION BY instrument_id ORDER BY actual_start_time) AS prev_end,
    #                actual_start_time AS next_start
    #         FROM instrument_logs_raw_data
    #     ) 
    #     WHERE prev_end IS NOT NULL
    #     GROUP BY instrument_id
    # """)

    return jsonify({
        "total_scheduled_today": total_today[0]['count'],
        "technician_utilization": utilization,
        "average_start_delay": delays,
        "average_idle_time": idle_time
    })

@app.route("/api/instrument-charts")
def instrument_charts():
    # gantt = query_db("""
    #     SELECT instrument_id, instrument_name,
    #            scheduled_start, actual_start_time, actual_end_time
    #     FROM instrument_logs_raw_data
    #     JOIN instrument_schedule USING(instrument_id)
    #     ORDER BY instrument_id, scheduled_start
    # """)

    # downtime = query_db("""
    #     SELECT instrument_id, COUNT(*) as downtime_events
    #     FROM instrument_logs_raw_data
    #     WHERE actual_start_time IS NULL OR actual_end_time IS NULL
    #     GROUP BY instrument_id
    # """)

    gantt = [
    {
        "instrument_id": "INS-3001",
        "instrument_name": "GC-MS",
        "scheduled_start": "2025-06-10T09:00:00",
        "actual_start_time": "2025-06-10T09:12:00",
        "actual_end_time": "2025-06-10T11:30:00"
    },
    {
        "instrument_id": "INS-3010",
        "instrument_name": "HPLC",
        "scheduled_start": "2025-06-10T10:00:00",
        "actual_start_time": "2025-06-10T10:20:00",
        "actual_end_time": "2025-06-10T12:00:00"
    },
    {
        "instrument_id": "INS-3015",
        "instrument_name": "Balance",
        "scheduled_start": "2025-06-10T11:00:00",
        "actual_start_time": "2025-06-10T11:05:00",
        "actual_end_time": "2025-06-10T12:10:00"
    }
    ]

    downtime = [
        {
            "instrument_id": "INS-3001",
            "downtime_events": 2
        },
        {
            "instrument_id": "INS-3010",
            "downtime_events": 1
        },
        {
            "instrument_id": "INS-3015",
            "downtime_events": 3
        },
        { "instrument_id": "INS-3020", "downtime_events": 0 }
    ]


    return jsonify({
        "gantt_data": gantt,
        "downtime_data": downtime
    })

@app.route("/api/dummy-reporting-qc")
def dummy_reporting_qc():
    return jsonify({
        "kpis": {
            "weekly_reports": 52,
            "monthly_reports": 208,
            "approval_rate": 82.7,
            "rejected_reports": 18,
            "repeat_tests": [
                { "test_type": "Microbial", "repeat_count": 14 },
                { "test_type": "Toxicology", "repeat_count": 10 },
                { "test_type": "Stability", "repeat_count": 7 },
                { "test_type": "Chemical", "repeat_count": 5 },
                { "test_type": "Physical", "repeat_count": 3 }
            ]
        },
        "line_chart": [
            { "date": "2025-06-01", "count": 15 },
            { "date": "2025-06-02", "count": 22 },
            { "date": "2025-06-03", "count": 18 },
            { "date": "2025-06-04", "count": 20 },
            { "date": "2025-06-05", "count": 19 },
            { "date": "2025-06-06", "count": 21 },
            { "date": "2025-06-07", "count": 17 },
            { "date": "2025-06-08", "count": 23 },
            { "date": "2025-06-09", "count": 25 },
            { "date": "2025-06-10", "count": 28 }
        ],
        "status_table": [
            { "status": "Approved", "count": 172 },
            { "status": "Pending", "count": 14 },
            { "status": "Rejected", "count": 12 },
            { "status": "Resubmitted", "count": 6 },
            { "status": "In Review", "count": 4 }
        ],
        "radar_chart": [
            {
                "test_type": "Microbial",
                "approval_rate": 75.0,
                "reject_rate": 15.0,
                "repeat_percent": 20.0
            },
            {
                "test_type": "Toxicology",
                "approval_rate": 82.0,
                "reject_rate": 10.0,
                "repeat_percent": 14.3
            },
            {
                "test_type": "Chemical",
                "approval_rate": 88.0,
                "reject_rate": 6.0,
                "repeat_percent": 7.1
            },
            {
                "test_type": "Stability",
                "approval_rate": 90.0,
                "reject_rate": 5.0,
                "repeat_percent": 8.7
            },
            {
                "test_type": "Physical",
                "approval_rate": 92.0,
                "reject_rate": 3.0,
                "repeat_percent": 4.0
            }
        ]
    })

@app.route("/api/dummy-alerts-dashboard")
def dummy_alerts_dashboard():
    return jsonify({
        "kpis": {
            "total_alerts_triggered": 64,
            "critical_alerts": 18,
            "notifications_sent": {
                "email": 45,
                "slack": 25
            },
            "avg_acknowledgment_time_minutes": 17.3
        },
        "timeline": [
            { "timestamp": "2025-06-01T09:15:00", "category": "Expiry", "severity": "Critical" },
            { "timestamp": "2025-06-01T11:30:00", "category": "Threshold", "severity": "Warning" },
            { "timestamp": "2025-06-02T14:05:00", "category": "Labeling", "severity": "Info" },
            { "timestamp": "2025-06-03T10:45:00", "category": "Temperature", "severity": "Critical" },
            { "timestamp": "2025-06-04T13:00:00", "category": "Disposal", "severity": "Warning" },
            { "timestamp": "2025-06-05T09:25:00", "category": "Expiry", "severity": "Critical" },
            { "timestamp": "2025-06-06T08:10:00", "category": "Threshold", "severity": "Warning" },
            { "timestamp": "2025-06-07T15:50:00", "category": "Labeling", "severity": "Info" }
        ],
        "pie_chart": [
            { "category": "Expiry", "count": 22 },
            { "category": "Threshold", "count": 18 },
            { "category": "Labeling", "count": 12 },
            { "category": "Temperature", "count": 8 },
            { "category": "Disposal", "count": 4 }
        ],
        "ack_distribution": [
            { "range": "0–5 min", "count": 15 },
            { "range": "5–15 min", "count": 22 },
            { "range": "15–30 min", "count": 14 },
            { "range": "30–60 min", "count": 9 },
            { "range": "> 60 min", "count": 4 }
        ]
    })


@app.route("/api/ai-summary")
def ai_summary_route():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = datetime.today().strftime('%Y-%m-%d')

    cursor.execute("SELECT summary FROM daily_ai_summary WHERE date = ?", (today,))
    result = cursor.fetchone()

    if result:
        ai_summary = result[0]
    else:
        summary_data = get_summary_data()
        ai_summary = generate_ai_summary(summary_data)
        cursor.execute("INSERT INTO daily_ai_summary (summary, date) VALUES (?, ?)", (ai_summary, today))
        conn.commit()

    conn.close()
    return jsonify({"summary": ai_summary})

def get_summary_data():
    today = datetime.today()
    year_month = today.strftime("%Y-%m")

    # 1. Count of expiring inventory items (next 30 days)
    expiring_items = query_db("""
        SELECT category, COUNT(*) as count
        FROM inventory_items_raw_data
        WHERE DATE(expiry_date) BETWEEN DATE('now') AND DATE('now', '+30 days')
        GROUP BY category
    """)

    # 2. Count of disposed samples (this month)
    disposed_samples = query_db("""
        SELECT status, COUNT(*) as count
        FROM samples_raw_data
        WHERE strftime('%Y-%m', final_disposal_date) = strftime('%Y-%m', 'now')
        GROUP BY status
    """)

    # 3. Frequently repeated test types
    repeated_tests = query_db("""
        SELECT test_required, COUNT(*) as count
        FROM samples_raw_data
        WHERE status = 'In Testing'  -- or any flag you use for repeats
        GROUP BY test_required
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 5
    """)

    expiring_items_count = sum([r['count'] for r in expiring_items])
    expiring_items_category = {r['CATEGORY']: r['count'] for r in expiring_items}

    disposed_samples_count = sum([r['count'] for r in disposed_samples])
    recent_disposals_by_status = {r['STATUS']: r['count'] for r in disposed_samples}

    common_test_repeats = [r['TEST_REQUIRED'] for r in repeated_tests]

    return {
        "expiring_items_count": expiring_items_count,
        "expiring_items_category": expiring_items_category,
        "disposed_samples_count": disposed_samples_count,
        "recent_disposals_by_status": recent_disposals_by_status,
        "common_test_repeats": common_test_repeats
    }

def generate_ai_summary(summary_data):
    prompt = f"""
    You are an AI Lab Analyst for a pharmaceutical facility. Based on the following inventory and sample disposal summary, generate:

    1. A concise executive summary (2-3 sentences).
    2. Key observations (bulleted list).
    3. Possible root causes (if any).
    4. Recommendations for lab or inventory management.

    ### Input Data:
    - Products expiring in next 30 days: {summary_data["expiring_items_count"]}
    - By category: {summary_data["expiring_items_category"]}
    - Samples disposed this month: {summary_data["disposed_samples_count"]}
    - By sample status before disposal: {summary_data["recent_disposals_by_status"]}
    - Most frequently repeated test types: {summary_data["common_test_repeats"]}

    Ensure the tone is analytical and actionable.
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.5,
        max_tokens=400
    )

    return response.choices[0].message.content.strip()


@app.route('/api/auth/login' , methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=?", (email,))
    user_data = cursor.fetchone()
    conn.close()
            
    if user_data and check_password_hash(user_data[2], password):
        session['email'] = email
        session['username'] = user_data[3]
        session['role'] = user_data[4]
        return jsonify({'success': True, 'message': 'Login successful'}), 200
                
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    hashed_password = generate_password_hash(password)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (email, password, username)
        VALUES (?, ?,?)
    """, (email, hashed_password, email))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Registration successful'}), 200

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth_page'))

@app.route('/sm_dashboard')
def sm_dashboard_page():
    return render_template('sm_dashboard.html')

@app.route('/slt_dashboard')
def slt_dashboard_page():
    return render_template('slt_dashboard.html')

@app.route('/im_dashboard')
def im_dashboard_page():
    return render_template('im_dashboard.html')

@app.route('/ius_dashboard')
def ius_dashboard_page():
    return render_template('ius_dashboard.html')

@app.route('/rq_dashboard')
def rq_dashboard_page():
    return render_template('rq_dashboard.html')

@app.route('/ac_dashboard')
def ac_dashboard_page():
    return render_template('ac_dashboard.html')

@app.route('/api/upload', methods=['POST'])
def upload_data():
    try:
        file = request.files['file']
        category = request.form['category']

        # Ensure file and category are provided
        if not file or not category:
            return jsonify({'success': False, 'message': 'File and category are required'}), 400

        file_name = file.filename

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Check if file already processed
        cursor.execute(
            "SELECT 1 FROM data_files_metadata WHERE file_name = ? AND is_processed = 1",
            (file_name,)
        )
        if cursor.fetchone():
            print(f"⏭️ Skipping already processed file: {file_name}")
            return jsonify({'success': False, 'message': 'File already processed'}), 409

        # Read and clean the DataFrame
        df = pd.read_csv(file)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        df.columns = df.columns.str.upper().str.replace(' ', '_')

        print(f"🔄 Saving {file_name} data to {category}_raw_data table...")
        df.to_sql(f'{category}_raw_data', conn, if_exists='append', index=False)
        print(f"✅ Saved {file_name} data successfully.")

        # Insert metadata (assuming you don’t have a report_date for now)
        cursor.execute("""
            INSERT INTO data_files_metadata (file_name, category, is_processed)
            VALUES (?, ?, 1)
        """, (file_name, category))

        conn.commit()
        return jsonify({'success': True, 'message': 'File uploaded successfully'}), 200

    except Exception as e:
        print(f"❌ Error during processing: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

    finally:
        conn.close()

def insert_metadata(metadata_list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for entry in metadata_list:
        cursor.execute('''
            INSERT INTO metadata_files (table_name, column_name, format, description)
            VALUES (?, ?, ?, ?)
        ''', (
            entry.get('table_name'),
            entry.get('column_name'),
            entry.get('format'),
            entry.get('description')
        ))
    conn.commit()
    conn.close()

@app.route('/api/upload-metadata', methods=['POST'])
def upload_metadata():
    file = request.files['file']
    if file.filename.endswith('.json'):
        file_path = os.path.join("temp_uploads", file.filename)
        file.save(file_path)

        with open(file_path, 'r') as f:
            data = json.load(f)

        for key, value in data.items():
            if isinstance(value, list):
                insert_metadata(value)

        return jsonify({'success': True, 'message': 'Metadata uploaded successfully'}), 200
    else:
        return jsonify({'success': False, 'message': 'Invalid file format. Please upload a JSON file.'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for table_meta in metadata:
            cursor.execute(create_sql)

        conn.commit()
        conn.close()
        return jsonify({'success': True,"message": "Metadata uploaded successfully"}), 200

    except Exception as e:
        return jsonify({'success': False, "error": f"Database error: {str(e)}"}), 500

@app.route("/rag-configure")
def rag_configure():
    return render_template("rag_configure.html")

@app.route("/rag-agents/add", methods=["GET", "POST"])
def add_agent():

    folders = {
        "CO2": "CO2",
        "Natural Gas": "NG",
        "Power": "PW"
    }

    if request.method == "POST":
        name = request.form.get("name")
        bucket = request.form.get("bucket")
        folder = request.form.get("folder")
        model = request.form.get("model")
        temperature = request.form.get("temperature")
        prompt = request.form.get("prompt")

        metadata_file = request.files.get("metadata_file")
        uploaded_file = request.files.get("uploaded_file")

        # if metadata_file:
        #     metadata_file.save(os.path.join("uploads", metadata_file.filename))
        # if uploaded_file:
        #     uploaded_file.save(os.path.join("uploads", uploaded_file.filename))

        flash("RAG Agent successfully added!", "success")

    return render_template("add_edit_agent.html", folders=folders) 

@app.route("/data-management")
def data_management():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM data_files_metadata 
    """)
    rows = cursor.fetchall()
    conn.close()

    columns = ["id","file_name","file_path", "is_processed","created_at"]
    files = []
    for row in rows:
        files.append(dict(zip(columns, row)))

    return render_template("data_management.html", files=files)

@app.route("/chat-with-rag")
def chat_with_rag():
    return render_template("chat_window.html")

@app.route('/api/copilot-query', methods=['POST'])
def rag_chat_api():
    user_question = request.json.get("message", "")

    sql_query = generate_sql_from_question(user_question)
    result_rows = execute_sql_query(sql_query)
    response_text = generate_natural_language_response(user_question, result_rows)
    followups = suggest_follow_up_questions(user_question, response_text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_query_log_to_db(timestamp, user_question, sql_query, response_text)

    return jsonify({
        "response": response_text,
        "followups": followups
    })

@app.route("/graph-query" , methods=["GET", "POST"])
def graph_query():
    user_query = ""
    chart_labels = []
    chart_values = []
    chart_colors = []
    summary = ""

    chart_type = "bar"
    if "pie" in user_query.lower():
        chart_type = "pie"
    elif "line" in user_query.lower():
        chart_type = "line"

    if request.method == "POST":
        user_query = request.form.get("graph_query")

        sql_query = generate_sql_for_graph(user_query)
        result_rows = execute_sql_query(sql_query)
        print("📊 Result Rows:", result_rows)
        result = generate_graph_insight(result_rows,user_query)
        print("🔍 LLM Output:", result)

        if "error" in result:
            summary = result["error"]
        else:
            sql = result.get("sql")
            summary = result.get("summary", "")
            chart_type = result.get("suggested_chart", "bar")
            x_axis = result.get("x_axis")
            y_axis = result.get("y_axis")

            print(f"📊 SQL: {sql}")
            query_result = run_sql(sql_query)
            print("📈 Query Result:", query_result)

            # Step 2: Extract chart data
            if query_result.get("rows"):
                chart_labels = [row[0] for row in query_result["rows"]]
                chart_values = [row[1] for row in query_result["rows"]]
                chart_colors = get_color_palette(len(chart_labels))

        # Step 3: Store to session history
        if "graph_history" not in session:
            session["graph_history"] = []

        session["graph_history"].append({
            "query": user_query,
            "summary": summary,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        session.modified = True
        chart_colors = get_color_palette(len(chart_labels))
        print(f"I am here {summary}")
    return render_template("graph_query.html",
                           user_query=user_query,
                           summary=summary,
                           chart_colors=chart_colors,
                           chart_labels=chart_labels,
                           chart_values=chart_values,
                           chart_type=chart_type,
                           graph_history=session.get("graph_history", []))


@app.route("/clear-graph-history", methods=["POST"])
def clear_graph_history():
    session.pop("graph_history", None)
    return redirect("/graph-query")

@app.route("/rag-dashboard")
def rag_dashboard():
    return render_template("rag_dashboard.html")

@app.route("/query-log-analyzer")
def query_log_analyzer():
    logs = fetch_query_logs(limit=300)
    return render_template("query_log_analyzer.html", logs=logs)

@app.route("/prompt-config")
def prompt_config():
    return render_template("workin_progress.html")

@app.route("/data-dash-config")
def data_dash_config():
    return render_template("workin_progress.html")

@app.route("/data-freshness")
def data_freshness():

    freshness = [
        {
            "table": "patients",
            "agent": "ETL_Agent_1",
            "frequency": "Daily",
            "last_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            "status": "✅ Fresh",
            "schema": {
                "required_columns": {"status": "✅ Pass", "missing_columns": []},
                "column_types": {"status": "✅ Pass", "type_mismatches": []},
                "unexpected_columns": {"status": "✅ Pass", "extra_columns": []},
                "primary_key": {"status": "✅ Pass", "message": ""}
            },
            "data_validation": {
                "nulls": {"age": 3, "gender": 1},
                "duplicates": 0,
                "date_format_errors": [],
                "non_numeric_columns": []
            }
        },
        {
            "table": "clinical_trials",
            "agent": "ETL_Agent_2",
            "frequency": "Weekly",
            "last_date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            "status": "⚠️ Stale",
            "schema": {
                "required_columns": {"status": "❌ Fail", "missing_columns": ["trial_id"]},
                "column_types": {"status": "✅ Pass", "type_mismatches": []},
                "unexpected_columns": {"status": "✅ Pass", "extra_columns": []},
                "primary_key": {"status": "✅ Pass", "message": ""}
            },
            "data_validation": {
                "nulls": {},
                "duplicates": 5,
                "date_format_errors": ["start_date"],
                "non_numeric_columns": ["trial_phase"]
            }
        },
        {
            "table": "adverse_events",
            "agent": "ETL_Agent_3",
            "frequency": "Monthly",
            "last_date": (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
            "status": "❌ No Data",
            "schema": {
                "required_columns": {"status": "✅ Pass", "missing_columns": []},
                "column_types": {"status": "❌ Fail", "type_mismatches": [("event_code", "int", "str")]},
                "unexpected_columns": {"status": "✅ Pass", "extra_columns": []},
                "primary_key": {"status": "✅ Pass", "message": ""}
            },
            "data_validation": {
                "nulls": {"event_code": 2},
                "duplicates": 0,
                "date_format_errors": [],
                "non_numeric_columns": []
            }
        },
        {
            "table": "medications",
            "agent": "ETL_Agent_1",
            "frequency": "Daily",
            "last_date": (datetime.now()).strftime("%Y-%m-%d"),
            "status": "✅ Fresh",
            "schema": {
                "required_columns": {"status": "✅ Pass", "missing_columns": []},
                "column_types": {"status": "✅ Pass", "type_mismatches": []},
                "unexpected_columns": {"status": "❌ Fail", "extra_columns": ["temp_col"]},
                "primary_key": {"status": "✅ Pass", "message": ""}
            },
            "data_validation": {
                "nulls": {},
                "duplicates": 2,
                "date_format_errors": [],
                "non_numeric_columns": []
            }
        },
        {
            "table": "inventory",
            "agent": "ETL_Agent_2",
            "frequency": "Weekly",
            "last_date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
            "status": "✅ Fresh",
            "schema": {
                "required_columns": {"status": "✅ Pass", "missing_columns": []},
                "column_types": {"status": "✅ Pass", "type_mismatches": []},
                "unexpected_columns": {"status": "✅ Pass", "extra_columns": []},
                "primary_key": {"status": "❌ Fail", "message": "Missing column 'item_id'"}
            },
            "data_validation": {
                "nulls": {"stock": 4},
                "duplicates": 1,
                "date_format_errors": [],
                "non_numeric_columns": ["stock"]
            }
        }
    ]

    return render_template("freshness_dashboard.html", freshness=freshness)

@app.route('/drilldown')
def drilldown():
    label = request.args.get('label')
    parent_query = request.args.get('query')

    chart_labels = []
    chart_values = []
    chart_colors = []
    summary = ""

    # Generate follow-up query using OpenAI
    refined_query = generate_followup_query(parent_query, label)
    print(refined_query)

    sql_query = generate_sql_for_graph(refined_query)
    result_rows = execute_sql_query(sql_query)
    print("📊 Result Rows:", result_rows)
    result = generate_graph_insight(result_rows, refined_query)

    chart_type = "bar"
    if "pie" in parent_query.lower():
        chart_type = "pie"
    elif "line" in parent_query.lower():
        chart_type = "line"

    if "error" in result:
            summary = result["error"]
    else:
        sql = result.get("sql")
        summary = result.get("summary", "")

        print(f"📊 SQL: {sql}")
        query_result = run_sql(sql_query)
        print("📈 Query Result:", query_result)

        if query_result.get("rows"):
            chart_labels = [row[0] for row in query_result["rows"]]
            chart_values = [row[1] for row in query_result["rows"]]
            chart_colors = get_color_palette(len(chart_labels))


    return render_template(
        'graph_drilldown.html',
        user_query=refined_query,
        summary=summary,
        chart_colors=chart_colors,
        chart_labels=chart_labels,
        chart_values=chart_values,
        chart_type=chart_type,
        label=label
    )




if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
