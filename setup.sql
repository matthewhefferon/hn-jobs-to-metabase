-- This script sets up the jobs table and its permissions.
-- It's idempotent - can be run multiple times safely

SET client_min_messages TO warning;

CREATE SCHEMA IF NOT EXISTS hn;

-- Drop existing policies if they exist
drop policy if exists "Allow public read access" on hn.jobs;
drop policy if exists "Allow authenticated users to insert" on hn.jobs;
drop policy if exists "Allow authenticated users to update" on hn.jobs;
drop policy if exists "Allow service role to insert" on hn.jobs;
drop policy if exists "Allow service role to update" on hn.jobs;

-- Drop existing trigger if it exists
drop trigger if exists update_jobs_updated_at on hn.jobs;

-- Drop and recreate jobs table for Who is hiring? jobs
DROP TABLE IF EXISTS hn.jobs CASCADE;

CREATE TABLE hn.jobs (
  hn_comment_id bigint primary key, -- HN comment ID (unique per job post)
  company text,                    -- Company name
  role text,                       -- Job title/role(s)
  location text,                   -- Location (remote/onsite/city)
  salary text,                     -- Salary/compensation info
  contact text,                    -- Contact email or URL
  description text,                -- Full job description (parsed)
  posted_at timestamp with time zone, -- When the comment was posted
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

-- Enable Row Level Security
ALTER TABLE hn.jobs ENABLE ROW LEVEL SECURITY;

-- Allow public read access (for Metabase)
CREATE POLICY "Allow public read access"
  ON hn.jobs FOR SELECT
  USING (true);

-- Function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION hn.update_updated_at_column()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call the function on every update
CREATE TRIGGER update_jobs_updated_at
  BEFORE UPDATE ON hn.jobs
  FOR EACH ROW
  EXECUTE FUNCTION hn.update_updated_at_column();

-- Add keywords column for filtering (idempotent)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema='hn' AND table_name='jobs' AND column_name='keywords'
    ) THEN
        ALTER TABLE hn.jobs ADD COLUMN keywords text[];
        COMMENT ON COLUMN hn.jobs.keywords IS 'Extracted keywords from title and description for filtering/search.';
    END IF;
END $$; 