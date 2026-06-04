FROM python:3.11-slim

WORKDIR /app

# Install curl and unzip for downloading CMS data
RUN apt-get update && apt-get install -y curl unzip && \
    mkdir -p /app/data && \
    # Download ICD-10-CM 2026 from CMS
    curl -fLo icd10cm.zip "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip" && \
    # Download ICD-10-PCS 2026 from CMS
    curl -fLo icd10pcs.zip "https://www.cms.gov/files/zip/2026-icd-10-pcs-codes-file.zip" && \
    # Extract files
    unzip icd10cm.zip -d /app/data/icd10cm && \
    unzip icd10pcs.zip -d /app/data/icd10pcs && \
    # Cleanup
    rm *.zip && \
    apt-get remove -y curl unzip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Set data directory environment variable
ENV ICD10_DATA_DIR=/app/data

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["python", "server.py"]
