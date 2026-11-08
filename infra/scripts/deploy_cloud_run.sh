#!/usr/bin/env bash
# Deploy the keyless hosted demo to Google Cloud Run. Run from the repo root (the folder with README.md).
# Needs the gcloud CLI, a project with billing on, and you signed in:  gcloud auth login
# Usage: bash infra/scripts/deploy_cloud_run.sh YOUR_PROJECT_ID [region]
set -euo pipefail
PROJECT="${1:?Usage: deploy_cloud_run.sh PROJECT_ID [region]}"
REGION="${2:-us-central1}"
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
# No keys on the public demo: item and instruction reads come from the recordings in data/.
gcloud run deploy warrant \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2 \
  --timeout 60
echo
echo "Deployed. Open the URL above, add /health to check it."
