import os
import uuid
import json
import base64
import logging
from datetime import datetime

import boto3
from chalice import Chalice, Response, BadRequestError, ChaliceViewError

app = Chalice(app_name="intelligent-redactor")
app.log.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("S3_BUCKET", "intelligent-redactor-docs")

comprehend = boto3.client("comprehend", region_name="us-east-1")
textract = boto3.client("textract", region_name="us-east-1")
s3 = boto3.client("s3", region_name="us-east-1")


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Content-Type": "application/json",
    }


def redact_text(text):
    """
    Call Amazon Comprehend to detect PII entities in the provided text,
    then replace each detected entity with a labeled placeholder.
    Works by replacing from right-to-left so character offsets stay valid.
    """
    if not text or not text.strip():
        raise BadRequestError("Input text must not be empty.")

    # Comprehend has a 5000-byte limit per call — chunk if needed
    MAX_BYTES = 4900
    encoded = text.encode("utf-8")

    if len(encoded) <= MAX_BYTES:
        chunks = [(text, 0)]
    else:
        chunks = _chunk_text(text, MAX_BYTES)

    all_entities = []

    for chunk_text, byte_offset in chunks:
        try:
            response = comprehend.detect_pii_entities(
                Text=chunk_text,
                LanguageCode="en"
            )
        except comprehend.exceptions.TextSizeLimitExceededException as e:
            app.log.error("Comprehend text size limit: %s", str(e))
            raise ChaliceViewError("Text chunk too large for Comprehend.")
        except Exception as e:
            app.log.error("Comprehend error: %s", str(e))
            raise ChaliceViewError("Failed to call Amazon Comprehend.")

        for entity in response.get("Entities", []):
            # Adjust offsets to be relative to the full text
            char_start = len(chunk_text[:entity["BeginOffset"]].encode("utf-8").decode("utf-8"))
            all_entities.append({
                "BeginOffset": entity["BeginOffset"] + _char_offset(text, byte_offset),
                "EndOffset": entity["EndOffset"] + _char_offset(text, byte_offset),
                "Type": entity["Type"],
                "Score": entity["Score"],
            })

    # Sort entities in reverse order so we can replace without offset drift
    all_entities.sort(key=lambda e: e["BeginOffset"], reverse=True)

    redacted = text
    redaction_log = []

    for entity in all_entities:
        start = entity["BeginOffset"]
        end = entity["EndOffset"]
        label = f"[{entity['Type']}]"
        original_value = redacted[start:end]
        redacted = redacted[:start] + label + redacted[end:]
        redaction_log.append({
            "type": entity["Type"],
            "original": original_value,
            "placeholder": label,
            "confidence": round(entity["Score"], 4),
        })

    return redacted, list(reversed(redaction_log))


def _char_offset(text, byte_offset):
    """Convert a byte offset in the full text to a character offset."""
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8", errors="replace"))


def _chunk_text(text, max_bytes):
    """
    Split text into chunks that fit within max_bytes.
    Returns list of (chunk_text, byte_start_offset) tuples.
    """
    chunks = []
    encoded = text.encode("utf-8")
    start = 0

    while start < len(encoded):
        end = start + max_bytes
        chunk_bytes = encoded[start:end]
        # Make sure we don't cut in the middle of a multi-byte character
        chunk_text = chunk_bytes.decode("utf-8", errors="ignore")
        chunks.append((chunk_text, start))
        start += len(chunk_text.encode("utf-8"))

    return chunks


def save_to_s3(document_id, original_text, redacted_text, source="text"):
    """
    Persist the original and redacted documents to S3.
    Uses a folder structure: documents/<document_id>/
    """
    timestamp = datetime.utcnow().isoformat()
    metadata = {
        "document_id": document_id,
        "timestamp": timestamp,
        "source": source,
    }

    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"documents/{document_id}/original.txt",
            Body=original_text.encode("utf-8"),
            ContentType="text/plain",
            Metadata={"document-id": document_id, "type": "original"},
        )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"documents/{document_id}/redacted.txt",
            Body=redacted_text.encode("utf-8"),
            ContentType="text/plain",
            Metadata={"document-id": document_id, "type": "redacted"},
        )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"documents/{document_id}/metadata.json",
            Body=json.dumps(metadata).encode("utf-8"),
            ContentType="application/json",
        )
        app.log.info("Saved document %s to S3.", document_id)
    except Exception as e:
        # S3 storage failure should not block the user from getting their result
        app.log.error("S3 storage error for document %s: %s", document_id, str(e))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"], cors=True)
