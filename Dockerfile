FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    curl \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Set up user for Hugging Face Spaces
RUN useradd -m -u 1000 user
RUN chown -R user:user /app

# Python dependencies
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=user:user gymble_api/ ./gymble_api/
COPY --chown=user:user Chatbotv2/ ./Chatbotv2/

# Data download & startup scripts
COPY --chown=user:user download_data.py .
COPY --chown=user:user entrypoint.sh .
COPY --chown=user:user run_combined.py .
RUN chmod +x /app/entrypoint.sh

# Directories
RUN mkdir -p /app/chroma_db /app/Chatbotv2/Datasets && chown -R user:user /app/chroma_db /app/Chatbotv2/Datasets

USER user

# Default port (Hugging Face Spaces exposes 7860)
ENV PORT=7860

EXPOSE ${PORT}

CMD ["/app/entrypoint.sh"]
