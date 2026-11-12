# Gemini Enterprise for CX — Shopping Agent Token Issuer Service

Sample backend **Token Issuer Service** for the [Gemini Enterprise for Customer Experience (CX) Shopping Agent](https://docs.cloud.google.com/gemini-enterprise-cx/commerce-agents/shopping/auth).

This service mediates authentication between your frontend **Shopping Chat SDK** and Google Cloud's **Agentic Applications API** (`InitializeSession` and `ExecuteChat`) using a least-privilege, two-service-account architecture.

---

## Architecture

1. **`token-service-sa` (Runtime Service Account):** Attached to the Cloud Run service (`token-svc`). Has no direct access to the Agentic Applications API, only `roles/iam.serviceAccountTokenCreator` on `api-caller`.
2. **`api-caller` (API Caller Service Account):** The target identity allowlisted to invoke the Agentic Applications API (`InitializeSession` and `ExecuteChat`).

### Token Issuance Flow (`POST /get-token`)
1. Authenticates the end user.
2. Runs under `token-service-sa` and impersonates `api-caller` (`google.auth.impersonated_credentials`) to obtain a short-lived, unbound OAuth 2.0 access token.
3. Calls `https://agenticapplications.googleapis.com/v1/sales:initializeSession` with the OAuth 2.0 token to create or continue a `sessionId`.
4. Uses the Google IAM `signJwt` API to sign a 1-hour session-bound JWT as `api-caller` with `"chat_scope": "sessionId:<sessionId>"`.
5. Returns `{ "token": "<jwt>", "sessionId": "<sessionId>", "expiry": <unix_timestamp> }` to the frontend Chat SDK.

---

## Repository Structure

* `main.py` — Flask application implementing `/get-token` and `/health`.
* `requirements.txt` — Python dependencies.
* `Dockerfile` — Container image definition using `python:3.11-slim` and `gunicorn`.
* `setup_gcp.sh` — Automated script to enable GCP APIs, create `api-caller` and `token-service-sa`, bind `roles/iam.serviceAccountTokenCreator`, build the image, and deploy to Cloud Run.

---

## Quickstart & Deployment

### 1. Deploy with Mock Session Initialization (Test IAM Impersonation & JWT Signing)
Before your `AGENTIC_AGENT_ID` is provisioned by Google, you can test the two-service-account impersonation and `signJwt` flow by setting `MOCK_INITIALIZE_SESSION=true`:

```bash
chmod +x setup_gcp.sh
MOCK_INITIALIZE_SESSION=true ./setup_gcp.sh
```

### 2. Deploy with Live `InitializeSession`
Once you receive your `AGENTIC_AGENT_ID` from Google:

```bash
AGENTIC_AGENT_ID="your-agent-id" MOCK_INITIALIZE_SESSION=false ./setup_gcp.sh
```

### 3. Test the Endpoint

```bash
curl -X POST "https://<YOUR_CLOUD_RUN_URL>/get-token" \
  -H "Content-Type: application/json" \
  -d '{"sessionId": "shopping-session-12345"}'
```
