# Sử dụng Python 3.11 Alpine làm base image để tối ưu dung lượng và loại bỏ hầu hết cảnh báo License/CVE của OS
FROM python:3.11-alpine

# Thiết lập biến môi trường hệ thống
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Thiết lập thư mục làm việc
WORKDIR /app

# Tạo non-root user và group theo chuẩn Alpine
RUN addgroup -S appgroup && adduser -S -G appgroup -s /sbin/nologin -h /app appuser

# Khởi tạo virtual environment và cấp quyền cho appuser
RUN python -m venv $VIRTUAL_ENV && \
    chown -R appuser:appgroup $VIRTUAL_ENV

# Copy file requirements trước để tận dụng Docker layer cache
COPY requirements.txt .
RUN $VIRTUAL_ENV/bin/pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" "wheel>=0.46.2" && \
    $VIRTUAL_ENV/bin/pip install --no-cache-dir -r requirements.txt && \
    # Gỡ bỏ pip, setuptools, wheel khỏi virtualenv runtime để triệt tiêu hoàn toàn license chardet (LGPL) và các CVE build-tool
    $VIRTUAL_ENV/bin/pip uninstall -y pip setuptools wheel && \
    # Dọn dẹp pip và setuptools mặc định trong base python để sạch hoàn toàn license chardet & autocommand
    rm -rf /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/bin/pip* && \
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

# Health check định kỳ trực tiếp bằng Python, loại bỏ hoàn toàn sự phụ thuộc vào gói curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"APP_PORT\", 8000)}/health')" || exit 1

# Khởi chạy dịch vụ FastAPI qua Uvicorn
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
