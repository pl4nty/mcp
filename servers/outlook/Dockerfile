FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src/ src/

# Install dependencies and the package
RUN uv pip install --system --no-cache -e .

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "-m", "outlook_mcp.server"]
