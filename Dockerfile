FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home bizmatic
COPY requirements.txt requirements.docker.txt /tmp/requirements/
RUN python -m pip install --no-cache-dir -r /tmp/requirements/requirements.docker.txt \
    && python -m pip check
COPY bizmatic_django/ /app/
COPY deploy/ /app/deploy/
RUN mkdir -p /var/lib/bizmatic/uploads /var/lib/bizmatic/keys /app/staticfiles \
    && chown -R bizmatic:bizmatic /var/lib/bizmatic /app/staticfiles
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
CMD ["gunicorn", "--config", "/app/deploy/gunicorn.conf.py", "bizmatic_django.wsgi:application"]
