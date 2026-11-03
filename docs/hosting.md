# Host a private workspace

MuseAutoLab serves the compiled interface, 3D assets and Python API at one HTTPS
address. The server makes the Meta API requests. Everyone given the workspace
login shares its project library and the configured Meta account's model allowance.

## Using the workspace

Sign in and choose **New project** to start with a lab task. **Save project** gives
the setup a name and adds it to **Projects**. Later edits save automatically. From
another browser, sign in and open the same name to resume the design and conversation.
**Import file** brings in an existing portable project, which you can then name.
**Export file** downloads a portable copy. Previous local projects can be moved this way.

The library keeps accepted project state, conversation, model selection and saved
pricing observations. Export jobs and simulation runs can be generated again. Text
still in the message box stays with its browser tab.

## Deploy on Modal

Use one workspace, one environment and one active writer for the project volume.
This deployment runs on a CPU, scales to zero when idle and wakes on the next request.
Projects and authenticated sessions survive that restart. Allow time for the first
request before a live presentation.

1. Connect your Modal workspace using the [Modal setup guide](https://modal.com/docs/guide).
   Install the deployment client separately from the application environment:

   ```powershell
   py -3.12 -m venv .local/modal
   .\.local\modal\Scripts\python.exe -m pip install modal==1.6.3
   .\.local\modal\Scripts\modal.exe setup
   ```

2. Check the credits on **Usage & Billing**. To operate within credits, set the
   **Workspace spend limit** (net charges after credits) to **$0**, and confirm it
   in the dashboard before creating resources. Model calls on the separate Meta
   account follow that account's allowance. [Modal budgets](https://modal.com/docs/guide/budgets)

3. Create the private project volume once, in the same environment as the app:

   ```powershell
   .\.local\modal\Scripts\modal.exe volume create museautolab-projects --version 2
   ```

4. In Modal's **Secrets**, create `museautolab-host`. Fill in the following values
   through the private secret form. Generate the password verifier and signing value
   locally with the application Python environment, away from shared screens and logs.

   | Secret key | Value |
   | --- | --- |
   | `MODEL_API_KEY` | API key from the Meta account that will run the models |
   | `MUSEAUTOLAB_AUTH_USERNAME` | Workspace login name |
   | `MUSEAUTOLAB_AUTH_PASSWORD_HASH` | Output of `python -c "from getpass import getpass; from app.host_auth import hash_password; print(hash_password(getpass()))"` |
   | `MUSEAUTOLAB_AUTH_SIGNING_SECRET` | Output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `MUSEAUTOLAB_AUTH_ORIGIN` | Exact HTTPS origin for the endpoint, without a trailing slash |

   The endpoint label is `museautolab`. Modal supplies the prefix for your workspace
   and environment. If the final hostname is unknown, use `https://unconfigured.invalid`
   for the first deployment. Sign-in stays closed to browser requests at the assigned
   domain until you replace this value and restart the app. [Modal endpoint URLs](https://modal.com/docs/guide/webhook-urls)

5. Deploy from the repository root. The build includes only Git-tracked application
   source and assets selected by the deployment entry point.

   ```powershell
   .\.local\modal\Scripts\modal.exe deploy --strategy recreate -m scripts.deploy_modal
   ```

   Copy the HTTPS address shown by Modal. If the origin secret needs to be updated,
   make the change, stop the old app and redeploy. Before any future deployment, let
   current users finish, stop the app and wait for its containers to exit. This
   prevents two versions from writing to the same project volume during a rollout.

6. In a private browser window, check that the URL displays **Sign in** and that
   `/api/library` returns 401. After sign-in, name a project, create another and reopen
   the first from **Projects**. Check model availability in the design assistant.
   Share the site address and distribute the workspace login privately.

## Other container hosts

The root Dockerfile serves the same application. Use one process, one replica, HTTPS
and a persistent volume mounted at `/data` writable by UID 10001. Configure the five
secret values above, `MUSEAUTOLAB_HOSTED=1` and
`MUSEAUTOLAB_DATABASE_PATH=/data/projects.sqlite3`. The image listens on
`PORT` (default 7860) and exposes a minimal public readiness check at `/healthz`.
Back up the volume privately. GitHub Pages can serve static files, while the full
workspace requires a running Python backend and private storage.
