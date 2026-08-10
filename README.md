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

The `.env` file is ignored by Git. Never commit credentials. `python-oracledb` uses thin mode by default, so Oracle Instant Client is normally unnecessary.

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

## Score direction

The confirmed model direction is `HIGH_SCORE_IS_RISK=false`: larger collection scores indicate safer customers. The AUC calculation reverses the score so the positive class remains `overdue_days >= 31`.

## Production deployment

Production follows the TOKI project-template pattern: Git tags build a Docker image on the production server, and the scheduled workflow runs that image as a batch job.

1. Install Docker and a GitHub Actions self-hosted runner on an approved Linux X64 server that can reach the DWH.
2. Configure the runner as a service and give it the `self-hosted`, `Linux`, and `X64` labels.
3. Open **Settings > Environments**, create an environment named `production`, and add secrets named `DWH_USER`, `DWH_PASSWORD`, `DWH_DSN`, and `POWER_AUTOMATE_URL`.
4. Push a release tag to build `collection-score-report:latest` on that server:

```bash
git tag v0.1.0
git push origin v0.1.0
```

5. Open **Actions**, select **BNPL Collection Score Report**, and choose **Run workflow** to test the production job manually.

The build workflow runs tests, builds the versioned image and `collection-score-report:latest`, and verifies its dry-run entrypoint. The image uses `python-oracledb` thin mode, so Oracle Instant Client is not required.

The monthly workflow runs automatically at `00:00 UTC` on the first day of each month, which is `08:00` in Ulaanbaatar. It mounts `output/` from the runner, generates the report, sends it to Power Automate, and uploads the HTML artifact for 90 days. The server must remain powered on and connected to the Unitel network.

To run the same image directly on the production server:

```bash
docker run --rm \
	--env-file "$HOME/envs/collection-score-report.env" \
	--volume "$PWD/output:/app/output" \
	collection-score-report:latest
```

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
