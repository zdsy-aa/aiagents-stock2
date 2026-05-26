# 🐳 Docker部署指南

## 📋 概述

使用Docker部署TDX股票数据查询系统，无需配置Go环境，一键启动！

---

## 🎯 优势

✅ **无需Go环境** - Docker容器内置所有依赖  
✅ **一键部署** - 简单的命令即可启动  
✅ **环境隔离** - 不影响主机系统  
✅ **跨平台** - Windows/Linux/Mac统一方案  
✅ **易于管理** - 启动/停止/重启非常方便  

---

## 📦 前置要求

### 安装Docker

#### Windows系统

**方法一：Docker Desktop（推荐）**

1. 下载Docker Desktop
   - 官网：https://www.docker.com/products/docker-desktop/
   - 选择Windows版本下载

2. 运行安装程序
   - 双击安装包
   - 按向导完成安装
   - 重启电脑

3. 启动Docker Desktop
   - 双击桌面图标
   - 等待Docker启动完成（状态显示为绿色）

4. 验证安装
   ```powershell
   docker --version
   docker-compose --version
   ```

**方法二：手动安装Docker Engine**

适用于Windows Server或不使用Docker Desktop的场景。

#### Linux系统

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# CentOS/RHEL
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker

# 添加当前用户到docker组
sudo usermod -aG docker $USER

# 验证安装
docker --version
docker-compose --version
```

#### Mac系统

1. 下载Docker Desktop for Mac
2. 安装.dmg文件
3. 启动Docker
4. 验证安装

---

## 🚀 快速开始

### 方式一：使用docker-compose（推荐）

#### 1. 进入项目目录
```powershell
cd C:\Users\Administrator\Downloads\tdx-master
```

#### 2. 构建并启动
```powershell
docker-compose up -d
```

这个命令会：
- 📦 自动构建Docker镜像
- 🚀 启动容器
- 🔌 映射端口到本机8080

#### 3. 查看日志
```powershell
# 查看实时日志
docker-compose logs -f

# 看到以下信息表示启动成功：
# 成功连接到通达信服务器
# 服务启动成功，访问 http://localhost:8080
```

#### 4. 访问应用
打开浏览器访问：http://localhost:8080

#### 5. 停止服务
```powershell
docker-compose down
```

---

### 方式二：使用docker命令

#### 1. 构建镜像
```powershell
docker build -t tdx-stock-web:latest .
```

#### 2. 运行容器
```powershell
docker run -d \
  --name tdx-stock-web \
  -p 8080:8080 \
  --restart unless-stopped \
  tdx-stock-web:latest
```

#### 3. 查看日志
```powershell
docker logs -f tdx-stock-web
```

#### 4. 停止容器
```powershell
docker stop tdx-stock-web
docker rm tdx-stock-web
```

---

## 📝 常用命令

### 容器管理

```powershell
# 查看运行中的容器
docker ps

# 查看所有容器（包括停止的）
docker ps -a

# 启动容器
docker-compose start

# 停止容器
docker-compose stop

# 重启容器
docker-compose restart

# 删除容器和网络
docker-compose down

# 删除容器、网络和镜像
docker-compose down --rmi all
```

### 日志查看

```powershell
# 查看最近100行日志
docker-compose logs --tail=100

# 实时查看日志
docker-compose logs -f

# 查看特定时间的日志
docker-compose logs --since="2024-11-03T14:00:00"

# 只查看错误日志
docker-compose logs | findstr "error"
```

### 进入容器

```powershell
# 进入容器shell
docker exec -it tdx-stock-web sh

# 执行命令
docker exec tdx-stock-web ls -la

# 查看容器内环境变量
docker exec tdx-stock-web env
```

### 镜像管理

```powershell
# 查看镜像列表
docker images

# 删除镜像
docker rmi tdx-stock-web:latest

# 清理未使用的镜像
docker image prune

# 查看镜像详细信息
docker inspect tdx-stock-web:latest
```

---

## ⚙️ 配置说明

### docker-compose.yml 配置项

```yaml
services:
  stock-web:
    build:
      context: .              # 构建上下文
      dockerfile: Dockerfile  # Dockerfile路径
    
    container_name: tdx-stock-web  # 容器名称
    
    ports:
      - "8080:8080"          # 端口映射 主机:容器
    
    restart: unless-stopped   # 重启策略
    
    environment:
      - TZ=Asia/Shanghai     # 时区设置
    
    networks:
      - stock-network        # 网络配置
```

### 修改端口

如果8080端口被占用，修改`docker-compose.yml`：

```yaml
ports:
  - "9090:8080"  # 将主机端口改为9090
```

然后访问：http://localhost:9090

### 环境变量

可以在`docker-compose.yml`中添加环境变量：

```yaml
environment:
  - TZ=Asia/Shanghai
  - DEBUG=true
  - LOG_LEVEL=info
```

---

## 🔍 故障排查

### 问题1：Docker命令不可用

**症状**：
```
docker : 无法将"docker"项识别为 cmdlet、函数、脚本文件或可运行程序的名称
```

**解决方案**：
1. 确认Docker Desktop已安装并启动
2. 查看系统托盘是否有Docker图标
3. 重启Docker Desktop
4. 重启PowerShell终端

### 问题2：构建失败 - 网络问题

**症状**：
```
ERROR: failed to solve: golang:1.21-alpine: error getting credentials
```

**解决方案**：
```powershell
# 配置Docker镜像加速（国内）
# 在Docker Desktop设置中添加：
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://registry.docker-cn.com"
  ]
}
```

### 问题3：端口被占用

**症状**：
```
Error starting userland proxy: listen tcp4 0.0.0.0:8080: bind: Only one usage...
```

**解决方案**：
```powershell
# 方法1：停止占用端口的程序
netstat -ano | findstr :8080
taskkill /PID <进程ID> /F

