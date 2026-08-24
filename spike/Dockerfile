FROM python:3.12-slim-bookworm

WORKDIR /app

COPY spike/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Do not COPY .env; lib.env loads it with override=True and would wipe process env.
COPY lib /app/lib
COPY skills /app/skills
COPY config /app/config
COPY spike /app/spike

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV REPO_PATH=/app
ENV LOCAL_STORAGE_PATH=/tmp/sictic-storage
ENV LOCAL_DATA_PATH=/tmp/sictic-data
ENV DOCUMENT_PARSER=llamaparse  # pragma: allowlist secret
ENV VECTOR_STORE=firestore  # pragma: allowlist secret

EXPOSE 8080
CMD ["python", "-m", "spike.web"]
