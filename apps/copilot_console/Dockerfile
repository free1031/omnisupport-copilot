FROM nginx:1.27-alpine

COPY apps/copilot_console/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/copilot_console/index.html /usr/share/nginx/html/index.html
COPY apps/copilot_console/styles.css /usr/share/nginx/html/styles.css
COPY apps/copilot_console/app.js /usr/share/nginx/html/app.js

EXPOSE 80
