FROM nginxinc/nginx-unprivileged:1.29.5-alpine3.23

ENV NGINX_ENVSUBST_FILTER=API_UPSTREAM

COPY --chown=101:101 index.html app-v2.js styles.css /usr/share/nginx/html/
COPY --chown=101:101 default.conf.template /etc/nginx/templates/default.conf.template

USER 101:101
EXPOSE 8080
