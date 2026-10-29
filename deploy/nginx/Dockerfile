FROM nginx/nginx-unprivileged:stable-alpine
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 15-bizmatic-settings.envsh /docker-entrypoint.d/15-bizmatic-settings.envsh
