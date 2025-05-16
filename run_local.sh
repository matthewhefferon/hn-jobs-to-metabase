#!/bin/bash
set -e

# Start Docker Compose
echo 'Starting Docker Compose...'
docker-compose up -d

# Wait for Postgres to be ready
echo 'Waiting for Postgres to be ready...'
until docker exec hn_jobs_postgres pg_isready -U hnuser; do
  sleep 1
done

# Apply schema
echo 'Applying schema...'
docker exec -i hn_jobs_postgres psql -q -U hnuser -d hnjobs < setup.sql

# Install Python dependencies
echo 'Installing Python dependencies...'
python3 -m pip install --upgrade pip -q
python3 -m pip install -r requirements.txt -q

# Run the job fetch/parse/insert script
echo 'Running fetch_hn_jobs.py...'
python3 fetch_hn_jobs.py

echo 'Done! Visit http://localhost:3000 to explore in Metabase.' 