# Intelligent Document Redactor
**COMP 264 — Cloud Machine Learning | Centennial College**

Team: Ajmal Afzalzada, Sina Cetinkaya, Mohammed Badruddin Saad

---

## What It Does

A serverless web application that automatically detects and redacts Personally Identifiable Information (PII) from documents. Users paste text or upload a scanned image; the system returns a redacted version with all sensitive values replaced by labeled placeholders like `[NAME]`, `[ADDRESS]`, `[SSN]`.

---

## AWS Services Used

| Service | Role |
|---|---|
| **Amazon Comprehend** | Core PII detection — `detect_pii_entities()` |
| **Amazon Textract** | OCR text extraction from images (stretch goal) |
| **AWS Lambda (via Chalice)** | Orchestration layer / serverless backend |
| **Amazon S3** | Stores original and redacted documents for audit |
| **AWS IAM** | Least-privilege roles for Lambda → Comprehend/Textract/S3 |
| **Amazon CloudWatch** | Automatic Lambda execution logs |

---

## Project Structure

```
intelligent-redactor/
├── .chalice/
│   ├── config.json          # Chalice deployment config
│   └── policy-dev.json      # IAM policy for Lambda execution role
├── frontend/
│   └── index.html           # Single-page HTML/JS frontend
├── app.py                   # Chalice app — all backend routes
├── requirements.txt
├── setup.sh                 # Bootstrap + local run script
└── README.md
```

---

## API Endpoints

### `GET /health`
Health check. Returns `{"status": "ok"}`.

---

### `POST /redact/text`
Redact PII from plain text input.

**Request:**
```json
{ "text": "John Smith lives at 123 Main St, SIN 123-456-789." }
```

**Response:**
```json
{
  "document_id": "uuid-v4",
  "redacted_text": "[NAME] lives at [ADDRESS], SIN [SSN].",
  "entities_found": 3,
  "redaction_log": [
    { "type": "NAME", "original": "John Smith", "placeholder": "[NAME]", "confidence": 0.9998 }
  ]
}
```

---

### `POST /redact/image`
Extract text from an image via Textract, then redact PII.

**Request:**
```json
{
  "image_base64": "<base64-encoded PNG or JPEG>",
  "media_type": "image/jpeg"
}
```

**Response:** Same as `/redact/text` plus `extracted_text` field.

---

### `GET /document/{document_id}`
Retrieve a previously processed document by ID.

---

## Running Locally

```bash
# Make sure AWS credentials are configured
aws configure

# Bootstrap and start local server
bash setup.sh
```

Then open `frontend/index.html` in your browser.
Set the API URL field to `http://localhost:8000`.

---

## Deploying to AWS

```bash
source .venv/bin/activate
chalice deploy --stage dev
```

Chalice will output the deployed API Gateway URL. Paste it into the API URL field in the frontend.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Right-to-left entity replacement | Replacing entities from the end of the string backwards ensures character offsets returned by Comprehend remain valid throughout the loop. |
| Text chunking at 4900 bytes | Amazon Comprehend's `detect_pii_entities` has a 5000-byte limit per call. Chunking with a 100-byte buffer prevents edge-case failures on multibyte characters. |
| S3 failure is non-blocking | Storage errors are logged but do not prevent the user from receiving their redacted output. Availability of the core service takes priority. |
| Vanilla JS frontend | No build toolchain required. Any browser opens `index.html` directly, making local testing trivially simple. |
| IAM least-privilege policy | Lambda role is granted only the specific actions it needs — no wildcards on resources for S3, no admin access. |
