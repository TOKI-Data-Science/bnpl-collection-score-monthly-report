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

## GitHub deployment

1. Push this repository to GitHub.
2. Open **Settings > Environments**, create an environment named `production`, and add environment secrets named `DWH_USER`, `DWH_PASSWORD`, `DWH_DSN`, and `POWER_AUTOMATE_URL`.
3. Open **Actions**, select **BNPL Collection Score Report**, and choose **Run workflow** to test it manually.
4. Download the generated report from the workflow run's **Artifacts** section if needed. Artifacts are retained for 90 days.

The workflow in `.github/workflows/monthly-report.yml` runs automatically at `00:00 UTC` on the first day of each month, which is `08:00` in Ulaanbaatar. GitHub schedules run from the default branch and can be delayed during periods of high Actions load.

The default workflow uses a GitHub-hosted Ubuntu runner. It must be able to reach `DWH_DSN`. If the DWH is only available inside the company network, install a GitHub self-hosted runner on an approved internal machine and change both `runs-on: ubuntu-latest` values to the runner's labels, for example `runs-on: self-hosted`.

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
