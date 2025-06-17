import logging

# Setup logging
logging.basicConfig(
    filename='sqlquery_log.txt',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Import needed libraries at the top of your script
import os
import streamlit as st
import sqlite3
import pandas as pd
import json
import tiktoken
from typing import List, Dict, Any, Tuple, Optional
from openai import OpenAI
from config import client, DB_NAME
from langchain.tools import tool
from DbUtils.DbOperations import load_feedback_data
from utils import create_faiss_index, retrieve_feedback_insights


token_usage_records: List[Dict[str, Any]] = []  # Enhanced to store operation descriptions and counts
# Initialize tiktoken encoder for token counting
encoder = tiktoken.get_encoding("cl100k_base")  # Using OpenAI's default encoding

def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    if not text:
        return 0
    return len(encoder.encode(text))


def log_token_usage(description: str, text: str) -> int:
    """Log the token usage for a given operation and record it globally."""
    token_count = count_tokens(text)
    # Store both description and count for better reporting
    token_usage_records.append({"description": description, "count": token_count})
    logging.info(f"📊 TOKEN USAGE - {description}: {token_count} tokens")
    return token_count


def get_total_token_count() -> Tuple[int, List[Dict[str, Any]]]:
    """Calculate and return the total token count and detailed usage records."""
    total = sum(record["count"] for record in token_usage_records)
    return total, token_usage_records


def print_token_usage_report():
    """Print a detailed report of token usage for all operations."""
    total, records = get_total_token_count()
    
    logging.info("\n" + "="*50)
    logging.info("📊 TOKEN USAGE REPORT 📊")
    logging.info("="*50)
    
    # Group by description to consolidate multiple calls to the same operation
    grouped_usage = {}
    for record in records:
        desc = record["description"]
        if desc in grouped_usage:
            grouped_usage[desc] += record["count"]
        else:
            grouped_usage[desc] = record["count"]
    
    # Print each operation's usage
    for desc, count in grouped_usage.items():
        percentage = (count / total) * 100 if total > 0 else 0
        logging.info(f"{desc}: {count} tokens ({percentage:.1f}%)")
    
    logging.info("-"*50)
    logging.info(f"TOTAL TOKEN USAGE: {total} tokens")
    logging.info("="*50)
    
    return total


def retrieve_feedback_for(question: str) -> List[str]:
    """
    Loads all feedback logs from the DB, builds a FAISS index,
    and returns the top feedback_insights for this question.
    """
    logging.info("🔍 FEEDBACK RETRIEVAL AGENT: Loading feedback data...")
    try:
        # 1. Pull every feedback record
        feedback_logs = load_feedback_data()
        # 2. Index them
        logging.info("🔍 FEEDBACK RETRIEVAL AGENT: Building FAISS index...")
        faiss_idx, indexed_logs = create_faiss_index(feedback_logs)
        # 3. Retrieve the most relevant feedback snippets
        logging.info("🔍 FEEDBACK RETRIEVAL AGENT: Finding relevant feedback...")
        insights = retrieve_feedback_insights(question, faiss_idx, indexed_logs)
        
        # Log token usage for feedback retrieval
        if insights:
            combined_insights = "\n".join(insights)
            log_token_usage("Feedback Retrieval", combined_insights)
        
        return insights
    except Exception as e:
        logging.info(f"❌ FEEDBACK RETRIEVAL AGENT: Error retrieving feedback - {str(e)}")
        return []  # Return empty list on error to allow system to continue


def execute_query(sql_query, category=None):
    logging.info("🔄 SQL EXECUTOR: Executing database query...")
    
    # Get the table name that might be expected in this query
    table_name = get_table_name_by_category(category) if category else "raw_data"
    
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        
        # Handle the case where no rows are returned
        if not rows:
            logging.info("⚠️ SQL EXECUTOR: Query returned no results")
            return {"columns": [], "rows": [], "warning": "Query returned no results. Please check your filters or criteria."}
            
        columns = [desc[0] for desc in cursor.description]
        result = {"columns": columns, "rows": rows}
        logging.info(f"✅ SQL EXECUTOR: Query completed successfully with {len(rows)} rows returned")

                # Print query results in a formatted way
        logging.info("\n=== QUERY RESULTS ===")
        logging.info(" | ".join(columns))
        logging.info("-" * (sum(len(col) for col in columns) + 3 * (len(columns) - 1)))
        for row in rows:
            logging.info(" | ".join(str(cell) for cell in row))
        logging.info("====================\n")


        return result
    except sqlite3.Error as sql_e:
        error_msg = str(sql_e)
        logging.info(f"❌ SQL EXECUTOR: SQLite error - {error_msg}")
        
        # Provide more specific error messages for common SQL errors
        if "no such column" in error_msg.lower():
            column_name = error_msg.split("no such column: ")[1].split()[0] if "no such column: " in error_msg else "unknown"
            return {"error": f"Column '{column_name}' not found. Please check your query and schema."}
        elif "syntax error" in error_msg.lower():
            return {"error": "SQL syntax error. Please check your query format."}
        else:
            return {"error": f"Database error: {error_msg}"}
    except Exception as e:
        error_msg = str(e)
        logging.info(f"❌ SQL EXECUTOR: General error - {error_msg}")
        return {"error": f"Error executing query: {error_msg}"}
    finally:
        if conn:
            conn.close()


# PW metadata schema
PW = {
    "columns_and_definitions": {
        "REPORT_DATE": "As-of date of the report generation",
        "BOOK": "Trading book identifier",
        "BOOK_ATTR6": "Business area classification",
        "BOOK_ATTR7": "Cost Allocation Indicator",
        "BOOK_ATTR8": "Detailed business classification",
        "USR_VAL4": "Route to market mechanism",
        "TGROUP1": "Primary trading strategy",
        "TGROUP2": "Secondary trading strategy",
        "SEGMENT": "Business segment",
        "Start Date": "Start of trade delivery",
        "End Date": "End of trade delivery",
        "BUCKET": "Product bucket label",
        "HORIZON": "Delivery term or horizon",
        "METHOD": "Valuation method used",
        "VOLUME_BL": "Base Load Volume",
        "VOLUME_PK": "Peak Load Volume",
        "VOLUME_OFPK": "Off-Peak Volume",
        "MKT_VAL_BL": "Base Load Market Value",
        "MKT_VAL_PK": "Peak Load Market Value",
        "MKT_VAL_OFPK": "Off-Peak Market Value",
        "TRD_VAL_BL": "Base Load Trade Value",
        "TRD_VAL_PK": "Peak Load Trade Value",
        "TRD_VAL_OFPK": "Off-Peak Trade Value"
    }
}

# CO2 metadata schema
CO2 = {
    "columns_and_definitions": {
        "REPORT_DATE": "As-of date of the report generation",
        "BOOK": "Trading book identifier",
        "BOOK_ATTR3": "Business type or classification",
        "BOOK_ATTR5": "Hedging or Trading purpose marker",
        "BOOK_ATTR6": "Cost Allocation Indicator",
        "BOOK_ATTR7": "Allocation Type",
        "BOOK_ATTR8": "Detailed Business Classification",
        "USR_VAL4": "Route to market mechanism",
        "TGROUP1": "Primary trading strategy",
        "TGROUP2": "Secondary trading strategy",
        "MKT1": "Market type or instrument (e.g., CO2)",
        "COMP1": "Compliance or Forecast type",
        "SEGMENT": "Business segment",
        "BUCKET_START": "Bucket start date",
        "BUCKET_END": "Bucket end date",
        "BUCKET": "Product bucket label",
        "HORIZON": "Delivery year or term",
        "VOLUME": "Traded or delivered quantity",
        "MKTVAL": "Market Value",
        "TRDVAL": "Trade Value",
        "TRDPRC": "Trade Price"
    }
}

# NG metadata schema
NG = {
    "columns_and_definitions": {
        "REPORT_DATE": "As-of date of the report",
        "BOOK": "Trading book identifier",
        "BOOK_ATTR3": "Commodity type",
        "BOOK_ATTR5": "Business purpose",
        "BOOK_ATTR6": "Business segment or unit",
        "BOOK_ATTR7": "Allocation Type",
        "BOOK_ATTR8": "Business area classification",
        "USR_VAL4": "Route to market",
        "TGROUP1": "Primary strategy",
        "TGROUP2": "Secondary strategy",
        "SEGMENT": "Business segment",
        "START DATE": "Start of delivery",
        "END DATE": "End of delivery",
        "BUCKET": "Product bucket label",
        "HORIZON": "Delivery horizon",
        "METHOD": "Valuation Method",
        "VOLUME": "Volume",
        "VOLUME_TOTAL": "Total volume",
        "QTY_PHY": "Physical quantity",
        "MKT_VAL": "Market value",
        "QTY_FIN": "Financial quantity",
        "TRD_VAL": "Trade value"
    }
}


def get_schema_by_category(category):
    """Get schema for a specific category with fallback."""
    logging.info(f"📋 SCHEMA MANAGER: Retrieving schema for {category} category...")
    if not category:
        logging.info("⚠️ SCHEMA MANAGER: No category provided, using Power as default")
        return PW  # Default to Power if no category specified
        
    if category.lower() == "power":
        return PW
    elif category.lower() == "co2":
        return CO2 
    elif category.lower() in ["natural gas", "ng"]:
        return NG
    else:
        logging.info(f"⚠️ SCHEMA MANAGER: Unknown category: {category}, using Power as default")
        return PW  # Default to Power for unknown categories

def get_table_name_by_category(category):
    """Get the appropriate table name for a specific category with fallback.
    
    Args:
        category (str): The energy category (power, co2, ng, etc.)
        
    Returns:
        str: The table name to use for the specified category
    """
    logging.info(f"📋 TABLE NAME MANAGER: Determining table name for {category} category...")
    
    if not category:
        logging.info("⚠️ TABLE NAME MANAGER: No category provided, using PW_raw_data as default")
        return "PW_raw_data"  # Default to Power if no category specified
        
    if category.lower() == "power":
        return "PW_raw_data"
    elif category.lower() == "co2":
        return "CO2_raw_data"
    elif category.lower() in ["natural gas", "ng"]:
        return "NG_raw_data"
    else:
        logging.info(f"⚠️ TABLE NAME MANAGER: Unknown category: {category}, using PW_raw_data as default")
        return "PW_raw_data"  # Default to Power for unknown categories


# SQL generation tool with "Net open position" handling
@tool
def generate_sql_tool(
        input_text: str,
        category: str,
        feedback_text: str = ""
    ) -> str:
    """Generate an SQLite query from natural language using OpenAI,
    now prefaced with any historical feedback warnings."""
    
    logging.info("🤖 SQL GENERATOR AGENT: Starting SQL generation process...")
    
    # Get the appropriate table name for this category
    table_name = get_table_name_by_category(category)
    logging.info(f"🤖 SQL GENERATOR AGENT: Using table {table_name} for {category} category")

    # 1. Fetch the JSON schema for this category
    schema = get_schema_by_category(category)
    if schema is None:
        logging.info("❌ SQL GENERATOR AGENT: Failed to retrieve schema")
        return "Error: Unknown category. Using Power category as default."
    
    # 2. Serialize just the columns_and_definitions map
    columns_map = schema["columns_and_definitions"]
    schema_json = json.dumps(columns_map)
    
    # 3. System prompt now includes feedback_text at the top
    if feedback_text:
        logging.info(f"📋 SQL GENERATOR AGENT: Incorporating feedback into SQL generation:\n{feedback_text}")
    else:
        logging.info("ℹ️ SQL GENERATOR AGENT: No feedback text provided for SQL generation.")

    # Enhanced system message with net open position handling instruction
    system_msg = (
        (feedback_text + "\n") if feedback_text else ""
    ) + f"""Only output raw, runnable SQLite SQL using {table_name} as the table name.
    
    IMPORTANT INSTRUCTION: Treat 'Net open position' questions as the sum of VOLUME_BL for the REPORT_DATE 
    unless the context clearly refers to monetary value, in which case use MKT_VAL_BL.

    CRITICAL: You MUST prefix ALL column aliases in SELECT statements with filter contexts from WHERE clauses.
    For example, if filtering by BOOK = 'GTUO', prefix column aliases with 'GTUO_'.

    IMPORTANT: When the user asks for trends across consecutive Report_Dates (e.g., "5 consecutive decreases"), you MUST:
    - First rank or number rows per BOOK ordered by Report_Date descending.
    - Compare the values in strict order (e.g., VOLUME_BL of latest day vs previous day, etc.).
    - Ensure you're using only the latest N Report_Dates per BOOK, not all historical data."""

    # 4. Build the user prompt
    user_prompt = f"""
    You are a SQLite-SQL expert. Below is the table's column schema as JSON:
    {schema_json}

    Table name to use: {table_name}

    Instructions:
    - Always include 'Report_Date' as a selected column in the query results.
    - Always include ALL columns that are relevant to the user's request in the SELECT statement.
    - Use {table_name} as the table name in your queries.
    - Use **only** the JSON keys as column names (case-sensitive).
    - Ensure the Query is ordered by 'Report_Date' (ascending or descending based on context or default to descending).
    - The JSON _values_ are human-readable descriptions; ignore them for naming.
    - 'Report_Date' is formatted as YYYY-MM-DD; if user provides another format, adjust it.
    - Handle relative date ranges (e.g., "last 6 months") through 'Report_Date' comparisons.
    - Return **only** raw runnable SQL — no explanations, no markdown fences, no comments.
    - If you reference any column not listed in the JSON keys, the query will fail.
    - IMPORTANT: For 'Net open position' questions, use VOLUME_BL column for quantity-based analysis, and MKT_VAL_BL for monetary value analysis.
    - If the user requests checking for changes over the latest N consecutive Report_Date rows (e.g., decreasing trend), retrieve only the latest N+1 records per group (using ROW_NUMBER or window functions) and compare them in sequence.
    - Use CASE WHEN or aggregation to validate that the decreasing or increasing condition holds across all required rows.

    User request:
    {input_text}
    """

    # Count tokens for request
    input_tokens = log_token_usage("SQL Generator Input", system_msg + user_prompt)
    logging.info(f"🤖 SQL GENERATOR AGENT: Prompt prepared ({input_tokens} tokens)")

    # 5. Call the LLM with error handling
    try:
        logging.info("🤖 SQL GENERATOR AGENT: Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system",  "content": system_msg},
                {"role": "user",    "content": user_prompt},
            ]
        )
        sql = response.choices[0].message.content.strip()
        
        # Count tokens for response
        output_tokens = log_token_usage("SQL Generator Output", sql)
        logging.info(f"🤖 SQL GENERATOR AGENT: Received SQL query ({output_tokens} tokens)")
        
        # 6. Strip any code fences
        if sql.startswith("```"):
            parts = sql.split("```")
            sql = parts[1] if len(parts) > 1 else sql
            # Check for SQL language specification
            if sql.lower().startswith("sql"):
                sql = sql[3:].strip()
        
        # 7. Replace any hardcoded placeholder with actual table name
        sql = sql.replace("tableName", table_name)
        
        logging.info("✅ SQL GENERATOR AGENT: SQL generation completed")
        return sql
    except Exception as e:
        error_msg = str(e)
        logging.info(f"❌ SQL GENERATOR AGENT: Error generating SQL - {error_msg}")
        return f"Error generating SQL: {error_msg}"

 
