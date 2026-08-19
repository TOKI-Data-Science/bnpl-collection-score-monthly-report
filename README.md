# BNPL Collection Score V1 Report

Monthly model monitoring for BNPL customers scored at `OD=6`. The report evaluates whether each customer reaches `overdue_days >= 31` on `base_date + 25` and produces:

- Overall AUC
- AUC by score date
- AUC and outcomes by score month
- Customer count, events, and event rate
- Event rate and volume by collection score grade

## Aging logic

Every run reads all historical rows whose score date has aged 25 days.

## Local setup

For normal Windows use, run one command from the project folder:

```powershell
.\run-report.cmd
```

The launcher always uses `.venv`, installs missing dependencies, generates `output/report.html`, and opens it in the default browser. No virtual-environment activation is needed.

The manual setup below is only needed for development.

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and enter the DWH connection values:

```dotenv
DWH_USER=your_username
DWH_PASSWORD=your_password_or_passport
DWH_DSN=hostname:1521/service_name
HIGH_SCORE_IS_RISK=false
```


Check the aging cutoff without connecting to DWH:

```powershell
python report.py --as-of 2026-08-01 --dry-run
```

Generate the report from DWH:

```powershell
python report.py --output output/report.html
```

For offline development, provide a CSV containing at least `user_id`, `base_date`, `collection_score`, `collection_score_grade`, and `event`:

```powershell
python report.py --input-csv sample.csv --as-of 2026-08-01
```

## Production deployment

Production follows the TOKI project-template pattern: Git tags build a Docker image on the production server, and the scheduled workflow runs that image as a batch job.

### One-time server setup

These steps are done once per server. Skip if the server already has Docker and an Actions runner for your GitHub organization.

**1. Install Docker on the Linux production server**

```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# Log out and back in for the group change to take effect
docker run --rm hello-world   # verify
```

**2. Register a GitHub Actions self-hosted runner**

Create a dedicated directory for each project to keep runners isolated:

```bash
mkdir -p ~/actions-runner-PROJECTNAME
cd ~/actions-runner-PROJECTNAME

curl -o actions-runner-linux-x64-2.336.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.336.0/actions-runner-linux-x64-2.336.0.tar.gz

tar xzf actions-runner-linux-x64-2.336.0.tar.gz
```

On GitHub, open **Repository → Settings → Actions → Runners → New self-hosted runner → Linux → x64** and copy the registration token. Run on the server:

```bash
./config.sh \
  --url https://github.com/ORG/REPO \
  --token PASTE_TOKEN_HERE \
  --name SERVERNAME-PROJECTNAME \
  --work _work \
  --unattended
```

Install as a persistent service so it survives reboots and SSH disconnects:

```bash
sudo ./svc.sh install ubuntu
sudo ./svc.sh start
sudo ./svc.sh status
```

Verify it appears as **Idle** with labels `self-hosted`, `Linux`, `X64` under **Settings → Actions → Runners**.

> **Note:** Each runner directory is registered to one repository. If the server already has a runner for another organization (check `cat ~/actions-runner/.runner`), always create a new directory — never reconfigure the existing one.

### One-time GitHub setup

**3. Create the production environment and secrets**

Open **Settings → Environments → New environment**, name it `production`, then add the required secrets. For this project:

| Secret | Description |
|---|---|
| `DWH_USER` | Oracle username |
| `DWH_PASSWORD` | Oracle password |
| `DWH_DSN` | Oracle DSN (`host:port/service`) |
| `POWER_AUTOMATE_URL` | Power Automate HTTP trigger URL (optional) |

`POWER_AUTOMATE_URL` is optional. When omitted, email delivery is skipped and the report is available as a GitHub Actions artifact only. Add it later to enable email delivery.

### Deploy a new version

Push a release tag to trigger the build workflow:

```bash
git tag v0.x.x
git push origin v0.x.x
```

The **Build Production Image** workflow runs tests, builds the Docker image on `bhtg`, tags it as both `vX.X.X` and `latest`, and verifies the production entrypoint. No manual steps are needed on the server.

### Run the report manually

Open **Actions → BNPL Collection Score Report → Run workflow**. Use this after deploying a new version to verify end-to-end before the next scheduled run.

### Scheduled execution

The monthly workflow runs automatically at `00:00 UTC` on the first day of each month, which is `08:00` in Ulaanbaatar. It mounts `output/` from the runner, generates the report, and uploads the HTML artifact for 90 days. The server must remain powered on and connected to the Unitel network.

### Download the report

Open **Actions → BNPL Collection Score Report → click the latest green run → Artifacts → `bnpl-collection-score-N`**. Extract the zip and open `bnpl_collection_score_v1.html` in any browser.

### Run the image directly on the server

```bash
docker run --rm \
  --env-file "$HOME/envs/collection-score-report.env" \
  --volume "$PWD/output:/app/output" \
  collection-score-report:latest
```

### Applying this pattern to a new project

1. Copy `.github/workflows/build-image.yml` and `.github/workflows/monthly-report.yml` into the new repository.
2. Replace `collection-score-report` with the new image name throughout both files.
3. Replace `script.py` with the new project's entrypoint.
4. Follow **One-time server setup** and **One-time GitHub setup** above.
5. Push a tag to deploy.

## Outlook delivery with Power Automate

Create an automated cloud flow in Power Automate:

1. Choose the **When an HTTP request is received** trigger.
2. Use this request body JSON schema:

```json
{
	"type": "object",
	"properties": {
		"modelName": { "type": "string" },
		"reportFileName": { "type": "string" },
		"reportContentBase64": { "type": "string" },
		"generatedAt": { "type": "string" }
	},
	"required": ["modelName", "reportFileName", "reportContentBase64", "generatedAt"]
}
```

3. Add the Outlook **Send an email (V2)** action.
4. Set recipients, subject `Monthly report - @{triggerBody()?['modelName']}`, and the desired email message.
5. In **Attachments Name - 1**, enter `@{triggerBody()?['reportFileName']}`.
6. In **Attachments Content - 1**, enter `@{base64ToBinary(triggerBody()?['reportContentBase64'])}`.
7. Save the flow and copy the HTTP POST URL from its trigger.
8. In GitHub, add the URL as the `POWER_AUTOMATE_URL` secret in the `production` environment. The URL contains an authorization signature and must be treated as a secret.
9. Run the GitHub Actions workflow manually once and confirm the email attachment arrives and opens.

The `monthly-report` job sends the generated HTML to this flow after report generation. A failed Power Automate request fails the job, and the artifact upload still runs for troubleshooting. The HTTP request trigger may require a Power Automate Premium license depending on the organization's Microsoft 365 plan.

## Validation

```powershell
python -m pytest -q
```

Before production use, confirm that `toki.bnpl_receivable` has only one matching row per account and `p_date`; otherwise aggregate or select one receivable row before joining to avoid duplicate customers.
