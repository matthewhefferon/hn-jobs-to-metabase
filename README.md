# HN Jobs to Metabase

Fetches job postings from "Who is hiring?" threads on Hacker News, parses them with OpenAI, and stores them in Postgres for Metabase dashboards. Also exports to CSV.

## Output

- A `hn_jobs.csv` file with all parsed jobs
- Data in Postgres for Metabase visualization

## Prerequisites

- Docker and Docker Compose installed and running
- Python 3.9+
- OpenAI API key

## Quickstart

1. **Clone:**
   ```bash
   git clone <your-repo-url>
   cd hn-jobs-to-metabase
   ```
2. **Create `.env`:**
   ```
   POSTGRES_URL=postgresql://hnuser:hnpass@localhost:5432/hnjobs
   OPENAI_API_KEY=your_openai_api_key
   ```
3. **Set thread ID:**
   Edit `MANUAL_THREAD_ID` at the top of `fetch_hn_jobs.py`:
   ```python
   MANUAL_THREAD_ID = 43858554  # Set your thread ID
   ```
4. **Run:**
   ```bash
   chmod +x run_local.sh
   ./run_local.sh
   ```
5. **Metabase:**

   - Go to [http://localhost:3000](http://localhost:3000)
   - Connect to Postgres with these settings:
     - Host: `db`
     - Database: `hnjobs`
     - Username: `hnuser`
     - Password: `hnpass`
     - Schema: `hn`
   - Explore the `jobs` table

6. **Stop and Cleanup:**
   ```bash
   docker compose down
   ```
   This will stop all containers and remove them, cleaning up your environment.

---

## How to Find a Thread ID

- Search Hacker News for: `Ask HN: Who is hiring? (Month Year)`
- The thread ID is at the end of the URL (e.g. `item?id=43858554`).
- Paste it into `MANUAL_THREAD_ID` in `fetch_hn_jobs.py`.

---

## Table Schema

```sql
CREATE SCHEMA IF NOT EXISTS hn;

CREATE TABLE hn.jobs (
  hn_comment_id bigint primary key,
  company text,
  role text,
  location text,
  salary text,
  contact text,
  description text,
  posted_at timestamp with time zone,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);
```

---

MIT License