def assess_question_complexity(question: str, category: str = None) -> bool:
    """Determine if a question requires multi-query processing."""
    logging.info("🧠 COMPLEXITY ASSESSOR: Analyzing question complexity...")
    
    # Get schema if category is provided
    schema_info = ""
    if category:
        schema = get_schema_by_category(category)
        if schema:
            schema_info = f"Schema information for {category}: {json.dumps(schema['columns_and_definitions'])}"
    
    prompt = f"""
    Analyze this question about energy trading data:
    "{question}"

    {schema_info}

    Think carefully before answering:
    - Break down what information is needed to answer this question
    - Consider if all of these can be logically combined in one SQL statement
    - Consider if intermediate calculations or processing would make this clearer

    Is this question complex enough to require multiple SQL queries to answer completely?
    A question requires multiple queries ONLY if it:
    1. Involves multiple unrelated data points that can't be combined in a single SQL query
    2. Requires complex calculations across different aggregations that can't be done in one query
    3. Involves data transformations that can't be done in a single SQL statement

    For simple filters, sorts, grouping, counts, sums, averages, or joining related data - use a SINGLE query.

    Answer with ONLY "yes" or "no".
    """
    
    # Count tokens for complexity assessment
    input_tokens = log_token_usage("Complexity Assessment Input", prompt)
    logging.info(f"🧠 COMPLEXITY ASSESSOR: Prompt prepared ({input_tokens} tokens)")
    
    try:
        logging.info("🧠 COMPLEXITY ASSESSOR: Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a SQL complexity analyzer. Only answer with 'yes' or 'no'."},
                {"role": "user", "content": prompt}
            ]
        )
        
        answer = response.choices[0].message.content.strip().lower()
        
        # Count tokens for response
        output_tokens = log_token_usage("Complexity Assessment Output", answer)
        
        is_complex = "yes" in answer
        logging.info(f"🧠 COMPLEXITY ASSESSOR: Question {'is complex' if is_complex else 'is simple'}")
        return is_complex  # True if complex, False if simple
    except Exception as e:
        logging.info(f"❌ COMPLEXITY ASSESSOR: Error assessing complexity - {str(e)}")
        # Default to simple in case of error
        return False


