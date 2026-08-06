FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/api

# The settings resolve relative paths against the repository root, which only
# exists in a source checkout. Inside the image the code sits at /srv/api, so
# these are pinned absolutely and the compose mounts must match them.
ENV SCENARIOS_PATH=/srv/scenarios \
    DATAHUB_FIXTURE_PATH=/srv/datahub/seed/showcase-ecommerce-demo.json \
    DATAHUB_MEMORY_STORE_PATH=/srv/state/datahub-fixture-memory.json

RUN mkdir -p /srv/state

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
