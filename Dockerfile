# Sử dụng Python 3.11 slim làm base image
FROM python:3.11-slim

# Thiết lập biến môi trường hệ thống
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Cài đặt các gói phụ thuộc hệ thống cần thiết (curl cho healthcheck, libglib cho xử lý tài liệu)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Tạo non-root user để tăng tính bảo mật
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Khởi tạo virtual environment và cấp quyền cho appuser
RUN python -m venv $VIRTUAL_ENV && \
    chown -R appuser:appgroup $VIRTUAL_ENV

# Copy file requirements trước để tận dụng Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    chown -R appuser:appgroup $VIRTUAL_ENV && \
    chmod -R a+rX $VIRTUAL_ENV

# Copy mã nguồn ứng dụng tường minh (tránh copy đệ quy dữ liệu nhạy cảm)
COPY --chown=appuser:appgroup core/ ./core/
COPY --chown=appuser:appgroup extractors/ ./extractors/
COPY --chown=appuser:appgroup services/ ./services/
COPY --chown=appuser:appgroup app.py launch_all.py API-trich-xuat-vbtl-hsdb-v5.md ./

# Tạo các thư mục runtime cần thiết và phân quyền cho appuser
RUN mkdir -p /app/logs /app/tmp && \
    chown -R appuser:appgroup /app && \
    chmod -R 775 /app/logs /app/tmp

# Chuyển sang non-root user
USER appuser

# Expose port dịch vụ
EXPOSE 8000

# Health check định kỳ qua endpoint /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT:-8000}/health || exit 1

# Khởi chạy dịch vụ FastAPI qua Uvicorn
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
