# data_health/dashboard_utils.py

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from data_health.agent_utils import get_filtered_tables, fernet
from data_health.run_checks import run_all_checks, get_expected_schema, get_pk_fk_expectation, deduplicate_freshness_results
from config import DB_NAME
import pyodbc
import snowflake.connector
from snowflake.connector.pandas_tools import pd_writer
import sys
import os
#from ..backend.agent_connections import get_agent_connection
#from ..backend.query_executor import fetch_table_data
#from ..backend.config_loader import load_config_for_table

def get_agent_connection_by_name(agent_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM connections WHERE agent_name = ?", (agent_name,))
    row = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if not row:
        return None

    conn_data = dict(zip(columns, row))
    if conn_data.get("pwd"):
        try:
            conn_data["pwd"] = fernet.decrypt(conn_data["pwd"].encode()).decode()
        except Exception:
            return None

    return conn_data

def fetch_primary_keys_snowflake(agent_conn, table_name):
    conn = None
    try:
        database = agent_conn["sf_database"]
        schema = agent_conn["schema"]

        conn = snowflake.connector.connect(
            user=agent_conn["uid"],
            password=agent_conn["pwd"],
            account=agent_conn["account"],
            warehouse=agent_conn["warehouse"],
            database=database,
            schema=schema
        )

        full_table = f"{database}.{schema}.{table_name}"
        show_command = f"SHOW PRIMARY KEYS IN TABLE {full_table}"
        print(show_command)

        with conn.cursor() as cursor:
            cursor.execute(show_command)
            rows = cursor.fetchall()

            pk_list = []
            for row in rows:
                column_name = row[4].strip().lower()
                seq = row[5]
                pk_list.append((seq, column_name))

            pk_list.sort(key=lambda x: x[0])
            pk_columns = [col for (_, col) in pk_list]
            print(f"📥 Snowflake PK Query returned: {pk_columns}")
            return pk_columns

    except Exception as e:
        print(f"❌ Failed to fetch PKs from Snowflake: {e}")
        return []
    finally:
        if conn is not None:
            conn.close()

def fetch_latest_load_date(conn_info, table):
    try:
        print("🔁 Checking load date for:", table)
        source = conn_info["source"].lower()
        result = None
        query = ""

        if source == "sqlite":
            conn = sqlite3.connect(conn_info["sql_database"])
            cursor = conn.cursor()
            query = f'SELECT MAX(load_date) FROM "{table}"'
            cursor.execute(query)
            result = cursor.fetchone()[0]

        elif source == "azure":
            conn_str = (
                f"DRIVER={{{conn_info['driver']}}};"
                f"SERVER={conn_info['server']};"
                f"DATABASE={conn_info['sql_database']};"
                f"UID={conn_info['uid']};"
                f"PWD={conn_info['pwd']};"
                f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=5;"
            )
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            query = f"SELECT MAX(load_date) FROM {table}"
            cursor.execute(query)
            result = cursor.fetchone()[0]

        elif source == "snowflake":
            conn = snowflake.connector.connect(
                user=conn_info["uid"],
                password=conn_info["pwd"],
                account=conn_info["account"],
                warehouse=conn_info["warehouse"],
                database=conn_info["sf_database"],
                schema=conn_info["schema"]
            )
            cursor = conn.cursor()
            database = conn_info["sf_database"]
            schema = conn_info["schema"]
            full_table = f'{database}.{schema}.{table}'
            query = f'SELECT MAX("LOAD_DATE") FROM {full_table}'
            print(f"🧪 Snowflake Query: {query}")
            cursor.execute(query)
            result = cursor.fetchone()[0]

        else:
            print(f"⚠️ Unsupported source type: {source}")
            return None

        if result:
            print(f"✅ {table}: Latest LOAD_DATE = {result}")
            if isinstance(result, str):
                return datetime.strptime(result[:10], "%Y-%m-%d")
            return result
        else:
            print(f"⚠️ {table}: LOAD_DATE is NULL or no rows")
            return None

    except Exception as e:
        print(f"❌ Error in table {table} | Query: {query}")
        print(f"   ↪️ Error: {e}")
        return None

def check_freshness_status(last_date, frequency):
    if not last_date:
        return "❌ No Data"

    if isinstance(last_date, datetime):
        last_date = last_date.date()

    today = datetime.today().date()
    expected_delta = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 90,
        "yearly": 365
    }.get(frequency.lower(), 7)

    freshness_cutoff = today - timedelta(days=expected_delta)
    return "✅ Fresh" if last_date >= freshness_cutoff else "⚠️ Stale"

