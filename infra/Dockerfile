# One image: builds the console, then serves API + console from one process.
# Build from the repo root: docker build -f infra/Dockerfile -t warrant .
FROM node:22-slim AS console
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src backend/src
COPY backend/tests/fixtures backend/tests/fixtures
COPY data data
RUN pip install --no-cache-dir -e ./backend
COPY --from=console /app/frontend/dist frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn warrant.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
