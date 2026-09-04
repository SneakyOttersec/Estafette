# Deploy the Google Drive delivery app

The public app has three parts:

1. `site/` is a static GitHub Pages site.
2. `backend/` is a small Cloud Run service that completes Google OAuth,
   creates each user's `Estafette` folder, and stores the encrypted grant.
3. The existing Monday workflow builds the PDFs and runs
   `backend/distribute.py` to upload them to every active registration.

The app requests only `openid` and
`https://www.googleapis.com/auth/drive.file`. It neither requests nor needs
access to unrelated files in a user's Drive.

## 1. Prepare a Google Cloud project

Create a production Google Cloud project with billing enabled. Enable:

- Google Drive API
- Cloud Run Admin API
- Cloud Build API
- Artifact Registry API
- Firestore API
- Secret Manager API
- IAM Service Account Credentials API
- Security Token Service API

Create a Firestore database in Native mode. A European location is sensible
when most users are in Europe; the database location cannot be changed later.

Use separate Google Cloud projects for local/testing and production. Google
also recommends separate deployment tiers in its OAuth policy.

## 2. Configure the OAuth application

In **Google Auth Platform**:

1. Create an External app named `Estafette`.
2. Set the homepage to `https://sneakyottersec.github.io/Estafette/`.
3. Set the privacy-policy URL to
   `https://sneakyottersec.github.io/Estafette/privacy.html`.
4. Add the `openid` and `.../auth/drive.file` scopes.
5. Create an OAuth client of type **Web application**.

The final authorized redirect URI is:

```text
https://YOUR-CLOUD-RUN-SERVICE-URL/auth/callback
```

The Cloud Run URL does not exist until the first deployment. For the bootstrap
deployment, give the OAuth client a temporary HTTPS redirect, deploy the
service, then replace it with the exact Cloud Run callback URL and redeploy.

Do not leave the OAuth app in Testing for real subscribers. Google expires
testing authorizations after seven days when a Drive scope is requested.
`drive.file` is non-sensitive, so it does not require the restricted-scope
security assessment; publishing the app may still require brand verification.

## 3. Create the application secrets

Create these Secret Manager secrets. Keep the names exactly as shown because
the workflows reference them:

| Secret | Value |
| --- | --- |
| `estafette-google-oauth-client-id` | Web OAuth client ID |
| `estafette-google-oauth-client-secret` | Web OAuth client secret |
| `estafette-token-encryption-key` | Fernet key used to encrypt refresh tokens |
| `estafette-session-secret` | Random Flask session-signing value |

Generate the encryption value locally:

```bash
PYTHONPATH=backend python -m estafette_service.generate_key
```

Generate the session value separately, for example with a password manager or
`openssl rand -hex 32`. Add values through Secret Manager rather than putting
them in a shell history or repository file.

The same encryption-key secret is read by Cloud Run when a user registers and
by the Monday GitHub Action when it decrypts the grant for delivery. Rotating
that key requires re-encrypting existing records first.

## 4. Create service identities and GitHub federation

Create two service accounts:

- A Cloud Run runtime identity with Firestore user and Secret Manager secret
  accessor permissions.
- A GitHub deployment/distribution identity with permission to deploy the
  Cloud Run service, act as the runtime identity, read the three distribution
  secrets, and read/write the Firestore registration collection.

Configure GitHub Actions authentication with Workload Identity Federation,
restricted to `SneakyOttersec/Estafette`. Do not create a downloadable service
account key. Follow Google's maintained setup instructions for
[`google-github-actions/auth`](https://github.com/google-github-actions/auth#workload-identity-federation).

Source deployments also use Cloud Build. Grant the Cloud Build service identity
the documented Cloud Run builder permissions for the project.

## 5. Set GitHub repository variables

Under **Settings → Secrets and variables → Actions → Variables**, configure:

| Variable | Example |
| --- | --- |
| `GCP_PROJECT_ID` | `estafette-prod` |
| `GCP_REGION` | `europe-west1` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/123456789/locations/global/workloadIdentityPools/github/providers/estafette` |
| `GCP_SERVICE_ACCOUNT` | `estafette-github@estafette-prod.iam.gserviceaccount.com` |
| `GCP_RUNTIME_SERVICE_ACCOUNT` | `estafette-runtime@estafette-prod.iam.gserviceaccount.com` |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://SERVICE.run.app/auth/callback` |
| `ESTAFETTE_API_URL` | `https://SERVICE.run.app` |
| `REMARKABLE_APP_URL` | Public URL of the reMarkable installer (optional) |

`ESTAFETTE_API_URL` and `REMARKABLE_APP_URL` are public configuration injected
into the Pages artifact; they are not secrets.

## 6. Deploy

1. In GitHub **Settings → Pages**, select **GitHub Actions** as the source.
2. Run **Deploy Estafette registration backend** from the Actions tab.
3. Copy the Cloud Run URL printed by the workflow.
4. Update the OAuth client's authorized redirect URI and the
   `GOOGLE_OAUTH_REDIRECT_URI` repository variable.
5. Set `ESTAFETTE_API_URL` to the Cloud Run URL.
6. Run the backend deployment again.
7. Run **Deploy Estafette registration page**.

Check `https://SERVICE.run.app/healthz`, then connect a test Google account from
the Pages site. The account should receive a new user-owned folder named
`Estafette` without exposing any other Drive files.

The next successful PDF build distributes every generated `dist/*.pdf` file.
Re-running delivery is safe: a file with the same name is updated instead of
duplicated.

## 7. Disconnect and failure behaviour

Disconnecting performs a fresh Google identity check, revokes the stored grant,
and deletes the Firestore registration. Previously delivered files and the
user-owned folder remain in that user's Drive.

One broken or revoked user grant does not prevent delivery to other users. The
record is marked `reconnect_required` with a bounded error description so it
can be diagnosed without retaining access tokens or PDF contents.

## Production checklist

- Replace the placeholder operator/contact paragraph in `site/privacy.html`.
- Complete OAuth production/brand verification before inviting users.
- Set Cloud Run minimum instances to zero unless low-latency OAuth callbacks
  justify the idle cost.
- Add Firestore backups and log-based alerts for distribution failures.
- Review the licences or permissions for article text and images before
  redistributing compiled PDFs.
