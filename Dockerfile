# Use Python 3.12 slim for a small footprint
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install UV for fast package management
RUN pip install uv

# Copy requirements and install dependencies system-wide
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy all your code (main.py, fiction.py, non_fiction.py, .env)
COPY . .

# Expose the port
EXPOSE 8000

# Command to run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]