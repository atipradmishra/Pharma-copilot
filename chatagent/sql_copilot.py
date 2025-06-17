import pandas as pd
import sqlite3
import pyodbc
import snowflake.connector
from decimal import Decimal
from gpt_client import create_invoke_chain
from db_manager import load_admin_prompts
from langchain.prompts import ChatPromptTemplate

# Template used to construct the full SQL generation prompt
sql_template = """
{system_prompt}

Task:
{task}

{column_info}

Instruction:
{instruction}

Context:
{context}

SQL Dialect:
Use the appropriate dialect such as SQLite, T-SQL (SQL Server), or Snowflake SQL depending on the source system.

SQL Guidance:
- Use proper JOINs when the query involves multiple tables.
- Use table aliases to avoid ambiguity.
- Ensure selected columns are qualified (e.g., t1.column_name).
- Do not assume implicit joins.

Formatting Instruction:
{formatting_instruction}

User Question:
{user_query}

Expected Output:
Return a JSON object like:
{{ "sql": "<valid SQL query>" }}
"""

def load_column_info_from_db(conn_details: dict) -> str:
    source = conn_details.get("source", "").lower()
    lines = []
    try:
        if source == "azure":
            conn_str = (
                f"DRIVER={{{conn_details['driver']}}};"
                f"SERVER={conn_details['server']};"
                f"DATABASE={conn_details['sql_database']};"
                f"UID={conn_details['uid']};"
                f"PWD={conn_details['pwd']};"
                f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=5;"
            )
            with pyodbc.connect(conn_str) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='{table}'")
                    columns = [col[0] for col in cursor.fetchall()]
                    lines.append(f"Table: {table}")
                    lines.extend([f"- {col}" for col in columns])
        elif source == "snowflake":
            conn = snowflake.connector.connect(
                user=conn_details["uid"],
                password=conn_details["pwd"],
                account=conn_details["account"],
                warehouse=conn_details["warehouse"],
                database=conn_details["sf_database"],
                schema=conn_details["schema"]
            )
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [row[1] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"DESC TABLE {table}")
                columns = [row[0] for row in cursor.fetchall()]
                lines.append(f"Table: {table}")
                lines.extend([f"- {col}" for col in columns])
        elif source == "sqlite":
            conn = sqlite3.connect(conn_details["sql_database"])
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [col[1] for col in cursor.fetchall()]
                lines.append(f"Table: {table}")
                lines.extend([f"- {col}" for col in columns])
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Failed to load column metadata: {e}"

def get_sql_from_question(user_query, table_name=None, conn_details=None, column_info=None, rag_agent_id=None):
    # Load the correct prompt from the DB based on selected agent
    prompts = load_admin_prompts(rag_agent_id=rag_agent_id)

    sql_kwargs = {
        "system_prompt": prompts.get("sql_system_prompt", ""),
        "task": prompts.get("sql_task", ""),
        "instruction": prompts.get("sql_instruction", ""),
        "formatting_instruction": "Return only raw SQL — no markdown or explanation."
    }

    context_info = f"Use the table named '{table_name}' for this query." if table_name else ""

    # If not explicitly passed, default column_info to empty string
    if not column_info:
        column_info = load_column_info_from_db(conn_details) if conn_details else ""

    # Build the input dictionary for the template
    prompt_input = {
        "system_prompt": sql_kwargs["system_prompt"],
        "task": sql_kwargs["task"],
        "instruction": sql_kwargs["instruction"],
        "formatting_instruction": sql_kwargs["formatting_instruction"],
        "column_info": column_info,
        "context": context_info,
        "user_query": user_query
    }

    print("📤 Prompt input to LLM:", prompt_input)

    # Create the LangChain prompt template
    template = ChatPromptTemplate.from_template(sql_template)

    # Generate the SQL via LLM
    return create_invoke_chain(template, prompt_input)
