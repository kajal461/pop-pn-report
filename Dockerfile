# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# The entrypoint runs the report pipeline in API mode
# Cloud Scheduler will POST to this container's HTTP endpoint
CMD ["python", "run_report.py", "--api", "--days", "7"]
