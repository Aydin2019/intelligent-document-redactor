#!/bin/bash
# setup.sh — Bootstrap and run the Intelligent Document Redactor locally
# Run this from the project root: bash setup.sh

set -e

echo "=== Intelligent Document Redactor — Setup ==="

# 1. Check Python
python3 --version || { echo "Python 3 is required."; exit 1; }

# 2. Create and activate a virtual environment
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "Virtual environment active."

# 3. Install dependencies
echo "Installing dependencies..."
pip install --quiet -r requirements.txt

# 4. Verify AWS credentials
echo "Checking AWS credentials..."
python3 -c "import boto3; boto3.client('sts').get_caller_identity()" \
  && echo "AWS credentials OK." \
  || { echo "AWS credentials not configured. Run: aws configure"; exit 1; }

# 5. Create S3 bucket if it doesn't exist
BUCKET="intelligent-redactor-docs"
REGION="us-east-1"

echo "Ensuring S3 bucket '$BUCKET' exists..."
aws s3 mb "s3://$BUCKET" --region "$REGION" 2>/dev/null && echo "Bucket created." \
  || echo "Bucket already exists (or creation skipped)."

# 6. Start Chalice local server
echo ""
echo "Starting Chalice local server on http://localhost:8000 ..."
echo "Open frontend/index.html in your browser to use the app."
echo "Press Ctrl+C to stop."
echo ""
chalice local --port 8000
