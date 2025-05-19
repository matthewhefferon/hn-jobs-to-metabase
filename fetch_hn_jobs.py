"""
HN Jobs to Metabase - Main Script

Set MANUAL_THREAD_ID below to the thread you want to parse.
"""

MANUAL_THREAD_ID = 43858554  # Set your thread ID here

import requests
import os
import sys
import re
import html
from datetime import datetime
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import openai
import json
import psycopg2
import csv

# Logging: only errors
import logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

load_dotenv()
POSTGRES_URL = os.getenv("POSTGRES_URL")
if not POSTGRES_URL:
    logger.error("Missing required environment variable POSTGRES_URL")
    sys.exit(1)
try:
    pgconn = psycopg2.connect(POSTGRES_URL)
    pgconn.autocommit = True
except Exception as e:
    logger.error(f"Failed to connect to Postgres: {str(e)}")
    sys.exit(1)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
RATE_LIMIT_DELAY = 0.5
MAX_REQUESTS_PER_MINUTE = 30

session = requests.Session()
retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[500, 502, 503, 504], allowed_methods=["GET", "POST"])
session.mount('https://', HTTPAdapter(max_retries=retries))
session.mount('http://', HTTPAdapter(max_retries=retries))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

OPENAI_PROMPT = (
    "You are a structured data parser for Hacker News job posts. "
    "Extract the following fields as plain strings (no quotes, arrays, or brackets unless necessary):\n"
    "- company: the name of the hiring company\n"
    "- role: the job title or position name\n"
    "- location: city/state/country or 'Remote' if applicable\n"
    "- salary: salary range or note (e.g. '$120k–$150k', 'Competitive', etc.)\n"
    "- contact: email address or direct application link (cleaned, no obfuscation like [at] or [dot])\n"
    "- description: a cleaned-up version of the full job post, useful for search\n\n"
    "Requirements:\n"
    "- Output a flat JSON object using the keys above\n"
    "- If any field is missing or not available, use null (not 'n/a', 'none', or empty string)\n"
    "- Do not include any markdown, HTML, or formatting characters\n"
    "- Fix obfuscated emails (e.g. convert 'john [at] domain [dot] com' to 'john@domain.com')\n"
    "- Do not include any commentary or explanation, only output the JSON object.\n"
    "- No trailing commas in the JSON.\n\n"
    "Job post:\n"
    '"""{job_text}"""'
)

def extract_job_fields_with_openai(job_text):
    prompt = OPENAI_PROMPT.format(job_text=job_text)
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0
    )
    content = response.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            data = {}
    return data

def insert_job_to_postgres(job_id, parsed, posted_at):
    if not any([
        parsed.get('company'), parsed.get('role'),
        parsed.get('location'), parsed.get('salary'),
        parsed.get('contact'), parsed.get('description')
    ]):
        return
    data = (
        job_id,
        parsed.get('company'),
        parsed.get('role'),
        parsed.get('location'),
        parsed.get('salary'),
        parsed.get('contact'),
        parsed.get('description'),
        posted_at
    )
    with pgconn.cursor() as cur:
        cur.execute('''
            INSERT INTO hn.jobs (hn_comment_id, company, role, location, salary, contact, description, posted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (hn_comment_id) DO UPDATE SET
                company=EXCLUDED.company,
                role=EXCLUDED.role,
                location=EXCLUDED.location,
                salary=EXCLUDED.salary,
                contact=EXCLUDED.contact,
                description=EXCLUDED.description,
                posted_at=EXCLUDED.posted_at,
                updated_at=now();
        ''', data)

def export_jobs_to_csv(pgconn, filename="hn_jobs.csv"):
    with pgconn.cursor() as cur:
        cur.execute("SELECT * FROM hn.jobs ORDER BY posted_at DESC")
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(colnames)
            writer.writerows(rows)

def print_first_job_comments(thread_id, n=None, insert=False):
    url = f"{HN_API_BASE}/item/{thread_id}.json"
    try:
        resp = session.get(url)
        resp.raise_for_status()
        thread = resp.json()
    except Exception as e:
        logger.error(f"Error fetching thread {thread_id}: {str(e)}")
        sys.exit(1)
    kids = thread.get('kids', [])
    total = n if n is not None else len(kids)
    print(f"Thread has {len(kids)} top-level comments (job posts)")
    count = 0
    bar_len = 40
    def progress_bar(count, total, bar_len=40):
        filled = int(bar_len * count / total)
        bar = '=' * filled + '-' * (bar_len - filled)
        pct = (count / total) * 100
        print(f"[{bar}] {count}/{total} ({pct:.1f}%)", end='\r')
    for kid_id in kids:
        if n is not None and count >= n:
            break
        try:
            comment_resp = session.get(f"{HN_API_BASE}/item/{kid_id}.json")
            comment_resp.raise_for_status()
            comment = comment_resp.json()
            text = comment.get('text', '')
            posted_at = datetime.utcfromtimestamp(comment.get('time', 0)).isoformat() if comment.get('time') else None
            if OPENAI_API_KEY:
                parsed = extract_job_fields_with_openai(text)
            else:
                parsed = {
                    'company': None,
                    'role': None,
                    'location': None,
                    'salary': None,
                    'contact': None,
                    'description': text.strip() or None,
                }
            if any([
                parsed.get('company'), parsed.get('role'),
                parsed.get('location'), parsed.get('salary'),
                parsed.get('contact'), parsed.get('description')
            ]):
                count += 1
                progress_bar(count, total, bar_len)
                if insert:
                    insert_job_to_postgres(kid_id, parsed, posted_at)
        except Exception as e:
            logger.warning(f"Error fetching comment {kid_id}: {str(e)}")
    print()  # Newline after progress bar
    print(f"Inserted {count} jobs from thread {thread_id}.")

if __name__ == "__main__":
    thread_id = MANUAL_THREAD_ID
    if thread_id:
        print_first_job_comments(thread_id, insert=True)
        export_jobs_to_csv(pgconn)
