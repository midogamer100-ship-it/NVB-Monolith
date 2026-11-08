# syntax=docker/dockerfile:1
# Nova Valley Bank (NVB) demo - single deployable image (API + built frontend).
# Synthetic data only. Build:  podman build -t nvb-app:1.0.0 -f Containerfile .
#
# Stage 1: build the React frontend into static assets.
FROM registry.access.redhat.com/ubi9/nodejs-22 AS frontend
USER 1001
WORKDIR /opt/app-root/src/frontend
COPY --chown=1001:0 frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --chown=1001:0 frontend/ ./
RUN npm run build

# Stage 2: build a self-contained Python virtual environment.
FROM registry.access.redhat.com/ubi9/python-312 AS pydeps
USER 1001
WORKDIR /opt/app-root/build
COPY --chown=1001:0 backend/requirements.txt ./
RUN python3.12 -m venv /opt/app-root/nvb-venv \
 && /opt/app-root/nvb-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/app-root/nvb-venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 3: runtime image. Only the venv, backend code and static assets.
FROM registry.access.redhat.com/ubi9/python-312

LABEL name="nvb-app" \
      summary="Nova Valley Bank modernization demo (synthetic data only)" \
      io.openshift.expose-services="8080:http"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/app-root/nvb-venv/bin:$PATH \
    WEB_CONCURRENCY=1 \
    FORWARDED_ALLOW_IPS=* \
    NVB_STATIC_DIR=/opt/nvb/backend/app/static \
    HOME=/tmp \
    TMPDIR=/tmp

USER 0
COPY --from=pydeps --chown=1001:0 /opt/app-root/nvb-venv /opt/app-root/nvb-venv
COPY --chown=1001:0 backend/app /opt/nvb/backend/app
COPY --chown=1001:0 backend/alembic /opt/nvb/backend/alembic
COPY --chown=1001:0 backend/alembic.ini /opt/nvb/backend/alembic.ini
COPY --from=frontend --chown=1001:0 /opt/app-root/src/frontend/dist /opt/nvb/backend/app/static
# OpenShift runs the container with an arbitrary UID that belongs to group 0.
# Give group 0 the same (read-only) permissions as the owner; nothing in the
# image needs to be writable at runtime - /tmp is an emptyDir/tmpfs.
RUN chmod -R g=u /opt/nvb /opt/app-root/nvb-venv \
 && find /opt/nvb -type f -exec chmod a-w {} + \
 && find /opt/app-root/nvb-venv -type f -exec chmod a-w {} +

USER 1001
WORKDIR /opt/nvb/backend
EXPOSE 8080

# FORWARDED_ALLOW_IPS=* is acceptable only because the pod is reachable solely
# through the OpenShift router (enforced by NetworkPolicy). Override if needed.
CMD ["sh", "-c", "exec uvicorn --factory app.main:app_factory --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS}\" --workers \"${WEB_CONCURRENCY}\" --no-server-header"]
