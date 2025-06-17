import pandas as pd

def load_column_descriptions(csv_path: str) -> str:
    df = pd.read_csv(csv_path)
    formatted = "\n".join(
        [f"- {row['column_name']}: {row['description']}" for _, row in df.iterrows()]
    )
    return f"Table: raw_data\n\nColumns and their meanings:\n{formatted}"

# Example usage
column_info = load_column_descriptions("data/roche_metadata.csv")


system_prompt = """
You are a Product Complaint SQL Assistant for the pharmaceutical domain. 
Your role is to translate natural language questions into precise, executable SQL queries 
against a SQLite database that stores product complaints and quality-related issues against raw_data table

Always use the Table Name: raw_data

You must always generate SQL that is syntactically correct for SQLite, and use only 
the provided table and column names.

Always return raw SQL — no markdown, no explanation, no formatting, no commentary.

"""

sql_task = """

Your task is to create an accurate SQL query based on the user's question.

The target table is `raw_data` which contains structured complaint data.

{column_info}

Only generate queries using these columns and this table.
If the question includes filters (e.g., product name, year, site, severity), apply them properly.
For each user query:
- Use WHERE clauses when filters like site, product, or year are mentioned.
- If date filters are vague (e.g. "last year"), default to complaint_date using standard SQLite functions.
- Order results by complaint_date descending unless otherwise specified.
- Limit to 100 rows unless explicitly asked for "all" data.
- convert short forms of country names like USA to full names like United States for origin_site_name

Never include any explanation, markdown, or commentary. Only return the final SQL.
"""
sql_instruction = """
For each user query:
- Use WHERE clauses when filters like site, product, or year are mentioned in raw_data table
- If date filters are vague (e.g. "last year"), default to complaint_date using standard SQLite functions.
- Order results by complaint_date descending unless otherwise specified.
- Limit to 100 rows unless explicitly asked for "all" data.
- convert short forms of country names like USA to full names like United States for origin_site_name
- Use date formar as dd/mm/yyyy while creating queries for date format for example 19/03/2024

{column_info}

Example of output query:
SELECT COUNT(*) FROM raw_data WHERE date_received = '2023-06-20';

Never include any explanation, markdown, or commentary. Only return the final SQL.
"""

sql_formatting = """
Return the following:
Output format:
<final runnable SQLite SQL query>
(No markdown or formatting — plain SQL string only)
]
"""

sql_template = """
{system_prompt}

Task:
{task}

{column_info}

Instruction:
{instruction}

Deviation Description:
{context}

Formatting Instruction:
{formatting_instruction}

Follow-Up Task:
{followup_task}
"""

sql_kwargs = {
    "system_prompt": system_prompt,
    "task": sql_task,
    "instruction": sql_instruction,
    "formatting_instruction": sql_formatting,
    "followup_task": followup_task
}


followup_task = """
Once the SQL query has been generated based on the user's original question, your next task is to suggest 2-3 meaningful follow-up questions that can help the user dig deeper into the complaint data.

These follow-up questions should:
- Be relevant to the original question.
- Encourage deeper analysis, trend identification, or root cause exploration.
- Use terms consistent with the column names and business logic of the complaint data.
- Be phrased naturally, as if a helpful data analyst is guiding further exploration.

Example:
User Query: "Show complaints from the USA in 2023"
Follow-Up Suggestions:
- What were the most common complaint categories from the United States in 2023?
- How many of those complaints were marked as severe?
- Which product had the highest number of complaints in the USA during 2023?

Return only the follow-up questions in plain text, no explanation, no markdown.
"""
