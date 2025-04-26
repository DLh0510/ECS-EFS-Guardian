#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import datetime
import logging
import socket
import psutil
import shutil
import uuid
from logging.handlers import RotatingFileHandler
import requests
import subprocess
from pathlib import Path
from flask import Flask, render_template, jsonify, request

# 配置日志
log_dir = os.environ.get('LOG_DIR', '/var/log/efs-check')
os.makedirs(log_dir, exist_ok=True)
logger = logging.getLogger('efs-check')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(f'{log_dir}/app.log', maxBytes=10485760, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# CloudWatch配置
try:
    import watchtower
    cloudwatch_log_group = os.environ.get('CLOUDWATCH_LOG_GROUP', '/ecs/efs-check')
    cloudwatch_handler = watchtower.CloudWatchLogHandler(log_group=cloudwatch_log_group)
    cloudwatch_handler.setFormatter(formatter)
    logger.addHandler(cloudwatch_handler)
except Exception as e:
    logger.warning(f"未能配置CloudWatch日志: {str(e)}")

# 配置应用
app = Flask(__name__)
EFS_MOUNT_PATH = os.environ.get('EFS_MOUNT_PATH', '/mnt/efs')
HEALTH_CHECK_DIR = os.environ.get('HEALTH_CHECK_DIR', os.path.join(EFS_MOUNT_PATH, 'test'))
METADATA_URL = 'http://169.254.169.254/latest/meta-data/'

def get_instance_metadata():
    """获取ECS实例元数据"""
    try:
        instance_id = requests.get(f"{METADATA_URL}instance-id", timeout=2).text
        availability_zone = requests.get(f"{METADATA_URL}placement/availability-zone", timeout=2).text
        private_ip = requests.get(f"{METADATA_URL}local-ipv4", timeout=2).text
        
        return {
            "instance_id": instance_id,
            "availability_zone": availability_zone,
            "private_ip": private_ip
        }
    except Exception as e:
        logger.error(f"获取实例元数据失败: {str(e)}")
        return {
            "instance_id": "未知",
            "availability_zone": "未知",
            "private_ip": socket.gethostbyname(socket.gethostname())
        }

def check_efs_mount():
    """检查EFS挂载状态"""
    if not os.path.exists(EFS_MOUNT_PATH):
        logger.error(f"EFS挂载点不存在: {EFS_MOUNT_PATH}")
        return {
            "is_mounted": False,
            "error": f"挂载点不存在: {EFS_MOUNT_PATH}",
            "possible_reason": "EFS可能未在任务定义中正确配置",
        }
    
    # 检查是否真的是EFS挂载
    try:
        df_output = subprocess.check_output(['df', '-h', '-T', EFS_MOUNT_PATH]).decode('utf-8')
        if 'nfs4' not in df_output and 'elasticfilesystem' not in df_output:
            logger.error(f"路径存在但可能不是EFS挂载: {EFS_MOUNT_PATH}")
            return {
                "is_mounted": False,
                "error": "路径存在但不是NFS/EFS挂载点",
                "possible_reason": "EFS挂载配置错误或挂载失败",
                "df_output": df_output
            }
        
        # 解析df输出获取空间信息
        lines = df_output.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 6:
                size = parts[2]
                used = parts[3]
                available = parts[4]
                use_percent = parts[5]
            else:
                size, used, available, use_percent = "未知", "未知", "未知", "未知"
        else:
            size, used, available, use_percent = "未知", "未知", "未知", "未知"
        
        return {
            "is_mounted": True,
            "filesystem_type": "nfs4/elasticfilesystem",
            "total_size": size,
            "used_space": used,
            "available_space": available,
            "use_percent": use_percent
        }
    except Exception as e:
        logger.error(f"检查EFS挂载状态失败: {str(e)}")
        return {
            "is_mounted": False,
            "error": f"检查挂载状态失败: {str(e)}",
            "possible_reason": "无法执行df命令或NFS客户端问题",
        }

def check_efs_permissions():
    """检查EFS权限状态"""
    if not os.path.exists(EFS_MOUNT_PATH):
        return {"error": "EFS挂载点不存在"}
    
    # 确保测试目录存在
    try:
        os.makedirs(HEALTH_CHECK_DIR, exist_ok=True)
    except Exception as e:
        return {
            "read": False,
            "write": False,
            "error": f"无法创建测试目录: {str(e)}",
            "possible_reason": "EFS挂载点只读或权限不足"
        }
    
    # 测试写入权限
    test_file = os.path.join(HEALTH_CHECK_DIR, "healthcheck.txt")
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_content = f"EFS健康检查 - {current_time} - {uuid.uuid4()}"
        
        with open(test_file, 'w') as f:
            f.write(test_content)
            
        # 验证写入内容
        with open(test_file, 'r') as f:
            read_content = f.read()
            
        return {
            "read": True,
            "write": True,
            "test_file": test_file,
            "content": read_content,
            "match": read_content == test_content
        }
    except Exception as e:
        logger.error(f"EFS权限测试失败: {str(e)}")
        return {
            "read": os.access(EFS_MOUNT_PATH, os.R_OK),
            "write": False,
            "error": f"写入/读取测试失败: {str(e)}",
            "possible_reason": "EFS挂载权限配置错误或网络问题"
        }

def list_efs_files():
    """列出EFS目录文件"""
    try:
        if not os.path.exists(HEALTH_CHECK_DIR):
            return {"error": f"目录不存在: {HEALTH_CHECK_DIR}"}
        
        files = []
        for item in os.listdir(HEALTH_CHECK_DIR):
            item_path = os.path.join(HEALTH_CHECK_DIR, item)
            stats = os.stat(item_path)
            file_info = {
                "name": item,
                "path": item_path,
                "size": stats.st_size,
                "created": datetime.datetime.fromtimestamp(stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "modified": datetime.datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "is_dir": os.path.isdir(item_path)
            }
            files.append(file_info)
            
        return {"files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"列出EFS文件失败: {str(e)}")
        return {"error": f"列出文件失败: {str(e)}"}

def diagnose_mount_issues():
    """诊断常见的EFS挂载问题"""
    issues = []
    
    # 检查网络连接
    try:
        efs_dns = os.environ.get('EFS_DNS', 'fs-xxxxxx.efs.region.amazonaws.com')
        result = subprocess.run(['ping', '-c', '1', efs_dns], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, 
                               timeout=5)
        if result.returncode != 0:
            issues.append({
                "type": "network",
                "detail": "无法连接到EFS DNS端点",
                "possible_fix": "检查安全组是否允许NFS流量(TCP 2049)以及网络ACL配置"
            })
    except Exception as e:
        issues.append({
            "type": "network",
            "detail": f"网络诊断失败: {str(e)}",
            "possible_fix": "检查网络配置和DNS解析"
        })
    
    # 检查NFS客户端
    try:
        result = subprocess.run(['showmount', '--version'], 
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        if result.returncode != 0:
            issues.append({
                "type": "nfs_client",
                "detail": "NFS客户端可能未安装",
                "possible_fix": "在容器中安装NFS客户端: apt-get install nfs-common"
            })
    except Exception:
        issues.append({
            "type": "nfs_client",
            "detail": "NFS客户端命令不可用",
            "possible_fix": "确保容器包含NFS客户端工具"
        })
    
    # 检查权限
    if not os.access(EFS_MOUNT_PATH, os.W_OK):
        issues.append({
            "type": "permissions",
            "detail": "EFS挂载点无写入权限",
            "possible_fix": "检查EFS文件系统权限和挂载选项"
        })
    
    return issues

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/status')
def status():
    """返回EFS和实例状态的API端点"""
    instance_data = get_instance_metadata()
    mount_status = check_efs_mount()
    
    # 只有当挂载成功时，才检查权限和文件列表
    if mount_status.get("is_mounted", False):
        perm_status = check_efs_permissions()
        files_status = list_efs_files()
        issues = []
    else:
        perm_status = {"error": "EFS未挂载，无法检查权限"}
        files_status = {"error": "EFS未挂载，无法列出文件"}
        issues = diagnose_mount_issues()
    
    result = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instance": instance_data,
        "mount": mount_status,
        "permissions": perm_status,
        "files": files_status,
        "issues": issues if 'issues' in locals() else []
    }
    
    # 记录结果
    if not mount_status.get("is_mounted", False) or 'error' in perm_status:
        logger.error(f"EFS检查失败: {json.dumps(result)}")
    else:
        logger.info(f"EFS检查成功: {json.dumps({'instance': instance_data})}")
    
    return jsonify(result)

@app.route('/api/refresh', methods=['POST'])
def refresh():
    """强制刷新状态检查"""
    logger.info("手动触发EFS检查")
    return status()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'False').lower() == 'true') 