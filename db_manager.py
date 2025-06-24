import sqlite3
import hashlib
from config import DB_NAME

# Create users table
def create_users_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password BLOB NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT DEFAULT 'user'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rag_agents (
            agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            model TEXT NOT NULL,
            temperature REAL DEFAULT 0.7,
            s3_folder TEXT, 
            prompt TEXT,
            is_active BOOLEAN DEFAULT TRUE CHECK(is_active IN (0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_files_metadata (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            category TEXT,
            is_processed BOOLEAN DEFAULT TRUE CHECK(is_processed IN (0, 1)),
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata_files (
            metadata_file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            column_name TEXT,
            format TEXT,
            description TEXT
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback_logs (
            feedback_logs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            answer TEXT NOT NULL,
            user_feedback BOOLEAN DEFAULT 1,
            feedback_comment TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_ai_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            summary TEXT NOT NULL,
            date TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user_query TEXT,
            generated_sql TEXT,
            rag_responce TEXT
        )
    """)
    conn.commit()
    conn.close()

# Register new user
def register_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# Authenticate user
def authenticate_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_password))
    user = c.fetchone()
    conn.close()
    return user is not None

def save_query_log_to_db(timestamp, user_query, generated_sql, rag_responce):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO query_logs (timestamp, user_query, generated_sql, rag_responce)
        VALUES (?, ?, ?, ?)
    """, (timestamp, user_query, generated_sql, rag_responce))
    conn.commit()
    conn.close()

def fetch_query_logs(limit=300):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, user_query, generated_sql, rag_responce
        FROM query_logs
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "timestamp": row[0],
            "user_query": row[1],
            "sql": row[2],
            "value": row[3]
        }
        for row in rows]