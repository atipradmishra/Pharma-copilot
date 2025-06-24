import json
from chatagent.chat_agent import format_metadata_prompt
from gpt_client import create_invoke_chain
from graphqueryagent.graphyquery_prompt import graph_template, graph_kwargs
from config import client

with open('temp_uploads/metadata.json') as f:
    metadata = json.load(f)

def get_color_palette(n):
    base_colors = [
        "rgba(255, 99, 132, 0.7)", "rgba(54, 162, 235, 0.7)", "rgba(255, 206, 86, 0.7)",
        "rgba(75, 192, 192, 0.7)", "rgba(153, 102, 255, 0.7)", "rgba(255, 159, 64, 0.7)"
    ]
    return (base_colors * ((n // len(base_colors)) + 1))[:n]

def generate_sql_for_graph(question):
    metadata_prompt = format_metadata_prompt(metadata)

    system_prompt = f"""
        You are a Pharma SQL Agent responsible for generating SQL queries to support visual dashboards and data visualizations 
        based on user questions. The data is stored in a SQLite database related to pharmaceutical lab operations.

        ### Your Tasks:
        - Convert the question into a valid SQLite SQL query that retrieves data for visualization.
        - Use aggregates like COUNT, AVG, SUM, MAX, MIN where appropriate for KPIs or trends.
        - Use GROUP BY clauses if the question suggests comparison across categories or time.
        - Use DATE functions for any time-based filtering or grouping.
        - Use appropriate ORDER BY to sort data for charts (like trends over time).
        - Join tables if necessary using foreign keys (e.g., `item_id`, `sample_id`, `report_id`).
        - Use LOWER(column) for text filtering.
        - Return only the raw SQL query — no explanations, no markdown, no formatting.

        ### Schema:
        {metadata_prompt}

        ### User Question:
        {question}

        ### SQL Query:
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt}
        ],
        temperature=0,
        max_tokens=500
    )

    return response.choices[0].message.content.strip()


def generate_graph_insight(result_rows, user_query: str):
    try:
        data_summary = "\n".join([str(row) for row in result_rows[:10]])
        
        context = f"""
        User Query: {user_query}
        SQL Result Sample (first 10 rows):
        {data_summary}
        """

        input_vars = {
            "system_prompt": graph_kwargs["system_prompt"],
            "task": graph_kwargs["task"],
            "instruction": graph_kwargs["instruction"],
            "context": context
        }

        return create_invoke_chain(graph_template, input_vars)

    except Exception as e:
        return f"⚠️ Error while generating graph insight: {str(e)}"


def generate_followup_query(parent_query, clicked_label):
    prompt = f"""
    You are an AI assistant helping users explore Pharma data visually.

    The user previously asked: "{parent_query}".
    They clicked on the chart label: "{clicked_label}".

    Generate a refined query for a more detailed breakdown or drilldown based on the clicked label.
    Make the query appropriate for visual exploration and use natural language.
    """
    response =  client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a data visualization assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )

    followup = response.choices[0].message.content.strip()
    return followup
