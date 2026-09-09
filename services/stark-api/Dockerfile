FROM python:3.12-slim
WORKDIR /app
COPY services/stark-api/runtime.py /app/runtime.py
ENV PYTHONUNBUFFERED=1 STARK_V2_PORT=8080
EXPOSE 8080
CMD ["python3","/app/runtime.py"]