# Query planning function with improved error handling
def plan_queries(user_question: str, category: str = None) -> List[str]:
    """Break down complex questions into simpler sub-questions."""
    logging.info("📝 QUERY PLANNER: Planning query breakdown...")
    
    # Get schema if category is provided
    schema_info = ""
    if category:
        schema = get_schema_by_category(category)
        if schema:
            schema_info = f"Available columns for {category}: {list(schema['columns_and_definitions'].keys())}"
    
    # Add net open position instruction
    net_position_info = """
    - For 'Net open position' analysis:
      - Use VOLUME_BL column for quantity-based analysis
      - Use MKT_VAL_BL for monetary value analysis
    """
    
    prompt = f"""
    Analyze this analytical question about energy trading data and break it down into simpler sub-questions if needed:
    "{user_question}"

    {schema_info}
    
    Domain knowledge:
    - In energy trading, "books" refers to trading portfolios or positions identified by unique codes in the data
    - "Baseload" refers to a specific type of energy contract for electricity that provides consistent power
    - The database contains power trading records with baseload, peak, and off-peak volume, price, and market value information
    {net_position_info}
        IMPORTANT: Only break this into multiple questions if absolutely necessary!
        
    A question requires multiple queries ONLY if it:
    1. Involves multiple unrelated data points that can't be combined in a single SQL query
    2. Requires complex calculations across different aggregations
    3. Involves data transformations that can't be done in a single SQL statement
    
    For simple filters, sorts, grouping, counts, sums, averages, or joining related data - use a SINGLE query.

    Format your response as a JSON string with this structure:
    {{"questions": ["First sub-question?", "Second sub-question?"]}}
    
    If this is a simple question that needs only one query, return exactly:
    {{"questions": ["SINGLE"]}}

    Return ONLY the JSON string with no additional text.
    """

    # Count tokens for query planning
    input_tokens = log_token_usage("Query Planning Input", prompt)
    logging.info(f"📝 QUERY PLANNER: Prompt prepared ({input_tokens} tokens)")
    
    try:
        logging.info("📝 QUERY PLANNER: Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a data analytics planner specializing in energy trading data."},
                {"role": "user", "content": prompt}
            ]
        )

        response_text = response.choices[0].message.content.strip()
        
        # Count tokens for response
        output_tokens = log_token_usage("Query Planning Output", response_text)

        # Check if the response has JSON code block formatting and extract if needed
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        # Parse the response as JSON with better error handling
        try:
            result = json.loads(response_text)
            if "questions" in result:
                sub_questions = result["questions"]
                logging.info(f"📝 QUERY PLANNER: Generated {len(sub_questions)} sub-questions")
                return sub_questions
            else:
                logging.info("⚠️ QUERY PLANNER: No 'questions' key in response, returning original question")
        except json.JSONDecodeError:
            logging.info(f"❌ QUERY PLANNER: Invalid JSON: {response_text}")
        
        # Return original question if we can't parse the response
        logging.info("📝 QUERY PLANNER: Fallback to original question")
        return [user_question]  # Fallback to original question
    except Exception as e:
        logging.info(f"❌ QUERY PLANNER: Error planning queries: {e}")
        # If parsing fails, return the original question
        return [user_question]


