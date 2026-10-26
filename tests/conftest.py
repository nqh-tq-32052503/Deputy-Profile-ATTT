import os

# Thiết lập API_KEY mặc định cho môi trường chạy test (nếu chưa có trong .env)
os.environ.setdefault("API_KEY", "test-secret-api-key-hsdb")
