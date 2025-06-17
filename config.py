from openai import OpenAI
import os

DB_NAME = "pharma_poc.db"

client = OpenAI(api_key= os.getenv("OPENAI_API_KEY"))

log_file_path = "sqlquery_log.txt"