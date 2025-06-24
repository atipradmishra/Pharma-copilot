from config import client
import json

with open('temp_uploads/metadata.json') as f:
    metadata = json.load(f)

def format_metadata_prompt(metadata):
    lines = []
    for table, columns in metadata.items():
        lines.append(f"Table: {table}_raw_data")
        for col in columns:
            col_line = f"  - {col['column_name']} ({col['data_type']}): {col['description']}"
            lines.append(col_line)
    return "\n".join(lines)


def generate_sql_from_question(question):
    metadata_prompt = format_metadata_prompt(metadata)

    system_prompt = f"""
        You are a Pharma SQL Agent. Your task is to convert natural language questions into valid SQL queries 
        for a SQLite database containing pharmaceutical lab management data.

        ### Rules:
        - Use only the table and column names defined in the schema.
        - Use the correct column types and naming conventions.
        - Use JOINs if data spans across tables using common keys (like `item_id`, `sample_id`).
        - For filters involving time, interpret "next week" as: 
        `BETWEEN DATE('now') AND DATE('now', '+7 days')`
        - Always use `LOWER(column)` for text comparisons like 'Calibration', 'Yes', etc.
        - DO NOT include explanations or markdown.
        - DO NOT use quotes around the full SQL string.
        - Return only raw SQL.

        ### Schema:
        {metadata_prompt}

        ### Question:
        {question}

        ### SQL Query:
        """.strip()

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt}
        ],
        temperature=0,
        max_tokens=300
    )

    # print(response.choices[0].message.content)


    sql =  response.choices[0].message.content

    # Clean out code fences and quotes
    if sql.startswith("```sql"):
        sql = sql[6:]
    if sql.endswith("```"):
        sql = sql[:-3]

    # Remove surrounding quotes if any
    sql = sql.strip("\"' \n")

    return sql


def execute_sql_query(query):
    import sqlite3
    conn = sqlite3.connect("pharma_poc.db")
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        conn.close()



def generate_natural_language_response(question, result_rows):
    context = f"""
        You are an AI assistant specialized in pharmaceutical data analytics.

        You will be given:
        - A natural language question asked by the user.
        - The SQL query used to answer the question.
        - The result of that query in JSON format.

        Your job is to:
        1. Clearly explain the answer to the question based on the SQL result.
        2. Use pharma-specific context if relevant (e.g., calibration, expiry, samples).
        3. Do not mention SQL or database terms in the response.
        4. If no results are found, say so politely in a business-friendly tone.
        5. Keep it concise and informative.

        ### User Question:
        {question}

        ### SQL Result:
        {result_rows}

        Answer:
        """.strip()

    prompt = context + "\nPlease generate a clear and concise natural language summary of this result."

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.7,
        max_tokens=300
    )

    # print(response.choices[0].message.content)

    return response.choices[0].message.content.strip()

def suggest_follow_up_questions(user_query, rag_response):

    followup_task = """
    Once the Answer has been generated based on the user's original question, your next task is to suggest 2-3 meaningful follow-up questions that can help the user dig deeper into the pharmaaceutical data.

    These follow-up questions should:
    - Be relevant to the original question.
    - Encourage deeper analysis, trend identification, or root cause exploration.
    - Use terms consistent with the column names and business logic of the pharmaceutical data.
    - Be phrased naturally, as if a helpful data analyst is guiding further exploration.

    Example:
    User Query: "Show instruments scheduled for calibration next week"
    Follow-Up Suggestions:
    Which instruments have the longest calibration durations scheduled?
    Are there any instruments that are overdue for calibration?
    Who scheduled the most calibration tasks this month?

    Return only the follow-up questions in plain text, no explanation, no markdown.
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": followup_task},
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": rag_response}
        ],
        temperature=0.7,
        max_tokens=300
    )

    followups = response.choices[0].message.content.strip().split("\n")

    # print(response.choices[0].message.content)

    return followups