# Query plan validation with improved error handling
def validate_query_plan(original_question: str, sub_questions: List[str], category: str = None) -> bool:
    """Validates if breaking into sub-questions is necessary."""
    logging.info("✅ PLAN VALIDATOR: Validating query plan necessity...")
    
    # Safety check for input
    if not sub_questions:
        logging.info("⚠️ PLAN VALIDATOR: No sub-questions provided, assuming single query is sufficient")
        return False
    
    # Get schema if category is provided
    schema_info = ""
    if category:
        schema = get_schema_by_category(category)
        if schema:
            schema_info = f"Available columns for {category}: {list(schema['columns_and_definitions'].keys())}"
    
    # Add net position instruction
    net_position_info = "Remember to use VOLUME_BL for volume-based 'Net open position' and MKT_VAL_BL for monetary value."
    
    prompt = f"""
    Original question: "{original_question}"
    
    {schema_info}
    {net_position_info}
    
    Proposed sub-questions:
    {json.dumps(sub_questions)}
    
    Is breaking the original question into these sub-questions NECESSARY, or can the original question be answered with a single SQL query?
    
    Answer only with "NECESSARY" or "UNNECESSARY".
    """
    
    # Count tokens for validation
    input_tokens = log_token_usage("Plan Validation Input", prompt)
    logging.info(f"✅ PLAN VALIDATOR: Prompt prepared ({input_tokens} tokens)")
    
    try:
        logging.info("✅ PLAN VALIDATOR: Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a validator for query planning decisions."},
                {"role": "user", "content": prompt}
            ]
        )
        
        answer = response.choices[0].message.content.strip().upper()
        
        # Count tokens for response
        output_tokens = log_token_usage("Plan Validation Output", answer)
        
        is_necessary = "NECESSARY" in answer
        logging.info(f"✅ PLAN VALIDATOR: Breaking into sub-questions is {'necessary' if is_necessary else 'unnecessary'}")
        return is_necessary
    except Exception as e:
        logging.info(f"❌ PLAN VALIDATOR: Error validating plan - {str(e)}")
        # Default to unnecessary in case of error
        return False


