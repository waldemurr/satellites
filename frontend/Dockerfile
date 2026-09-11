FROM nginx:alpine

# Копируем статику и шаблоны
COPY templates/ /usr/share/nginx/html/
COPY static/ /usr/share/nginx/html/static/

# Свой конфиг nginx (см. ниже)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000