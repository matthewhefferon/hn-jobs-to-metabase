"""
HN Jobs to Metabase - Main Script

Set MANUAL_THREAD_ID below to the thread you want to parse.
"""

MANUAL_THREAD_ID = 43858554  # <-- Set your thread ID here!

import requests
import os
import time
import logging
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

# Setup logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
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

# HN API base URL
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

# Rate limiting settings
RATE_LIMIT_DELAY = 0.5  # 500ms between requests
MAX_REQUESTS_PER_MINUTE = 30
MAX_HISTORICAL_ITEMS = 1000  # Limit historical scan to last 1000 items

# Setup requests session with retries
session = requests.Session()
retries = Retry(
    total=3,  # Reduced from 5 to 3
    backoff_factor=1.0,  # Increased from 0.5 to 1.0
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
session.mount('https://', HTTPAdapter(max_retries=retries))
session.mount('http://', HTTPAdapter(max_retries=retries))

# OpenAI setup
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

OPENAI_PROMPT = (
    "Extract the following fields from this Hacker News job post as plain strings (no quotes, brackets, or arrays unless truly necessary):\n"
    "- company\n"
    "- role\n"
    "- location\n"
    "- salary\n"
    "- contact\n"
    "- description\n"
    "Return your answer as a JSON object with these keys. If a field is missing, use null. Do not wrap any field in quotes, brackets, or arrays unless it is truly required.\n"
    "Job post:\n"
    '"""{job_text}"""'
)

def get_max_item_id():
    """Get the latest item ID from HN"""
    try:
        response = session.get(f"{HN_API_BASE}/maxitem.json")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching max item ID: {str(e)}")
        sys.exit(1)

def get_job_stories(start_id=None, batch_size=100):
    """Get job stories, optionally starting from a specific ID"""
    if start_id is None:
        # Get latest job stories
        url = f"{HN_API_BASE}/jobstories.json"
        try:
            response = session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching job stories: {str(e)}")
            sys.exit(1)
    
    # Get historical job stories
    job_ids = []
    end_id = max(0, start_id - min(batch_size, MAX_HISTORICAL_ITEMS))
    request_count = 0
    start_time = time.time()
    total_items = start_id - end_id
    
    logger.info(f"Scanning {total_items} items for job posts...")
    
    for i, item_id in enumerate(range(start_id, end_id, -1), 1):
        # Progress indicator
        if i % 10 == 0:
            progress = (i / total_items) * 100
            logger.info(f"Progress: {progress:.1f}% ({i}/{total_items})")
            
        # Rate limiting
        if request_count >= MAX_REQUESTS_PER_MINUTE:
            elapsed = time.time() - start_time
            if elapsed < 60:
                sleep_time = 60 - elapsed
                logger.info(f"Rate limit reached, sleeping for {sleep_time:.1f} seconds")
                time.sleep(sleep_time)
            request_count = 0
            start_time = time.time()
        
        try:
            response = session.get(f"{HN_API_BASE}/item/{item_id}.json")
            response.raise_for_status()
            item = response.json()
            if item and item.get("type") == "job":
                job_ids.append(item_id)
                logger.info(f"Found job post: {item_id}")
            request_count += 1
            time.sleep(RATE_LIMIT_DELAY)  # Rate limiting
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching item {item_id}: {str(e)}")
            # Don't exit here, just log and continue with next item
        except Exception as e:
            logger.error(f"Unexpected error fetching item {item_id}: {str(e)}")
            # Don't exit here, just log and continue with next item
    
    return job_ids

def find_latest_who_is_hiring():
    """Find the most recent 'Ask HN: Who is hiring?' thread for the current month and return its ID."""
    url = f"{HN_API_BASE}/askstories.json"
    try:
        response = session.get(url)
        response.raise_for_status()
        ask_ids = response.json()
    except Exception as e:
        logger.error(f"Error fetching askstories: {str(e)}")
        sys.exit(1)

    now = datetime.utcnow()
    month_year = now.strftime('%B %Y')  # e.g., 'May 2025'
    pattern = re.compile(rf"ask hn:\s*who is hiring\??\s*\({month_year}\)", re.IGNORECASE)
    for ask_id in ask_ids:
        try:
            item_resp = session.get(f"{HN_API_BASE}/item/{ask_id}.json")
            item_resp.raise_for_status()
            item = item_resp.json()
            if item and 'title' in item and pattern.search(item['title']):
                logger.info(f"Found latest 'Who is hiring?' thread: {item['title']} (ID: {item['id']})")
                print(f"Thread ID: {item['id']}")
                print(f"Title: {item['title']}")
                print(f"URL: https://news.ycombinator.com/item?id={item['id']}")
                return item['id']
        except Exception as e:
            logger.warning(f"Error fetching Ask HN item {ask_id}: {str(e)}")
    # If not found, walk backward from maxitem
    logger.info("Not found in askstories.json, searching by maxitem...")
    try:
        maxitem_resp = session.get(f"{HN_API_BASE}/maxitem.json")
        maxitem_resp.raise_for_status()
        max_id = maxitem_resp.json()
    except Exception as e:
        logger.error(f"Error fetching maxitem: {str(e)}")
        return None
    found = None
    for item_id in range(max_id, max_id-20000, -1):
        if item_id % 100 == 0:
            logger.info(f'Checking item {item_id}')
        time.sleep(0.1)
        try:
            item_resp = session.get(f"{HN_API_BASE}/item/{item_id}.json")
            item_resp.raise_for_status()
            item = item_resp.json()
            if item and item.get('type') == 'story' and 'title' in item and pattern.search(item['title']):
                logger.info(f"Found latest 'Who is hiring?' thread by maxitem: {item['title']} (ID: {item['id']})")
                print(f"Thread ID: {item['id']}")
                print(f"Title: {item['title']}")
                print(f"URL: https://news.ycombinator.com/item?id={item['id']}")
                found = item['id']
                break
        except Exception as e:
            continue
    if not found:
        logger.error("No 'Who is hiring?' thread found in recent HN posts for this month.")
    return found

def parse_job_post(text):
    # Remove HTML tags and decode entities
    clean = re.sub(r'<[^>]+>', '\n', text)
    clean = html.unescape(clean)
    clean = re.sub(r'\n+', '\n', clean).strip()
    # Try to extract fields from the first line (Company | Role | Location ...)
    first_line = clean.split('\n', 1)[0]
    parts = [html.unescape(p.strip()) for p in first_line.split('|')]
    company, role, location, contact, salary = None, None, None, None, None
    if len(parts) >= 1:
        company = parts[0]
    # Smarter role/salary parsing
    if len(parts) >= 2:
        second = parts[1]
        if re.search(r'(\$|k|equity)', second, re.IGNORECASE):
            salary = second
        else:
            role = second
    if len(parts) >= 3:
        if salary is None and re.search(r'(\$|k|equity)', parts[2], re.IGNORECASE):
            salary = parts[2]
        elif role is None:
            role = parts[2]
        else:
            location = parts[2]
    if len(parts) >= 4:
        location = parts[3]
    # Try to find contact info (email or URL) anywhere in the text
    email_match = re.search(r'[\w\.-]+@[\w\.-]+', clean)
    url_match = re.search(r'https?://\S+', clean)
    if email_match:
        contact = html.unescape(email_match.group(0))
    elif url_match:
        contact = html.unescape(url_match.group(0))
    # Improved salary extraction: only match real comp, not $1 in URLs
    salary_match = re.search(r'(\$\d{2,3}[,\d]*[kK]?\s*(?:[-–—]\s*\$?\d{2,3}[,\d]*[kK]?)?|€[\d,]+|£[\d,]+|USD\s*[\d,]+|Compensation[:\s]+[^\n]+)', clean)
    if salary_match:
        salary = html.unescape(salary_match.group(0).strip())
    # Description: everything after the first line
    description = html.unescape(clean.split('\n', 1)[1].strip()) if '\n' in clean else ''
    return {
        'company': company,
        'role': role,
        'location': location,
        'contact': contact,
        'salary': salary,
        'description': description,
    }

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
        parsed.get('company'), parsed.get('role'), parsed.get('role(s)'),
        parsed.get('location'), parsed.get('salary'), parsed.get('contact'), parsed.get('description')
    ]):
        return
    role = parsed.get('role') or parsed.get('role(s)')
    data = (
        job_id,
        parsed.get('company'),
        role,
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
    logger.info(f"Inserted job {job_id}: {parsed.get('company')} | {role}")

def print_first_job_comments(thread_id, n=None, insert=False):
    """Fetch, parse (with OpenAI if available), print and optionally insert all valid job posts from the thread."""
    url = f"{HN_API_BASE}/item/{thread_id}.json"
    try:
        resp = session.get(url)
        resp.raise_for_status()
        thread = resp.json()
    except Exception as e:
        logger.error(f"Error fetching thread {thread_id}: {str(e)}")
        sys.exit(1)
    kids = thread.get('kids', [])
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
                parsed = parse_job_post(text)
            # Only print/insert if at least one key field is present
            if any([parsed.get('company'), parsed.get('role'), parsed.get('role(s)'), parsed.get('location'), parsed.get('contact'), parsed.get('salary'), parsed.get('description')]):
                count += 1
                progress_bar(count, len(kids), bar_len)
                if insert:
                    insert_job_to_postgres(kid_id, parsed, posted_at)
        except Exception as e:
            logger.warning(f"Error fetching comment {kid_id}: {str(e)}")
    print()  # Newline after progress bar
    print(f"Inserted {count} jobs from thread {thread_id}.")

def run():
    logger.info("Starting job fetch")
    
    # First get latest jobs
    latest_jobs = get_job_stories()
    if not latest_jobs:
        logger.error("No latest jobs found")
        sys.exit(1)
    logger.info(f"Found {len(latest_jobs)} latest job stories")
    
    # Then get historical jobs
    max_id = get_max_item_id()
    if not max_id:
        logger.error("Could not get max item ID")
        sys.exit(1)
        
    logger.info(f"Fetching historical jobs from ID {max_id}")
    historical_jobs = get_job_stories(start_id=max_id)
    logger.info(f"Found {len(historical_jobs)} historical job stories")
    
    all_jobs = list(set(latest_jobs + historical_jobs))  # Remove duplicates
    if not all_jobs:
        logger.error("No jobs found to process")
        sys.exit(1)
        
    logger.info(f"Processing {len(all_jobs)} total jobs")
    
    request_count = 0
    start_time = time.time()
    
    for i, job_id in enumerate(all_jobs, 1):
        # Progress indicator
        progress = (i / len(all_jobs)) * 100
        logger.info(f"Processing job {i}/{len(all_jobs)} ({progress:.1f}%)")
        
        # Rate limiting
        if request_count >= MAX_REQUESTS_PER_MINUTE:
            elapsed = time.time() - start_time
            if elapsed < 60:
                sleep_time = 60 - elapsed
                logger.info(f"Rate limit reached, sleeping for {sleep_time:.1f} seconds")
                time.sleep(sleep_time)
            request_count = 0
            start_time = time.time()
            
        try:
            response = session.get(f"{HN_API_BASE}/item/{job_id}.json")
            response.raise_for_status()
            job = response.json()
            if job and job.get("type") == "job":
                insert_job_to_postgres(job_id, job, datetime.fromtimestamp(job.get("time", datetime.now().timestamp())).isoformat())
            request_count += 1
            time.sleep(RATE_LIMIT_DELAY)  # Rate limiting
        except requests.exceptions.RequestException as e:
            logger.error(f"Error processing job {job_id}: {str(e)}")
            # Don't exit here, just log and continue with next item
        except Exception as e:
            logger.error(f"Unexpected error processing job {job_id}: {str(e)}")
            # Don't exit here, just log and continue with next item
    
    logger.info("Job fetch completed successfully")

if __name__ == "__main__":
    thread_id = MANUAL_THREAD_ID if MANUAL_THREAD_ID else find_latest_who_is_hiring()
    if thread_id:
        print_first_job_comments(thread_id, n=25, insert=True)
