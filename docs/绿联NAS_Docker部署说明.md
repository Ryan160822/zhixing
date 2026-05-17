# 绿联 NAS Docker 部署说明

本说明用于在绿联 NAS 上通过 Docker Compose 部署手机网页版本。

## 访问方式

部署完成后，在同一局域网访问：

```text
http://绿联NAS的IP:8765
```

例如：

```text
http://192.168.1.20:8765
```

## 项目文件

本项目已经包含：

```text
Dockerfile
docker-compose.yml
.dockerignore
```

容器会运行手机网页服务 `run_mobile.py`，并监听 `0.0.0.0:8765`。

默认 `docker-compose.yml` 会直接拉取 GitHub 自动构建的镜像：

```text
ghcr.io/ryan160822/zhixing:latest
```

如果你想在 NAS 上本地构建镜像，可以改用 `docker-compose.build.yml`。

## 目录持久化

下面两个目录会保存在 NAS 项目目录里：

```text
results/
.runtime/
```

- `results/` 保存查询结果 PNG。
- `.runtime/` 保存运行时临时文件，验证码查询成功后会自动删除对应验证码图片。

## 绿联 NAS 操作步骤

1. 打开绿联 NAS 的 Docker / 容器应用。
2. 新建项目目录，例如：

```text
/volume1/docker/zxgk-query
```

3. 把 GitHub 项目下载到这个目录，或用 SSH 执行：

```bash
cd /volume1/docker
git clone https://github.com/Ryan160822/zhixing.git zxgk-query
cd zxgk-query
```

4. 在绿联 Docker 的 Compose / 项目功能里选择 `docker-compose.yml`。
5. 启动项目。
6. 浏览器打开：

```text
http://绿联NAS的IP:8765
```

## SSH 命令部署

如果你习惯用 SSH，也可以在 NAS 终端里执行：

```bash
cd /volume1/docker/zxgk-query
docker compose up -d
```

查看运行状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

停止服务：

```bash
docker compose down
```

更新项目：

```bash
cd /volume1/docker/zxgk-query
git pull
docker compose pull
docker compose up -d
```

## 本地构建方式

如果 GitHub 镜像暂时还没有发布，或你的 NAS 无法访问 `ghcr.io`，可以使用本地构建：

```bash
cd /volume1/docker/zxgk-query
docker compose -f docker-compose.build.yml up -d --build
```

## 注意事项

当前版本不加登录密码。如果把 NAS 端口映射到公网，任何知道地址的人都能打开查询页面。

如果只在家里或公司局域网使用，不需要做端口映射。
