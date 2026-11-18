FROM python:3.13.11-alpine3.23

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup -S app && adduser -S -G app -u 10001 app
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt
COPY --chown=app:app . ./reference_apps/

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "reference_apps.app:create_app_from_environment", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
