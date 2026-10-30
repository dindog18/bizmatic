FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.docker.txt /tmp/requirements/
RUN python -m pip install --no-cache-dir -r /tmp/requirements/requirements.docker.txt \
    && python -m pip check
ARG APP_UID=10001
ARG APP_GID=10001
RUN (getent group "$APP_GID" || groupadd --gid "$APP_GID" bizmatic) \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home bizmatic
COPY bizmatic_django/ /app/
COPY deploy/ /app/deploy/
RUN mkdir -p /var/lib/bizmatic/uploads /var/lib/bizmatic/keys /app/staticfiles \
    && chown -R "$APP_UID:$APP_GID" /var/lib/bizmatic /app/staticfiles
USER ${APP_UID}:${APP_GID}
EXPOSE 8000
ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
CMD ["gunicorn", "--config", "/app/deploy/gunicorn.conf.py", "bizmatic_django.wsgi:application"]
