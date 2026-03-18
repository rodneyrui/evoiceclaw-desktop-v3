# ──────────────────────────────────────────────
# Stage 1: Build frontend
# ──────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --frozen-lockfile

COPY frontend/ ./
RUN npm run build
# Output: /app/frontend/dist/


# ──────────────────────────────────────────────
# Stage 2: Production backend image
# ──────────────────────────────────────────────
FROM python:3.12-slim AS backend

# System dependencies for lancedb (requires libc++ / libstdc++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy compile script first (for Cython build)
COPY deploy/compile_rules.py /tmp/compile_rules.py

# Copy application source
COPY backend/ .

# Cython 编译 rules/ 源码为二进制（IP 保护）
RUN pip install --no-cache-dir cython setuptools \
    && python /tmp/compile_rules.py --clean --verify \
    && pip uninstall -y cython \
    && rm -f /tmp/compile_rules.py \
    && rm -rf build/ *.egg-info

# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist/ ./frontend_dist/

# Create data directories (volumes will overlay these at runtime)
RUN mkdir -p data/lancedb data/skills data/preset

# Non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 28772

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:28772/api/v1/system/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "28772"]
