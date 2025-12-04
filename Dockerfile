# Use Python 3.11-slim as the base image for minimal size
FROM python:3.11-slim

# Create a non-root user for security (UID 1000 is common)
RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup

# Set the working directory for the application
WORKDIR /app

# Copy requirements file from the build context
COPY requirements.txt .

# Install dependencies (Run as ROOT)
# This installs packages globally to /usr/local/lib/python3.11/site-packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
# Use --chown to ensure the appuser owns the application files
COPY --chown=appuser:appgroup . .

# Cloud Run defaults to Port 8080. We must match it.
ENV PORT=8000
EXPOSE 8000

# Switch to non-root user for runtime security
USER appuser

# Start Uvicorn on the exposed port
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]