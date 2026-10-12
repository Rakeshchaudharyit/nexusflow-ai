FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY apps/mcp-demo/requirements.lock ./
RUN pip install -r requirements.lock && useradd --create-home --uid 10001 appuser
COPY apps/mcp-demo/nexusflow_mcp_demo ./nexusflow_mcp_demo
USER appuser
EXPOSE 8765
CMD ["python", "-m", "nexusflow_mcp_demo"]
