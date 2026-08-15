# Intelligent Document Redactor

A serverless AWS application that automatically detects and redacts personally identifiable information (PII) from documents. Paste text or upload a scanned image, and the system returns a redacted version with every sensitive value replaced by a labeled placeholder like `[NAME]`, `[ADDRESS]`, or `[SSN]`.

## What it does

Text is sent to Amazon Comprehend, which detects PII entities; each entity is replaced in place with a labeled placeholder (replacing right-to-left so character offsets stay valid). For scanned images, Amazon Textract extracts the text first via OCR. Original and redacted documents are stored in S3 for audit. The whole backend runs serverless on AWS Lambda, deployed through Chalice.

## My role

Designed and built the complete pipeline end to end — the Chalice/Lambda backend and API, the AWS service integration (Comprehend, Textract, S3, IAM), and the frontend.

## AWS services

| Service | Role |
|---|---|
| **Amazon Comprehend** | Core PII detection (`detect_pii_entities`) |
| **Amazon Textract** | OCR text extraction from uploaded images |
| **AWS Lambda (via Chalice)** | Serverless orchestration / backend |
| **Amazon S3** | Stores original and redacted documents for audit |
| **AWS IAM** | Least-privilege roles for Lambda -> Comprehend/Textract/S3 |
| **Amazon CloudWatch** | Lambda execution logs |

## API endpoints

- `GET /health` — health check, returns `{"status": "ok"}`
- `POST /redact/text` — redacts PII from plain text input
- `POST /redact/image` — OCR via Textract, then redaction

Comprehend has a 5,000-byte per-call limit, so longer text is automatically chunked.

## Tech stack

Python, AWS Lambda (Chalice), Amazon Comprehend, Amazon Textract, Amazon S3, IAM, boto3

## Project structure

```
├── intelligent-redactor/    # Chalice app — backend routes (app.py), deploy config
├── frontend/                # single-page HTML/JS frontend
└── README.md
```

## Deploy

```bash
cd intelligent-redactor
pip install -r requirements.txt
chalice deploy
```

Requires AWS credentials configured with access to Comprehend, Textract, and S3. Update the S3 bucket name in `.chalice/config.json` before deploying.