def generate_freshness_dashboard_BKP():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT table_name, frequency, server_name FROM freshness_metadata")
    records = cursor.fetchall()
    conn.close()

    dashboard = []

    for table_name, frequency, server_name in records:
        print(f"🔍 Checking: {table_name} | Agent: {server_name} | Freq: {frequency}")
        agent_conn = get_agent_connection_by_name(server_name)

        if not agent_conn:
            status = "❌ Agent Not Found"
            last_date = None
            schema_info = {"status": "❌ Agent Missing"}
        else:
            last_date = fetch_latest_load_date(agent_conn, table_name)
            status = check_freshness_status(last_date, frequency)

            try:
                expected_schema = get_expected_schema(table_name)
                source = agent_conn["source"].lower()
                df = None

                actual_pks = []
                expected_pks = []

                if expected_schema and source in ["sqlite", "snowflake", "azure", "mssql", "sqlserver", "postgresql", "oracle"]:
                    if source == "sqlite":
                        df = pd.read_sql_query(
                            f"SELECT * FROM {table_name} LIMIT 100",
                            sqlite3.connect(agent_conn["sql_database"])
                        )

                    elif source == "snowflake":
                        sf_conn = snowflake.connector.connect(
                            user=agent_conn["uid"],
                            password=agent_conn["pwd"],
                            account=agent_conn["account"],
                            warehouse=agent_conn["warehouse"],
                            database=agent_conn["sf_database"],
                            schema=agent_conn["schema"]
                        )
                        query = f'SELECT * FROM {table_name} LIMIT 100'
                        df = pd.read_sql(query, sf_conn)

                        actual_pks = fetch_primary_keys_snowflake(agent_conn, table_name)
                        pk_fk = get_pk_fk_expectation(table_name)
                        expected_pks = [col.lower() for col, meta in pk_fk.items() if meta.get("pk")]
                        print(f"📌 PK Expectation Raw: {pk_fk}")
                        print(f"🔍 Expected PKs from CSV: {expected_pks}")
                        print(f"🔍 Actual PKs from DB: {actual_pks}")

                    config = {
                        "expected_schema": expected_schema,
                        "date_column": "load_date",
                        "critical_columns": list(expected_schema.keys())[:3],
                        "min_volume": 10,
                        "max_volume": 100000,
                        "freshness_threshold_days": 7,
                        "agent_conn": agent_conn,
                        "table_name": table_name,
                        "actual_primary_keys": actual_pks,
                        "expected_primary_keys": expected_pks
                    }

                    if df is not None and not df.empty:
                        all_results = run_all_checks(df, config)
                        schema_info = all_results["schema_validation"]
                        # ✨ Capture data validation results
                        data_validation_info = all_results["data_validation"]
                    else:
                        schema_info = {"status": "⚠️ Empty DataFrame", "reason": "No data to validate"}
                        # ✨ Create empty data validation structure
                        data_validation_info = {
                            "nulls": {},
                            "duplicates": 0,
                            "date_format_errors": {},
                            "non_numeric_columns": []
                        }
                else:
                    schema_info = {"status": "⚠️ Skipped", "reason": "Schema or source unsupported"}
            except Exception as e:
                print(f"⚠️ Schema check failed for {table_name}: {e}")
                schema_info = {"status": "❌ Error", "reason": str(e)}

        dashboard.append({
            "table": table_name,
            "frequency": frequency,
            "agent": server_name,
            "last_date": last_date.strftime("%Y-%m-%d") if last_date else "N/A",
            "status": status,
            "schema": schema_info,
            # ✨ Add data validation to dashboard results
            "data_validation": data_validation_info
        })
    dashboard = deduplicate_freshness_results(dashboard)
    return dashboard



