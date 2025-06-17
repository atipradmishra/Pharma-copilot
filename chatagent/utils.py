# import re
# import pandas as pd
# import plotly.express as px
# from sql_query_executor import run_sql

# def extract_country_from_question(question: str) -> str:
#     result = run_sql("SELECT DISTINCT origin_site_name FROM raw_data WHERE origin_site_name IS NOT NULL")
#     countries = [row[0] for row in result["rows"]]

#     for country in countries:
#         if country and country.lower() in question.lower():
#             return country
#     return "Unknown"

# def generate_bar_chart(data: dict, x: str, y: str) -> str:
#     """
#     Converts a dict result (columns + rows) into a Plotly bar chart.
#     Returns an HTML string for rendering in the frontend.
#     """
#     df = pd.DataFrame([dict(zip(data["columns"], row)) for row in data["rows"]])
#     fig = px.bar(df, x=x, y=y, title=f"{y} by {x}")
#     return fig.to_html(full_html=False)