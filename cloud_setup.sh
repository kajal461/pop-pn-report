#!/bin/bash
# cloud_setup.sh — Set up automated daily PN report on Google Cloud
# Run once: bash cloud_setup.sh
#
# Prerequisites:
#   - GCP project: copies-qc
#   - gcloud CLI installed and authenticated
#   - .env file with all required credentials
#
# What this does:
#   1. Enables required GCP APIs
#   2. Builds and pushes Docker image to Container Registry
#   3. Creates Cloud Run job
#   4. Creates Cloud Scheduler to run daily at 6am IST

set -e

PROJECT_ID="copies-qc"
REGION="asia-south1"         # Mumbai — closest to India
SERVICE_NAME="pn-report-daily"
SCHEDULE="0 0 * * *"         # Daily at midnight UTC = 5:30am IST
SCHEDULER_NAME="pn-report-scheduler"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "=== POP PN Report — Cloud Automation Setup ==="
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo ""

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✅ Loaded .env"
else
    echo "❌ .env file not found. Copy .env.example to .env and fill in values."
    exit 1
fi

# Check required env vars
required_vars="GCP_PROJECT_ID GOOGLE_CLOUD_KEY_PATH BQ_DATASET MOENGAGE_APP_ID MOENGAGE_SECRET_KEY"
for var in $required_vars; do
    if [ -z "${!var}" ]; then
        echo "❌ Missing required env var: $var"
        exit 1
    fi
done
echo "✅ All required environment variables present"

# Enable required APIs
echo ""
echo "Enabling GCP APIs..."
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    --project="${PROJECT_ID}"
echo "✅ APIs enabled"

# Build and push Docker image
echo ""
echo "Building Docker image..."
gcloud builds submit --tag "${IMAGE}" --project="${PROJECT_ID}"
echo "✅ Image built and pushed: ${IMAGE}"

# Create Cloud Run Job (runs to completion, not a server)
echo ""
echo "Creating Cloud Run Job..."
gcloud run jobs create "${SERVICE_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --task-timeout=600 \
    --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID}" \
    --set-env-vars="BQ_DATASET=${BQ_DATASET}" \
    --set-env-vars="MOENGAGE_APP_ID=${MOENGAGE_APP_ID}" \
    --set-env-vars="MOENGAGE_SECRET_KEY=${MOENGAGE_SECRET_KEY}" \
    --set-env-vars="MOENGAGE_DATA_CENTER=${MOENGAGE_DATA_CENTER:-api-01}" \
    --set-env-vars="GOOGLE_CLOUD_KEY_PATH=/app/credentials/service_account.json" \
    2>/dev/null || \
gcloud run jobs update "${SERVICE_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}"
echo "✅ Cloud Run Job: ${SERVICE_NAME}"

# Create Cloud Scheduler job
echo ""
echo "Creating Cloud Scheduler (daily at 5:30am IST)..."
gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
    --schedule="${SCHEDULE}" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${SERVICE_NAME}:run" \
    --message-body='{}' \
    --oauth-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --time-zone="Asia/Kolkata" \
    2>/dev/null || echo "  (Scheduler already exists — skipping)"
echo "✅ Cloud Scheduler: runs daily at 6:00am IST"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Your PN report will now run automatically every day at 6am IST."
echo "It will:"
echo "  1. Pull last 7 days of campaign data from MoEngage API"
echo "  2. Merge with all historical data in BigQuery (no data loss)"
echo "  3. Rebuild all summary tables"
echo "  4. Dashboard auto-updates — no action needed"
echo ""
echo "To trigger a manual run now:"
echo "  gcloud run jobs execute ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID}"
echo ""
echo "To view run logs:"
echo "  gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME}\" --limit=50"