def generate_freshness_dashboard(agent_name=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = "SELECT table_name, frequency, server_name FROM freshness_metadata"
    if agent_name:
        query += " WHERE server_name = ?"
        cursor.execute(query, (agent_name,))
    else:
        cursor.execute(query)
    records = cursor.fetchall()
    conn.close()

    dashboard = []

    for table_name, frequency, server_name in records:
        print(f"🔍 Checking: {table_name} | Agent: {server_name} | Freq: {frequency}")
        agent_conn = get_agent_connection_by_name(server_name)

        if not agent_conn:
            status = "❌ Agent Not Found"
            last_date = None
            schema_info = {"status": "❌ Agent Missing"}
            data_validation_info = {
                "nulls": {},
                "duplicates": 0,
                "date_format_errors": {},
                "non_numeric_columns": []
            }
        else:
            last_date = fetch_latest_load_date(agent_conn, table_name)
            status = check_freshness_status(last_date, frequency)

            try:
                expected_schema = get_expected_schema(table_name)
                source = agent_conn["source"].lower()
                df = None

                actual_pks = []
                expected_pks = []

                if expected_schema and source in ["sqlite", "snowflake", "azure", "mssql", "sqlserver", "postgresql", "oracle"]:
                    if source == "sqlite":
                        df = pd.read_sql_query(
                            f"SELECT * FROM {table_name} LIMIT 100",
                            sqlite3.connect(agent_conn["sql_database"])
                        )

                    elif source == "snowflake":
                        sf_conn = snowflake.connector.connect(
                            user=agent_conn["uid"],
                            password=agent_conn["pwd"],
                            account=agent_conn["account"],
                            warehouse=agent_conn["warehouse"],
                            database=agent_conn["sf_database"],
                            schema=agent_conn["schema"]
                        )
                        full_table = f"{agent_conn['sf_database']}.{agent_conn['schema']}.{table_name}"
                        query = f'SELECT * FROM {full_table} LIMIT 100'
                        print(f"📥 Executing query: {query}")
                        df = pd.read_sql(query, sf_conn)

                        actual_pks = fetch_primary_keys_snowflake(agent_conn, table_name)
                        pk_fk = get_pk_fk_expectation(table_name)
                        expected_pks = [col.lower() for col, meta in pk_fk.items() if meta.get("pk")]
                        print(f"📌 PK Expectation Raw: {pk_fk}")
                        print(f"🔍 Expected PKs from CSV: {expected_pks}")
                        print(f"🔍 Actual PKs from DB: {actual_pks}")

                    config = {
                        "expected_schema": expected_schema,
                        "date_column": "load_date",
                        "critical_columns": list(expected_schema.keys())[:3],
                        "min_volume": 10,
                        "max_volume": 100000,
                        "freshness_threshold_days": 7,
                        "agent_conn": agent_conn,
                        "table_name": table_name,
                        "actual_primary_keys": actual_pks,
                        "expected_primary_keys": expected_pks
                    }

                    if df is not None and not df.empty:
                        all_results = run_all_checks(df, config)
                        schema_info = all_results["schema_validation"]
                        data_validation_info = all_results["data_validation"]
                    else:
                        schema_info = {"status": "⚠️ Empty DataFrame", "reason": "No data to validate"}
                        data_validation_info = {
                            "nulls": {},
                            "duplicates": 0,
                            "date_format_errors": {},
                            "non_numeric_columns": []
                        }
                else:
                    schema_info = {"status": "⚠️ Skipped", "reason": "Schema or source unsupported"}
                    data_validation_info = {
                        "nulls": {},
                        "duplicates": 0,
                        "date_format_errors": {},
                        "non_numeric_columns": []
                    }
            except Exception as e:
                print(f"⚠️ Schema check failed for {table_name}: {e}")
                schema_info = {"status": "❌ Error", "reason": str(e)}
                data_validation_info = {
                    "nulls": {},
                    "duplicates": 0,
                    "date_format_errors": {},
                    "non_numeric_columns": []
                }

        dashboard.append({
            "table": table_name,
            "frequency": frequency,
            "agent": server_name,
            "last_date": last_date.strftime("%Y-%m-%d") if last_date else "N/A",
            "status": status,
            "schema": schema_info,
            "data_validation": data_validation_info
        })

    dashboard = deduplicate_freshness_results(dashboard)
    return dashboard
