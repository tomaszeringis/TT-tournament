FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and install Python dependencies
COPY pyproject.toml ./pyproject.toml
COPY tournament_platform/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .

# Copy application code
COPY tournament_platform/ ./tournament_platform/
COPY tests/ ./tests/
COPY streamlit_app.py ./streamlit_app.py

# Create data directory (must match DATABASE_URL path)
RUN mkdir -p /app/data /app/tournament_platform/data

# Expose ports
EXPOSE 8501 8000

# Run database migrations
RUN python -m alembic -c tournament_platform/alembic.ini upgrade head

# Default command: Streamlit frontend (root entrypoint)
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
