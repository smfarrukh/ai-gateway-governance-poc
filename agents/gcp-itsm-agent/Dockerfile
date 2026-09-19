# Runs the ADK agent with its built-in web chat UI, for deploying from the
# Cloud Run console (source build) instead of the "adk deploy cloud_run" command.
FROM python:3.12-slim
WORKDIR /app
COPY itsm_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/
ENV PORT=8080
# /app holds the itsm_agent folder, which is what "adk web" expects.
CMD ["sh", "-c", "adk web --host 0.0.0.0 --port ${PORT} /app"]
