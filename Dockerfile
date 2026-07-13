FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml .
COPY requirements.txt ./requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY tournament_platform/ ./tournament_platform/
COPY tests/ ./tests/

# Create data directory
RUN mkdir -p /app/data

# Expose ports
EXPOSE 8501 8000

# Run database migrations
RUN python -m alembic upgrade head

# Default command
CMD ["streamlit", "run", "tournament_platform/app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
