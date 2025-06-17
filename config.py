from openai import OpenAI
import os

DB_NAME = "pharma_poc.db"
VALID_BUCKET = "etrm-etai-poc-chub"
REJECTED_BUCKET = "etai-rejected-files"

aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")

client = OpenAI(api_key= os.getenv("OPENAI_API_KEY"))

log_file_path = "sqlquery_log.txt"