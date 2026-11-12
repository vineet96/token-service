#!/usr/bin/env bash
set -euo pipefail

# Configuration for your GCP Project
export AGENT_PROJECT_ID="ge-poc-511814"
export TOKEN_SERVICE_REGION="${TOKEN_SERVICE_REGION:-us-central1}"
export AGENTIC_AGENT_ID="${AGENTIC_AGENT_ID:-YOUR_AGENT_ID}"
export MOCK_INITIALIZE_SESSION="${MOCK_INITIALIZE_SESSION:-false}"

API_CALLER_SA="api-caller@${AGENT_PROJECT_ID}.iam.gserviceaccount.com"
TOKEN_SERVICE_SA="token-service-sa@${AGENT_PROJECT_ID}.iam.gserviceaccount.com"

echo "==> 1. Enabling required Google Cloud APIs in ${AGENT_PROJECT_ID}..."
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  --project="${AGENT_PROJECT_ID}"

echo "==> 2. Creating Service Accounts (api-caller and token-service-sa)..."
gcloud iam service-accounts create api-caller \
  --description="Service account to call the Agentic Applications API" \
  --display-name="api-caller" \
  --project="${AGENT_PROJECT_ID}" || echo "api-caller already exists, continuing..."

gcloud iam service-accounts create token-service-sa \
  --description="Service account for the Token Issuer Service" \
  --display-name="token-service-sa" \
  --project="${AGENT_PROJECT_ID}" || echo "token-service-sa already exists, continuing..."

echo "==> 3. Granting token-service-sa permission to impersonate and sign JWTs for api-caller..."
gcloud iam service-accounts add-iam-policy-binding "${API_CALLER_SA}" \
  --member="serviceAccount:${TOKEN_SERVICE_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${AGENT_PROJECT_ID}"

echo "==> 4. Creating Artifact Registry repository (if not already present)..."
gcloud artifacts repositories create token-service \
  --repository-format=docker \
  --location="${TOKEN_SERVICE_REGION}" \
  --description="Token Issuer Service repository" \
  --project="${AGENT_PROJECT_ID}" || echo "Repository token-service already exists, continuing..."

IMAGE_URI="${TOKEN_SERVICE_REGION}-docker.pkg.dev/${AGENT_PROJECT_ID}/token-service/token-svc-image:latest"

echo "==> 5. Building and pushing container image via Cloud Build..."
gcloud builds submit . \
  --tag="${IMAGE_URI}" \
  --project="${AGENT_PROJECT_ID}"

echo "==> 6. Deploying Token Issuer Service to Cloud Run..."
gcloud run deploy token-svc \
  --image="${IMAGE_URI}" \
  --region="${TOKEN_SERVICE_REGION}" \
  --service-account="${TOKEN_SERVICE_SA}" \
  --set-env-vars="AGENT_PROJECT_ID=${AGENT_PROJECT_ID},API_CALLER_SA_EMAIL=${API_CALLER_SA},AGENTIC_AGENT_ID=${AGENTIC_AGENT_ID},MOCK_INITIALIZE_SESSION=${MOCK_INITIALIZE_SESSION}" \
  --allow-unauthenticated \
  --project="${AGENT_PROJECT_ID}"

echo "==> Done! Remember to share project '${AGENT_PROJECT_ID}' (SA: ${API_CALLER_SA}) with your Google representative so it is granted access to the Agentic Applications API."