# Multi-query execution with improved error handling
def execute_multi_query(sub_questions: List[str], category=None) -> List[Dict[str, Any]]:
    """Execute multiple queries and return their results."""
    logging.info("🔄 MULTI-QUERY EXECUTOR: Starting multi-query execution...")
    results = []
    
    total_tokens = 0
    
    for i, question in enumerate(sub_questions):
        try:
            logging.info(f"\n🔄 MULTI-QUERY EXECUTOR: Processing sub-question {i+1}/{len(sub_questions)}: {question}")
            sql_query = generate_sql_tool.run({
                "input_text": question,
                "category": category
            })
            
            # Check if SQL generation failed
            if isinstance(sql_query, str) and sql_query.startswith("Error"):
                logging.info(f"⚠️ MULTI-QUERY EXECUTOR: SQL generation failed - {sql_query}")
                results.append({
                    "question": question,
                    "sql": "Error generating SQL",
                    "result": {"error": sql_query}
                })
                continue
                
            logging.info(f"🔄 MULTI-QUERY EXECUTOR: Executing SQL: {sql_query}")
            result = execute_query(sql_query, category)  # Pass category to execute_query
            
            # Track SQL size for token counting
            sql_tokens = count_tokens(sql_query)
            total_tokens += sql_tokens
            
            results.append({
                "question": question,
                "sql": sql_query,
                "result": result
            })
        except Exception as e:
            error_msg = str(e)
            logging.info(f"❌ MULTI-QUERY EXECUTOR: Error processing question '{question}': {error_msg}")
            results.append({
                "question": question,
                "sql": "Error occurred",
                "result": {"error": f"Error processing this sub-question: {error_msg}"}
            })
    
    logging.info(f"✅ MULTI-QUERY EXECUTOR: Completed execution of {len(sub_questions)} queries (Total SQL tokens: {total_tokens})")
    return results


