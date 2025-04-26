FROM python:3.11-slim

# 安装NFS客户端和其他必要工具
RUN apt-get update && \
    apt-get install -y nfs-common procps net-tools iputils-ping dnsutils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 创建应用目录
WORKDIR /app

# 设置Python环境
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p /var/log/efs-check && \
    chmod 777 /var/log/efs-check

# 设置启动命令
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", "--access-logfile", "-", "--error-logfile", "-"] 