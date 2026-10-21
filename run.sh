#!/bin/bash

# Kích hoạt môi trường Conda surya nếu có
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate surya
fi

# Chạy Uvicorn server
uvicorn app:app --host 0.0.0.0 --port 8091 --reload --reload-include "*.env"