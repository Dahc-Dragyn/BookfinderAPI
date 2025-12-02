# Use Python 3.11-slim as the base image for minimal size
FROM python:3.11-slim

# Create and switch to a non-root user for security (UID 1000 is common)
# This prevents the container from running as root by default.
RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup
USER appuser

# Set the working directory for the application
WORKDIR /app

# Copy requirements file from the build context
# Note: The effective user is now 'appuser'
COPY requirements.txt .

# Install dependencies
# Using --no-cache-dir saves space and keeping upgrade pip first is generally better
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
# The .dockerignore file ensures that .env, test scripts, and dev files are excluded here.
COPY . .

# Cloud Run defaults to Port 8080. We must match it.
ENV PORT=8080
EXPOSE 8080

# Start Uvicorn on the exposed port
# Use the unbuffered version of uvicorn for better logging capture
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--forwarded-allow-ips", "*"]