FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000 \
    APP_ENV=production

WORKDIR /app

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p instance/uploads

EXPOSE 3000

CMD ["sh", "-c", "python -m flask --app run:app db upgrade && exec gunicorn --workers 2 --bind 0.0.0.0:${PORT:-3000} --access-logfile - --error-logfile - run:app"]