# Results synthesis with improved error handling
def synthesize_results(
        user_question: str,
        query_results: List[Dict[str, Any]],
        feedback_text: str = ""
    ) -> str:
    """Combine multiple query results into a comprehensive answer with feedback context."""
    logging.info("🧩 RESULTS SYNTHESIZER: Combining query results into comprehensive answer...")
    
    # Check if we have any results to synthesize
    if not query_results:
        return "No query results were available to synthesize. Please try reformulating your question."
    
    # 1. Format the raw query results
    formatted_results = ""
    error_count = 0
    
    for idx, res in enumerate(query_results):
        formatted_results += f"\nSub-question {idx+1}: {res['question']}\n"
        formatted_results += f"SQL: {res['sql']}\n"
        if "error" in res["result"]:
            formatted_results += f"Error: {res['result']['error']}\n"
            error_count += 1
        elif "warning" in res["result"]:
            formatted_results += f"Warning: {res['result']['warning']}\n"
            # Add empty result notation
            formatted_results += " | ".join(res["result"]["columns"]) + "\n"
            formatted_results += "[No data returned]\n"
        else:
            formatted_results += " | ".join(res["result"]["columns"]) + "\n"
            for row in res["result"]["rows"]:
                formatted_results += " | ".join(str(cell) for cell in row) + "\n"

    # Check if all queries failed
    if error_count == len(query_results):
        return "All queries failed to execute. Please check your question or try with different criteria."

    # 2. Build the synthesis prompt, with feedback_text up top
    synthesis_prompt = f"""
    {feedback_text}

    Original user question: "{user_question}"

    Results from multiple queries:
    {formatted_results}

    Please synthesize these results into a comprehensive, coherent answer that fully addresses the original question.
    Include relevant numbers and insights from all the queries. Be concise but thorough.

    For any queries that had errors or returned no data, acknowledge this in your response and provide any partial insights 
    you can from the successful queries.
    """

    # Count tokens for synthesis request
    input_tokens = log_token_usage("Results Synthesis Input", synthesis_prompt)
    logging.info(f"🧩 RESULTS SYNTHESIZER: Prompt prepared ({input_tokens} tokens)")

    try:
        # 3. Call the LLM
        logging.info("🧩 RESULTS SYNTHESIZER: Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system",  "content": "You are a data analyst who synthesizes information from multiple SQL queries into cohesive insights."},
                {"role": "user",    "content": synthesis_prompt},
            ]
        )

        synthesis = response.choices[0].message.content.strip()
        
        # Count tokens for response
        output_tokens = log_token_usage("Results Synthesis Output", synthesis)
        logging.info(f"✅ RESULTS SYNTHESIZER: Synthesis completed ({output_tokens} tokens)")
        
        return synthesis
    except Exception as e:
        error_msg = str(e)
        logging.info(f"❌ RESULTS SYNTHESIZER: Error synthesizing results - {error_msg}")
        # Provide a fallback synthesis
        return f"Unable to synthesize results due to an error. Raw query results are available but synthesis failed with: {error_msg}"