# 方法2：修改docker-compose.yml中的端口映射
ports:
  - "9090:8080"
```

### 问题4：容器启动后立即退出

**症状**：
```
docker ps -a  # 显示Exited状态
```

**解决方案**：
```powershell
# 查看容器日志
docker logs tdx-stock-web

# 查看详细错误信息
docker-compose logs
```

### 问题5：无法访问网页

**症状**：浏览器无法打开 http://localhost:8080

**排查步骤**：
```powershell
# 1. 确认容器正在运行
docker ps

# 2. 检查端口映射
docker port tdx-stock-web

# 3. 查看容器日志
docker logs tdx-stock-web

# 4. 测试容器内部服务
docker exec tdx-stock-web wget -O- http://localhost:8080

# 5. 检查防火墙设置
# Windows防火墙 → 允许应用通过防火墙 → Docker
```

### 问题6：构建速度慢

**解决方案**：

1. **使用镜像加速**（已在Dockerfile中配置）
   ```dockerfile
   ENV GOPROXY=https://goproxy.cn,direct
   ```

2. **使用构建缓存**
   ```powershell
   # Docker会自动缓存构建层
   # 第二次构建会快很多
   ```

3. **多阶段构建优化**（已实现）
   ```dockerfile
   # 第一阶段：构建（包含完整Go环境）
   # 第二阶段：运行（只包含二进制文件）
   # 最终镜像大小：约20MB
   ```

---

## 📊 监控和维护

### 查看容器状态

```powershell
# 查看容器资源使用
docker stats tdx-stock-web

# 查看容器详细信息
docker inspect tdx-stock-web

# 查看容器进程
docker top tdx-stock-web
```

### 健康检查

容器配置了自动健康检查：

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/"]
  interval: 30s      # 每30秒检查一次
  timeout: 3s        # 超时时间3秒
  retries: 3         # 失败3次后标记为unhealthy
  start_period: 5s   # 启动后5秒开始检查
```

查看健康状态：
```powershell
docker ps  # 查看HEALTH列
```

### 备份和恢复

```powershell
# 导出容器为镜像
docker commit tdx-stock-web tdx-stock-web-backup:v1.0

# 保存镜像到文件
docker save -o tdx-stock-web-backup.tar tdx-stock-web:latest

# 从文件加载镜像
docker load -i tdx-stock-web-backup.tar
```

---

## 🔄 更新和升级

### 更新应用

```powershell
# 1. 停止并删除旧容器
docker-compose down

# 2. 拉取最新代码
git pull  # 如果使用Git

# 3. 重新构建并启动
docker-compose up -d --build

# 4. 查看日志确认启动成功
docker-compose logs -f
```

### 版本管理

```powershell
# 构建带版本标签的镜像
docker build -t tdx-stock-web:v1.0.0 .

# 使用特定版本
docker run -d \
  --name tdx-stock-web \
  -p 8080:8080 \
  tdx-stock-web:v1.0.0
```

---

## 🌐 生产环境部署

### 使用环境变量文件

创建 `.env` 文件：
```bash
# .env
TZ=Asia/Shanghai
PORT=8080
LOG_LEVEL=info
```

修改 `docker-compose.yml`：
```yaml
services:
  stock-web:
    env_file:
      - .env
    ports:
      - "${PORT}:8080"
```

### 数据持久化（如需要）

```yaml
services:
  stock-web:
    volumes:
      - ./data:/app/data      # 数据目录
      - ./logs:/app/logs      # 日志目录
```

### 反向代理（Nginx）

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - stock-web
    networks:
      - stock-network
```

---

## 📈 性能优化

### 1. 镜像优化

✅ 已实现多阶段构建  
✅ 使用Alpine Linux（体积小）  
✅ 编译时使用 `-ldflags="-s -w"` 减小二进制文件  

最终镜像大小：**约20MB**

### 2. 资源限制

```yaml
services:
  stock-web:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

### 3. 容器优化

```yaml
services:
  stock-web:
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
```

---

## ✅ 完整部署检查清单

部署前检查：
- [ ] Docker已安装并启动
- [ ] 8080端口未被占用
- [ ] 网络连接正常
- [ ] 有足够的磁盘空间（至少500MB）

部署步骤：
- [ ] 进入项目目录
- [ ] 运行 `docker-compose up -d`
- [ ] 查看日志确认启动
- [ ] 浏览器访问测试

验证成功：
- [ ] 容器状态为 `Up`
- [ ] 健康检查显示 `healthy`
- [ ] 可以访问 http://localhost:8080
- [ ] 能够搜索和查看股票数据

---

## 🎉 快速命令参考

```powershell
# 一键启动
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose stop

# 完全清理
docker-compose down

# 重新构建
docker-compose up -d --build
```

---

## 📞 获取帮助

### 常用诊断命令

```powershell
# Docker版本信息
docker version
docker-compose version

# Docker系统信息
docker info

# 查看Docker磁盘使用
docker system df

# 清理系统
docker system prune -a
```

### 下一步

Docker部署成功后，您可以：

1. ✅ 访问 http://localhost:8080 使用应用
2. ✅ 查看 `web/DEMO.md` 了解功能
3. ✅ 查看 `web/USAGE.md` 学习使用技巧
4. ✅ 根据需要修改配置

---

**祝您部署顺利！** 🐳🚀

有任何问题，请查看故障排查章节或反馈给我。

