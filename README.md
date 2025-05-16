# HN Jobs to Metabase

Fetches job postings from the latest "Who is hiring?" thread on Hacker News, parses them with OpenAI for structured data, and stores them in Postgres for visualization in Metabase.

## Quickstart (One Command)

1. **Clone the repo:**
   ```bash
   git clone <your-repo-url>
   cd hn-jobs-to-metabase
   ```
2. **Create `.env` in the project root:**
   ```
   POSTGRES_URL=postgresql://hnuser:hnpass@localhost:5432/hnjobs
   OPENAI_API_KEY=your_openai_api_key
   ```
3. **Set the thread ID in `fetch_hn_jobs.py`:**
   ```python
   MANUAL_THREAD_ID = 43858554  # or any "Who is hiring?" thread ID
   ```
4. **Run everything:**
   ```bash
   chmod +x run_local.sh
   ./run_local.sh
   ```
5. **Open Metabase:**

   - Go to [http://localhost:3000](http://localhost:3000)
   - Connect to the Postgres database (Display name: `HN`, Host: `db`, Port: `5432`, Database name: `hnjobs` Username: `hnuser`, Password: `hnpass`, Schemas: `hn`)
   - Explore the `jobs` table and build dashboards!

6. **To stop the services:**
   ```bash
   docker compose down
   ```

### How to Find a "Who is hiring?" Thread ID

1. Go to [Hacker News](https://news.ycombinator.com).
2. Scroll to the very bottom and use the search box.
3. Search for:  
   `Ask HN: Who is hiring? (Month Year)`  
   For example: `Ask HN: Who is hiring? (May 2025)`
4. Click on the thread you want.
5. The thread ID is the number at the end of the URL.  
   For example, in:  
   `https://news.ycombinator.com/item?id=43858554`  
   the thread ID is **43858554**.

Paste this ID into your `fetch_hn_jobs.py`:

```python
MANUAL_THREAD_ID = 43858554
```

---

- Only needs to run once per month (low cost)
- MIT License

## Table Schema

The script creates and uses the following table in Postgres (in the `hn` schema):

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

_All columns are used by the script except `created_at` and `updated_at`, which are managed automatically._