# Coordinator function for simple queries with improved error handling
def run_graph_agent(prompt: str, category=None, feedback_text: str = "") -> Dict[str, Any]:
    """Takes a natural language prompt and returns SQL query results,
    now enriched with any historical feedback warnings."""
    logging.info("🎮 QUERY COORDINATOR: Processing simple query...")
    
    try:
        # Step 1: Generate SQL using OpenAI (including feedback_text)
        sql_query = generate_sql_tool.run({
            "input_text": prompt, 
            "category": category,
            "feedback_text": feedback_text
        })
        
        # Check if SQL generation failed
        if isinstance(sql_query, str) and sql_query.startswith("Error"):
            logging.info(f"⚠️ QUERY COORDINATOR: SQL generation failed - {sql_query}")
            return {"error": sql_query}
            
        logging.info(f"🎮 QUERY COORDINATOR: Generated SQL - {sql_query}")

        # Step 2: Execute the SQL and return the result
        result = execute_query(sql_query, category)  # Pass category to execute_query
        
        # Add the SQL query to the result for transparency
        result["sql_query"] = sql_query
        
        logging.info("✅ QUERY COORDINATOR: Simple query processing completed")
        return result
    except Exception as e:
        error_msg = str(e)
        logging.info(f"❌ QUERY COORDINATOR: Error processing query - {error_msg}")
        return {"error": f"Error processing query: {error_msg}", "sql_query": "Error occurred"}


