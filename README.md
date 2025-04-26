# ECS-EFS连通性检测Web服务

这是一个轻量级Web应用，用于验证ECS任务是否成功挂载EFS文件系统，并展示关键状态信息。

## 功能特点

* 显示ECS实例元数据（实例ID、可用区、私有IP）
* 检测EFS挂载状态（是否成功挂载指定路径）
* 显示EFS挂载点剩余空间及读写权限状态
* 列出EFS指定目录下的文件列表
* 自动向EFS写入测试文件，验证读写权限
* 支持手动触发重新检测
* 若EFS挂载失败，显示红色告警及常见错误原因
* 记录错误日志至CloudWatch Logs

## 技术栈

* 后端：Python + Flask
* 前端：HTML + Bootstrap + JavaScript
* 容器化：Docker
* 部署：ECS Fargate

## 快速启动

### 本地开发环境

1. 复制环境变量示例文件并根据需要修改：

```bash
cp .env.example .env.local
```

2. 使用Docker Compose启动应用：

```bash
docker-compose up
```

3. 在浏览器中访问：http://localhost:5000

### 生产环境部署

1. 构建Docker镜像：

```bash
docker build -t efs-check .
```

2. 将镜像推送到ECR：

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
docker tag efs-check:latest <account-id>.dkr.ecr.<region>.amazonaws.com/efs-check:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/efs-check:latest
```

3. 在ECS Fargate中创建任务定义，确保：
   - 任务定义中包含EFS卷挂载
   - 设置必要的环境变量
   - 配置ALB和目标组

## 环境变量配置

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| EFS_MOUNT_PATH | EFS挂载路径 | /mnt/efs |
| HEALTH_CHECK_DIR | 健康检查目录路径 | /mnt/efs/test |
| EFS_DNS | EFS DNS端点（用于诊断） | - |
| LOG_DIR | 日志目录 | /var/log/efs-check |
| CLOUDWATCH_LOG_GROUP | CloudWatch日志组 | /ecs/efs-check |
| PORT | 应用端口 | 5000 |
| DEBUG | 调试模式 | False |

## ECS任务定义示例

下面是一个示例的ECS任务定义片段（JSON格式），展示了如何配置EFS卷挂载：

```json
{
  "family": "efs-check",
  "executionRoleArn": "arn:aws:iam::account-id:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::account-id:role/ecsTaskRole",
  "networkMode": "awsvpc",
  "containerDefinitions": [
    {
      "name": "efs-check",
      "image": "account-id.dkr.ecr.region.amazonaws.com/efs-check:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 5000,
          "hostPort": 5000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "EFS_MOUNT_PATH",
          "value": "/mnt/efs"
        },
        {
          "name": "HEALTH_CHECK_DIR",
          "value": "/mnt/efs/test"
        },
        {
          "name": "EFS_DNS",
          "value": "fs-xxxxxx.efs.region.amazonaws.com"
        }
      ],
      "mountPoints": [
        {
          "sourceVolume": "efs-volume",
          "containerPath": "/mnt/efs",
          "readOnly": false
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/efs-check",
          "awslogs-region": "region",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ],
  "volumes": [
    {
      "name": "efs-volume",
      "efsVolumeConfiguration": {
        "fileSystemId": "fs-xxxxxx",
        "rootDirectory": "/",
        "transitEncryption": "ENABLED",
        "authorizationConfig": {
          "iam": "ENABLED"
        }
      }
    }
  ],
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512"
}
```

## 常见问题排查

### EFS挂载失败

可能的原因：
1. 安全组未正确配置（需开放TCP 2049端口）
2. EFS和ECS任务不在同一VPC或安全组不兼容
3. EFS文件系统ID配置错误
4. IAM权限不足

### 无法写入EFS

可能的原因：
1. EFS挂载选项设置为只读
2. EFS文件系统策略限制了写入操作
3. 根目录权限设置问题

## 日志和监控

应用日志存储路径：
- 容器内部：`/var/log/efs-check/app.log`
- CloudWatch日志组：`/ecs/efs-check`

建议配置CloudWatch警报，监控EFS挂载失败事件。 