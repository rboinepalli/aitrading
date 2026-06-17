# =============================================================================
# Dockerfile for the Python trading bot
# Deployed as a Railway "worker" service (no web port needed).
# =============================================================================

# python:3.12-slim = official Python image, minimal size (~130MB vs ~1GB full)
# The "slim" variant strips out build tools and docs — saves space in production.
FROM python:3.12-slim

# Set the working directory inside the container.
# All subsequent COPY/RUN commands operate relative to this path.
WORKDIR /app

# Copy requirements first — Docker caches this layer.
# If only your code changes (not requirements), Docker reuses the pip install
# layer from cache, making builds much faster. This is a standard Docker pattern.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the application code.
# (Copying code after pip install means code changes don't invalidate the cache layer above.)
COPY . .

# Railway sets environment variables via its dashboard — we don't hardcode secrets here.
# The CMD runs `python main.py` when the container starts.
CMD ["python", "main.py"]
