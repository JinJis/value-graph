# Evidence renderer (PH-PROV2). The Playwright base ships Chromium + OS deps preinstalled;
# the heavy headless-browser dependency is isolated to THIS service only.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    RENDER_CACHE_DIR=/cache

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" "playwright==1.47.0" \
    && playwright install chromium

COPY app ./app
RUN mkdir -p /cache

EXPOSE 8006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