def health():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "intelligent-redactor"}


@app.route("/redact/text", methods=["POST"], cors=True)
def redact_text_endpoint():
    """
    Accept a plain text body and return a redacted version.

    Request body (JSON):
        { "text": "John Smith lives at 123 Main St..." }

    Response (JSON):
        {
            "document_id": "...",
            "redacted_text": "...",
            "entities_found": 3,
            "redaction_log": [...]
        }
    """
    request = app.current_request
    body = request.json_body

    if not body or "text" not in body:
        raise BadRequestError("Request body must include a 'text' field.")

    raw_text = body["text"]

    if len(raw_text) > 100_000:
        raise BadRequestError("Text exceeds maximum allowed length of 100,000 characters.")

    app.log.info("Received redact/text request — %d characters.", len(raw_text))

    redacted, redaction_log = redact_text(raw_text)

    document_id = str(uuid.uuid4())
    save_to_s3(document_id, raw_text, redacted, source="text-input")

    return {
        "document_id": document_id,
        "redacted_text": redacted,
        "entities_found": len(redaction_log),
        "redaction_log": redaction_log,
    }


@app.route("/redact/image", methods=["POST"], cors=True)
def redact_image_endpoint():
    """
    Accept a base64-encoded image (PNG/JPEG) or PDF page, extract text
    via Amazon Textract, then redact PII with Comprehend.

    Request body (JSON):
        {
            "image_base64": "<base64 string>",
            "media_type": "image/jpeg"   (or image/png, application/pdf)
        }
    """
    request = app.current_request
    body = request.json_body

    if not body or "image_base64" not in body:
        raise BadRequestError("Request body must include 'image_base64'.")

    media_type = body.get("media_type", "image/jpeg")
    allowed_types = {"image/jpeg", "image/png", "application/pdf"}
    if media_type not in allowed_types:
        raise BadRequestError(f"Unsupported media_type. Allowed: {', '.join(allowed_types)}")

    try:
        image_bytes = base64.b64decode(body["image_base64"])
    except Exception:
        raise BadRequestError("Invalid base64 encoding for image_base64.")

    app.log.info("Received redact/image request — %d bytes, type=%s.", len(image_bytes), media_type)

    # Extract text via Textract
    try:
        textract_response = textract.detect_document_text(
            Document={"Bytes": image_bytes}
        )
    except textract.exceptions.UnsupportedDocumentException:
        raise BadRequestError("Textract could not read this document format.")
    except textract.exceptions.DocumentTooLargeException:
        raise BadRequestError("Document is too large for Textract (max 10MB).")
    except Exception as e:
        app.log.error("Textract error: %s", str(e))
        raise ChaliceViewError("Failed to extract text from image.")

    # Reassemble extracted text from Textract LINE blocks
    lines = [
        block["Text"]
        for block in textract_response.get("Blocks", [])
        if block["BlockType"] == "LINE"
    ]
    extracted_text = "\n".join(lines)

    if not extracted_text.strip():
        raise BadRequestError("No text could be extracted from the provided image.")

    app.log.info("Textract extracted %d characters.", len(extracted_text))

    redacted, redaction_log = redact_text(extracted_text)

    document_id = str(uuid.uuid4())
    save_to_s3(document_id, extracted_text, redacted, source="image-textract")

    return {
        "document_id": document_id,
        "extracted_text": extracted_text,
        "redacted_text": redacted,
        "entities_found": len(redaction_log),
        "redaction_log": redaction_log,
    }


@app.route("/document/{document_id}", methods=["GET"], cors=True)
def get_document(document_id):
    """
    Retrieve a previously redacted document by its ID.
    Returns both the redacted text and the metadata.
    """
    try:
        redacted_obj = s3.get_object(
            Bucket=S3_BUCKET,
            Key=f"documents/{document_id}/redacted.txt"
        )
        meta_obj = s3.get_object(
            Bucket=S3_BUCKET,
            Key=f"documents/{document_id}/metadata.json"
        )
    except s3.exceptions.NoSuchKey:
        return Response(
            body=json.dumps({"error": "Document not found."}),
            status_code=404,
            headers=_cors_headers(),
        )
    except Exception as e:
        app.log.error("S3 retrieval error for %s: %s", document_id, str(e))
        raise ChaliceViewError("Failed to retrieve document from storage.")

    redacted_text = redacted_obj["Body"].read().decode("utf-8")
    metadata = json.loads(meta_obj["Body"].read().decode("utf-8"))

    return {
        "document_id": document_id,
        "redacted_text": redacted_text,
        "metadata": metadata,
    }
