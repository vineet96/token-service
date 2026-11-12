import json
import os
import time
import uuid
from flask import Flask, jsonify, request
import flask_cors
import google.auth
from google.auth import exceptions
from google.auth import impersonated_credentials
import google.auth.transport.requests
from googleapiclient import discovery
import requests

app = Flask(__name__)
# Enable CORS - restrict origins in production
flask_cors.CORS(app, supports_credentials=True)

# Pre-configured defaults for GCP project ge-poc-511814
AGENT_PROJECT_ID = os.environ.get("AGENT_PROJECT_ID", "ge-poc-511814")
API_CALLER_SA_EMAIL = os.environ.get(
    "API_CALLER_SA_EMAIL",
    f"api-caller@{AGENT_PROJECT_ID}.iam.gserviceaccount.com",
)
AGENTIC_API_ENDPOINT = os.environ.get(
    "AGENTIC_API_ENDPOINT", "https://agenticapplications.googleapis.com"
)
AGENTIC_AGENT_ID = os.environ.get(
    "AGENTIC_AGENT_ID"
)  # Agent ID received from Google
MOCK_INITIALIZE_SESSION = (
    os.environ.get("MOCK_INITIALIZE_SESSION", "false").lower() == "true"
)


def _get_request_data(req: request):
    """Returns the request data from the flask request."""
    request_data = req.get_json(silent=True)
    if request_data:
        app.logger.info("Request data loaded via get_json.")
    else:
        app.logger.info(
            "get_json failed to parse request data, falling back to get_data."
        )
        raw_data = req.get_data()
        if raw_data:
            try:
                request_data = json.loads(raw_data.decode("utf-8"))
                app.logger.info("Request data loaded via get_data.")
            except (json.JSONDecodeError, UnicodeDecodeError):
                app.logger.warning(
                    "Content-Type is not application/json and failed to parse"
                    " request body as JSON."
                )
                request_data = {}
        else:
            request_data = {}
    return request_data


@app.route("/get-token", methods=["POST"])
@flask_cors.cross_origin(supports_credentials=True)
def get_token():
    """Returns a session-bound JWT for the Shopping Agent frontend Chat SDK."""
    if not API_CALLER_SA_EMAIL:
        return (
            jsonify({"error": "API_CALLER_SA_EMAIL environment variable not set"}),
            500,
        )
    if not AGENTIC_AGENT_ID and not MOCK_INITIALIZE_SESSION:
        return (
            jsonify({"error": "AGENTIC_AGENT_ID environment variable not set"}),
            500,
        )

    # user_id is required by InitializeSession; replace with your app's user auth ID
    user_id = str(uuid.uuid4())

    try:
        # Obtain base credentials (runs as token-service-sa@ge-poc-511814.iam.gserviceaccount.com)
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

        # 1. Impersonate api-caller SA to get an unbound OAuth 2.0 token for InitializeSession
        target_credentials = impersonated_credentials.Credentials(
            source_credentials=credentials,
            target_principal=API_CALLER_SA_EMAIL,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=3600,
        )
        auth_request = google.auth.transport.requests.Request()
        target_credentials.refresh(auth_request)
        oauth_token = target_credentials.token

        # 2. Call InitializeSession (or continue an existing session if sessionId is provided)
        request_data = _get_request_data(request)
        if MOCK_INITIALIZE_SESSION:
            # Useful for testing IAM impersonation & JWT signing before AGENTIC_AGENT_ID is provisioned
            session_id = request_data.get(
                "sessionId", f"mock-session-{uuid.uuid4().hex[:8]}"
            )
        else:
            try:
                init_session_url = (
                    f"{AGENTIC_API_ENDPOINT}/v1/sales:initializeSession"
                )
                init_session_payload = {
                    "userId": user_id,
                    "agentId": AGENTIC_AGENT_ID,
                }
                if "sessionId" in request_data:
                    init_session_payload["sessionId"] = request_data["sessionId"]

                session_metadata = {
                    "auth": {},
                    "trusted": {},
                    "untrusted": {},
                }
                init_session_payload["sessionMetadata"] = session_metadata

                headers = {
                    "Authorization": f"Bearer {oauth_token}",
                    "Content-Type": "application/json",
                }
                init_session_response = requests.post(
                    init_session_url,
                    headers=headers,
                    json=init_session_payload,
                    timeout=30,
                )
                init_session_response.raise_for_status()
                session_id = init_session_response.json().get("sessionId")
            except requests.exceptions.RequestException as e:
                return (
                    jsonify({"error": f"Failed to initialize session: {e}"}),
                    500,
                )

        # 3. Create a JWT signed by api-caller and bound to session_id
        iam_service = discovery.build("iam", "v1", credentials=credentials)
        name = f"projects/-/serviceAccounts/{API_CALLER_SA_EMAIL}"

        iat = int(time.time())
        exp = iat + 3600
        claims = {
            "iss": API_CALLER_SA_EMAIL,
            "sub": API_CALLER_SA_EMAIL,
            "aud": f"{AGENTIC_API_ENDPOINT}/google.cloud.agenticapplications.v1.SalesService",
            "iat": iat,
            "exp": exp,
            "chat_scope": f"sessionId:{session_id}",
        }
        body = {"payload": json.dumps(claims)}

        try:
            response = (
                iam_service.projects()
                .serviceAccounts()
                .signJwt(name=name, body=body)
                .execute()
            )
            jwt_token = response["signedJwt"]
        except Exception as e:
            return jsonify({"error": f"Failed to sign JWT: {e}"}), 500

        return jsonify(
            {
                "token": jwt_token,
                "sessionId": session_id,
                "expiry": exp,
            }
        )

    except (exceptions.DefaultCredentialsError, exceptions.RefreshError) as e:
        return (
            jsonify(
                {
                    "error": f"Failed to generate token for {API_CALLER_SA_EMAIL}: {e}"
                }
            ),
            500,
        )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "project": AGENT_PROJECT_ID}), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