def run_orchestrated_agent(user_question, category=None, conversation_history=None):
    """Orchestrates multi-query execution for complex questions with memory."""
    # Reset our token log so each run is fresh
    token_usage_records.clear()
    logging.info("\n🎭 ORCHESTRATION AGENT: Starting orchestration process...")
    logging.info(f"🎭 ORCHESTRATION AGENT: Processing question: {user_question}")
    
    # Start tracking total token usage
    total_tokens = 0
    total_tokens += count_tokens(user_question)
    
    # Check if conversation_history is provided, if not initialize as empty list
    if conversation_history is None:
        conversation_history = []
    
    # Special handling for net open position queries
    is_net_position_query = "net open position" in user_question.lower() or "open position" in user_question.lower()
    if is_net_position_query:
        logging.info("🎭 ORCHESTRATION AGENT: Detected net open position query - applying special handling")
        
        # Determine if it's volume or value based
        is_value_based = any(term in user_question.lower() for term in ["value", "money", "dollar", "financial", "price"])
        
        column_to_use = "MKT_VAL_BL" if is_value_based else "VOLUME_BL"
        logging.info(f"🎭 ORCHESTRATION AGENT: Using {column_to_use} for net position query")
    
    # 1. Add the user question to memory
    conversation_history.append({"role": "user", "content": user_question})
    
    # Retrieve relevant feedback for this question
    try:
        feedback_insights = retrieve_feedback_for(user_question)
        feedback_text = "\n".join(feedback_insights) if feedback_insights else ""
    except Exception as e:
        logging.info(f"⚠️ ORCHESTRATION AGENT: Error retrieving feedback - {e}")
        feedback_text = ""
    
    # 2. Assess complexity based on memory-aware prompt (optional: pass memory if needed)
    logging.info("🎭 ORCHESTRATION AGENT: Assessing question complexity...")
    try:
        is_complex = assess_question_complexity(user_question, category)
        
        if not is_complex:
            logging.info("🎭 ORCHESTRATION AGENT: Question is simple - using single query approach")
            result = run_graph_agent(user_question, category, feedback_text)
            
            # 3. Add the assistant response to memory
            result_str = str(result)
            conversation_history.append({"role": "assistant", "content": result_str})
            total_tokens += count_tokens(result_str)
            
            # Generate token usage report
            final_token_count = print_token_usage_report()
            
            logging.info(f"✅ ORCHESTRATION AGENT: Simple query completed (Total tokens: {final_token_count})")
            return result, False
        
        logging.info("🎭 ORCHESTRATION AGENT: Question is complex - planning sub-questions...")
        sub_questions = plan_queries(user_question, category)
        
        # Track tokens for sub-questions
        for q in sub_questions:
            total_tokens += count_tokens(q)
        
        if len(sub_questions) == 1 and sub_questions[0] == "SINGLE":
            logging.info("🎭 ORCHESTRATION AGENT: Planner determined a single query is sufficient")
            result = run_graph_agent(user_question, category, feedback_text)
            
            result_str = str(result)
            conversation_history.append({"role": "assistant", "content": result_str})
            total_tokens += count_tokens(result_str)
            
            # Generate token usage report
            final_token_count = print_token_usage_report()
            
            logging.info(f"✅ ORCHESTRATION AGENT: Single query completed (Total tokens: {final_token_count})")
            return result, False
        
        if len(sub_questions) > 1:
            logging.info("🎭 ORCHESTRATION AGENT: Validating multi-query plan...")
            
            try:
                is_multi_necessary = validate_query_plan(user_question, sub_questions, category)
                if not is_multi_necessary:
                    logging.info("🎭 ORCHESTRATION AGENT: Validation indicates single query is sufficient")
                    result = run_graph_agent(user_question, category, feedback_text)
                    
                    result_str = str(result)
                    conversation_history.append({"role": "assistant", "content": result_str})
                    total_tokens += count_tokens(result_str)
                    
                    # Generate token usage report
                    final_token_count = print_token_usage_report()
                    
                    logging.info(f"✅ ORCHESTRATION AGENT: Single query completed (Total tokens: {final_token_count})")
                    return result, False
            except Exception as e:
                logging.info(f"⚠️ ORCHESTRATION AGENT: Error in validation, defaulting to multi-query approach - {str(e)}")
                # Continue with multi-query approach on validation failure

        logging.info("🎭 ORCHESTRATION AGENT: Executing multi-query approach...")
        results = execute_multi_query(sub_questions, category)
        synthesis = synthesize_results(user_question, results, feedback_text)

        final_response = {
            "original_question": user_question,
            "sub_questions": sub_questions,
            "results": results,
            "synthesis": synthesis
        }
        
        # 4. Add final assistant response to memory
        final_response_str = str(final_response)
        conversation_history.append({"role": "assistant", "content": final_response_str})
        total_tokens += count_tokens(final_response_str)
        
        # Generate token usage report
        final_token_count = print_token_usage_report()
        
        logging.info(f"✅ ORCHESTRATION AGENT: Multi-query orchestration completed (Total tokens: {final_token_count})")
        return final_response, True
    except Exception as e:
        error_msg = str(e)
        logging.info(f"❌ ORCHESTRATION AGENT: Error in orchestration - {error_msg}")
        
        # Attempt fallback to simple query approach
        logging.info("🎭 ORCHESTRATION AGENT: Attempting fallback to simple query approach")
        try:
            result = run_graph_agent(user_question, category, feedback_text)
            
            # Add the fallback response to memory
            result_str = str(result)
            conversation_history.append({"role": "assistant", "content": result_str})
            
            # Generate token usage report
            final_token_count = print_token_usage_report()
            
            logging.info(f"✅ ORCHESTRATION AGENT: Fallback query completed (Total tokens: {final_token_count})")
            return result, False
        except Exception as fallback_error:
            logging.info(f"❌ ORCHESTRATION AGENT: Fallback also failed - {str(fallback_error)}")
            error_response = {
                "error": f"Unable to process query: {error_msg}. Fallback also failed: {str(fallback_error)}",
                "original_question": user_question
            }
            
            # Generate token usage report anyway
            final_token_count = print_token_usage_report()
            
            return error_response, False