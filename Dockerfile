# 1. Base Image
FROM python:3.11-slim

# 2. Security: Create the TrueNAS 'apps' user (UID 568)
# This prevents permission issues when writing to your TrueNAS datasets
RUN groupadd -g 568 appgroup && \
    useradd -u 568 -g 568 --system --create-home appuser

# 3. Environment: Set standard Python defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 4. Dependencies: Install before code to leverage layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Code: Copy the 'app' directory into the container
# We use --chown to ensure appuser can read the code
COPY --chown=appuser:appgroup app/ ./app/

# 6. User: Switch away from root
USER appuser

# 7. Execution: Run FastAPI using uvicorn
# We use 0.0.0.0 so it's accessible outside the container
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
