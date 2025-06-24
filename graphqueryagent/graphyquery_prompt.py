# dashboard_prompt.py
from langchain.prompts import ChatPromptTemplate

# System prompt for dashboard summarization
system_prompt = """
You are a Product Complaint Visualization Assistant for the pharmaceutical domain.
Your task is to generate natural language summaries and visualization suggestions based on structured complaint data.
The input will consist of user questions and complaint metrics including:
- Most frequent products and origin sites
- Complaint status trends (e.g., Open, Closed)
- Complaint criticality
- Time-based or product-based filtering

You will analyze the data and guide the generation of graphs such as bar charts, pie charts, line trends, etc.
Make your output simple, concise, and oriented toward business users.
Avoid technical jargon.
"""

# Task prompt for graph-based dashboard insights
graph_task = """
Generate a natural language summary or visualization recommendation based on the following user request and associated metrics:

{column_info}

Context:
{context}

Focus on summarizing key complaint trends, helping users visualize:
- Complaint frequency by product
- Status distribution
- Complaint trends over time or by site
- Criticality comparisons

Return insights or graph guidance.
"""

# Instructions for structured graph summary or suggestion
graph_instruction = """
Respond with a JSON object that includes:
- "summary": A short natural language insight.
- "suggested_chart": bar | pie | line | table
- "x_axis": A column name from the table (like product_name or origin_site_name).
- "y_axis": A column like complaint_count.
- "sql": A valid SQLite query that retrieves two columns: x_axis and y_axis values.

Example:
{
  "summary": "Most complaints originated from Site X in Q1 2024.",
  "suggested_chart": "bar",
  "x_axis": "origin_site_name",
  "y_axis": "complaint_count",
  "sql": "SELECT DATE(test_date) as week, COUNT(*) as calibration_count FROM test_records WHERE LOWER(test_type) = 'calibration' GROUP BY week ORDER BY week;"
}

Only return raw JSON — no markdown, no explanations.

"""

# Final template for the LLM call
# graph_template = """
# {system_prompt}

# Task:
# {task}

# Instruction:
# {instruction}

# Context:
# {context}
# """

graph_template = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    ("user", """Task:
{task}

Instruction:
{instruction}

Context:
{context}""")
])


# Final kwargs dictionary for invocation
graph_kwargs = {
    "system_prompt": system_prompt,
    "task": graph_task,
    "instruction": graph_instruction
}
