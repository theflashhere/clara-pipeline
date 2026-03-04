# Clara Answers — AI Voice Agent Pipeline

Automated pipeline: call transcript -> structured account memo -> Retell voice agent config -> versioned updates.

Built for Clara Answers internship assignment. Zero-cost, no paid APIs required.

---

## How It Works

```
Transcript (.docx / .txt)
        |
        v
  Pipeline A (local_pipeline.py)
        |
        |-- outputs/accounts/<id>/v1/account_memo.json
        +-- outputs/accounts/<id>/v1/agent_spec.json
        |
        | (onboarding update arrives)
        v
  Pipeline B (pipeline_b.py)
        |
        |-- outputs/accounts/<id>/v2/account_memo.json
        |-- outputs/accounts/<id>/v2/agent_spec.json
        |-- outputs/accounts/<id>/v2/changelog.json
        +-- outputs/accounts/<id>/v2/changelog.md
```

---

## Quickstart — Run in 3 Commands

### 1. Install the one dependency

Windows:
```
pip install python-docx
```

Mac / Linux:
```
pip3 install python-docx
```

---

### 2. Run Pipeline A — Generate Agent v1

```
python scripts/local_pipeline.py --transcript data/onboarding_bens-electric-solutions.docx --source-type onboarding_call
```

Expected output:
```
[Clara Pipeline] Processing: data/onboarding_bens-electric-solutions.docx
  Transcript length: 21528 chars
  Using rule-based extraction (zero-cost mode)...
  outputs/accounts/ben-s-electric-solutions/v1/account_memo.json
  outputs/accounts/ben-s-electric-solutions/v1/agent_spec.json
Pipeline complete: ben-s-electric-solutions/v1
```

---

### 3. Run Pipeline B — Update to v2

```
python scripts/pipeline_b.py --update data/onboarding_update_bens-electric-solutions.txt --v1-memo outputs/accounts/ben-s-electric-solutions/v1/account_memo.json
```

Expected output:
```
[Pipeline B] Detected 10 field updates
  outputs/accounts/ben-s-electric-solutions/v2/account_memo.json
  outputs/accounts/ben-s-electric-solutions/v2/agent_spec.json
  outputs/accounts/ben-s-electric-solutions/v2/changelog.json
  outputs/accounts/ben-s-electric-solutions/v2/changelog.md
Pipeline B complete: ben-s-electric-solutions/v2 (13 changes)
```

---

### 4. Open the Dashboard

Double-click dashboard/index.html in your file explorer.
Opens in any browser, no server needed.

- Use the v1 / v2 toggle (top right) to switch versions
- Click "v1 to v2 Diff" in the sidebar to see every change and why

---

## Run on Your Own Transcripts

Single file:
```
python scripts/local_pipeline.py --transcript data/your_transcript.docx --source-type onboarding_call
```

Source type options: demo_call | onboarding_call | onboarding_form

Batch — process all files in data/ at once:
```
python scripts/batch_run.py --dataset ./data
```

Name your files like this so the batch runner pairs them automatically:
```
data/
  demo_company-name.docx           <- Pipeline A (demo call)
  onboarding_company-name.docx     <- Pipeline B (onboarding update)
```

---

## Optional: Use Claude API for Better Extraction

The pipeline runs fully offline using rule-based extraction.
Set a free Anthropic API key for smarter extraction:

Windows:
```
set ANTHROPIC_API_KEY=your_key_here
python scripts/local_pipeline.py --transcript data/your_file.docx
```

Mac / Linux:
```
export ANTHROPIC_API_KEY=your_key_here
python3 scripts/local_pipeline.py --transcript data/your_file.docx
```

---

## File Structure

```
clara-pipeline/
|-- README.md
|-- setup.sh                             <- One-command setup (Mac/Linux)
|-- scripts/
|   |-- local_pipeline.py                <- Pipeline A: transcript -> v1
|   |-- pipeline_b.py                    <- Pipeline B: update -> v2 + changelog
|   |-- batch_run.py                     <- Batch processor for multiple accounts
|   |-- extract_memo.py                  <- Claude API extraction engine
|   +-- generate_agent_spec.py           <- Agent spec generator
|-- data/
|   |-- onboarding_bens-electric-solutions.docx
|   +-- onboarding_update_bens-electric-solutions.txt
|-- dashboard/
|   +-- index.html                       <- Visual dashboard (open in browser)
|-- workflows/
|   +-- n8n_workflow.json                <- n8n automation export
+-- outputs/
    +-- accounts/
        +-- ben-s-electric-solutions/
            |-- v1/
            |   |-- account_memo.json
            |   +-- agent_spec.json
            +-- v2/
                |-- account_memo.json
                |-- agent_spec.json
                |-- changelog.json
                +-- changelog.md
```

---

## Output Files Explained

| File | What it contains |
|------|-----------------|
| account_memo.json | All extracted config: business hours, pricing, routing, emergency rules, unknowns |
| agent_spec.json | Full Retell agent: system prompt, voice settings, transfer + fallback protocols |
| changelog.json | Machine-readable diff of every field changed v1 to v2 |
| changelog.md | Human-readable table: field, old value, new value, reason |

---

## Deploy to Retell (Manual Import)

Retell API requires a paid plan. Use manual import:

1. Go to app.retellai.com -> Agents -> Create New Agent
2. Set agent name: Clara - [Company Name]
3. Open agent_spec.json -> copy the system_prompt field -> paste into Retell
4. Set transfer number from call_routing.transfer_phone_number
5. Select voice: Olivia or similar warm English voice
6. Save and run test calls

---

## n8n Automation (Optional)

```
docker run -it --rm -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n
```

Go to localhost:5678 -> Workflows -> Import -> upload workflows/n8n_workflow.json

Trigger Pipeline A:
```
POST localhost:5678/webhook/pipeline-a
{ "transcript_path": "data/your_file.docx", "source_type": "onboarding_call" }
```

---

## Known Limitations

- Rule-based extraction is tuned for service trade businesses
- Audio files must be transcribed first (.docx or .txt input only)
- Retell programmatic agent creation requires paid tier
- Timezone is inferred from area code when not stated in transcript

## What Would Be Added with Production Access

- Retell API for programmatic agent creation and updates
- Whisper integration to auto-transcribe recordings
- Supabase for real-time shared account database
- Asana API to auto-create onboarding tasks per account
- Confidence scoring to flag uncertain extractions for human review
- Google Drive webhook to auto-trigger pipeline on new upload
