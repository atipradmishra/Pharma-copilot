# import json
# import logging
# from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import ChatPromptTemplate
# from gpt_client import llm
# from decimal import Decimal
# from chatagent.utils import extract_country_from_question, generate_bar_chart
# from sql_query_executor import run_sql


# def clean_result_data(result):
#     def normalize(value):
#         if isinstance(value, str):
#             value = value.replace(',', '').replace('−', '-')  # normalize Unicode minus and remove commas
#             try:
#                 return float(value)
#             except ValueError:
#                 return value
#         elif isinstance(value, Decimal):
#             return float(value)
#         return value

#     cleaned_rows = []
#     for row in result.get("rows", []):
#         cleaned_row = {k: normalize(v) for k, v in row.items()}
#         cleaned_rows.append(cleaned_row)

#     return {
#         "columns": result.get("columns", []),
#         "rows": cleaned_rows
#     }

# def qualify_table_names(sql: str, conn_details: dict) -> str:
#     """
#     Ensures fully-qualified table names in the SQL string for Snowflake.
#     """
#     if conn_details.get("source", "").lower() == "snowflake":
#         db = conn_details.get("sf_database")
#         schema = conn_details.get("schema")
#         if db and schema:
#             import re
#             pattern = re.compile(r'\bFROM\s+(?!\b' + db + '\.' + schema + '\.)([a-zA-Z_][\w]*)', re.IGNORECASE)
#             sql = pattern.sub(rf"FROM {db}.{schema}.\\1", sql)

#             pattern_join = re.compile(r'\bJOIN\s+(?!\b' + db + '\.' + schema + '\.)([a-zA-Z_][\w]*)', re.IGNORECASE)
#             sql = pattern_join.sub(rf"JOIN {db}.{schema}.\\1", sql)

#     return sql

# def generate_rag_response(result_or_payload: dict, user_question: str = None) -> str:
#     print("🧠 Inside generate_rag_response")

#     try:
#         # ✅ DASHBOARD MODE: AI Summary from Chart JSON
#         if "charts" in result_or_payload and "prompt" in result_or_payload:
#             charts = result_or_payload.get("charts", [])
#             prompt = result_or_payload.get("prompt", "")

#             print("📊 Summary Prompt:", prompt)
#             print("📦 Chart JSON Preview:", json.dumps(charts, indent=2)[:500])

#             summary_prompt = ChatPromptTemplate.from_messages([
#                 ("system", "You are a pharma product complaint analyst. Analyze the following dashboard charts and generate a clear, leadership-ready summary that includes trends, patterns, outliers, and business insights."),
#                 ("user", "{prompt}\n\nHere is the structured chart data:\n{json_data}\n\nSummarize this dashboard.")
#             ])

#             chain = summary_prompt | llm | StrOutputParser()
#             response = chain.invoke({
#                 "prompt": prompt,
#                 "json_data": json.dumps(charts, indent=2)
#             })
#             return response

#         # ✅ CHAT MODE: Raw SQL result
#         elif user_question:
#             # ⛔ Guard against missing or malformed result
#             if not result_or_payload or "columns" not in result_or_payload or "rows" not in result_or_payload:
#                 print("⚠️ Incomplete or missing SQL result structure")
#                 return "⚠️ No data available to answer this question."

#             result = clean_result_data(result_or_payload)

#             summary_prompt = ChatPromptTemplate.from_messages([
#                 ("system", "You are a pharma product complaint analyst who explains structured JSON data in a friendly and natural tone. Your job is to analyze user queries and provide your response in a concrete and concise manner. Answer the user's question precisely using only the data provided."),
#                 ("user", "User asked: {question}\n\nHere is the structured data returned:\n{json_data}\n\nWrite a natural language summary of this.")
#             ])

#             chain = summary_prompt | llm | StrOutputParser()
#             response = chain.invoke({
#                 "question": user_question,
#                 "json_data": json.dumps(result, indent=2)
#             })
#             return response

#         else:
#             return "⚠️ No valid data provided for response generation."

#     except Exception as e:
#         logging.error(f"Error generating summary: {e}")
#         print("❌ GPT Summary Generation Exception:", e)
#         return "⚠️ Error generating summary."

# def generate_why_response(user_question: str) -> dict:
#     focus_country = extract_country_from_question(user_question)

#     base_sql = """
#     SELECT origin_site_name, COUNT(*) as total_complaints
#     FROM raw_data
#     GROUP BY origin_site_name
#     """
#     base_data = run_sql(base_sql)

#     drill_sql = f"""
#     SELECT lifecycle_state, quality_event_type, title, COUNT(*) as count
#     FROM raw_data
#     WHERE origin_site_name = '{focus_country}'
#     GROUP BY lifecycle_state, quality_event_type, title
#     ORDER BY count DESC
#     """
#     drill_data = run_sql(drill_sql)

#     response_text = generate_rag_response({
#         "base_data": base_data,
#         "focus_country": focus_country,
#         "drill_data": drill_data,
#     }, user_question)

#     chart_html = generate_bar_chart(base_data, x="origin_site_name", y="total_complaints")

#     return {
#         "text": response_text,
#         "chart_html": chart_html
#     }