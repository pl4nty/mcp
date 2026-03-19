FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml main.py ./
COPY tools/ tools/

RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -e .

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
