# Docker 部署

需要 Docker Engine 和 Docker Compose v2。镜像使用 Python 3.12，数据库使用 MySQL 8.4。正式服务须通过已有的 HTTPS 反向代理访问；Compose 的 HTTP 端口仅绑定宿主机 127.0.0.1，不能作为公网登录入口。

## 首次部署

在解压的源码目录运行（配置生成脚本只依赖 Python 3 标准库）：

```sh
python3 docker-setup.py
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
curl --fail http://127.0.0.1:8125/api/health
```

`.env.docker` 自动生成随机数据库密码、连接加密密钥和初始管理员密码，权限为 0600；已存在时不会覆盖。管理员账号为 `admin`，初始密码查看该文件中的 `ENTRY_SEED_PASSWORD_ADMIN`，首次登录必须修改。不要将该文件发给他人或提交到 Git。

将 HTTPS 反向代理转发到 `http://127.0.0.1:8125`，并传递 Host、X-Forwarded-Proto 和 X-Forwarded-For。如需信任代理头，在 `.env.docker` 中设置 `ENTRY_FORWARDED_ALLOW_IPS` 为容器实际看到的可信代理地址。不要使用 `*`。如果 8125 已占用，设置 `ENTRY_HTTP_PORT` 为其他端口。

容器首次启动执行数据库迁移并创建管理员，不创建示例模板、用户或任务。应用以 UID 10001 运行，数据库不对宿主机开放端口。应用文件保存在 `app_data` 卷，数据库保存在 `mysql_data` 卷。容器重建后这些卷仍会保留。

## 服务器架构与离线镜像

Dockerfile 可在 Linux amd64 和 arm64 上构建。下载的镜像包必须与目标服务器架构一致：`uname -m` 的 x86_64 对应 amd64，aarch64 对应 arm64。只有明确标注已验证的架构才代表本次实际测试过。

已获得离线镜像包时：

```sh
gunzip -c data-entry-platform-v1.0.0-linux-ARCH-images.tar.gz | docker load
python3 docker-setup.py
docker compose --env-file .env.docker up -d --no-build --pull never
```

离线镜像包需要同时包含 `data-entry-platform:v1.0.0` 与 `mysql:8.4`。源码包通过 `--build` 构建，需要访问镜像仓库和 Python 包仓库。

## 升级与恢复

升级前备份 `.env.docker`、应用卷和数据库。不要更换已有 `ENTRY_SECRET_KEY`，否则已保存的外部连接凭据无法解密。数据库密码变更需要同步修改 MySQL 内部账号；仅修改环境变量不会更新已有数据库账号。

```sh
mkdir -p backups
chmod 700 backups
docker compose --env-file .env.docker exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --single-transaction --routines --triggers data_entry' > backups/data-entry.sql
docker compose --env-file .env.docker stop app
docker compose --env-file .env.docker run --rm --no-deps --entrypoint tar app -C /var/lib/data-entry -czf - . > backups/app-data.tar.gz
docker compose --env-file .env.docker up -d --build
```

`docker compose down` 保留数据卷；不要执行 `down -v`，该命令会删除数据库和上传文件。恢复时先停止应用，把应用文件恢复到 `app_data`，将数据库备份导入对应版本 MySQL，并恢复原配置与加密密钥。涉及数据库迁移的回滚必须同时恢复升级前数据库备份，不能仅换旧镜像。

默认关闭向外部业务库写入。确认映射、权限及独立测试库中的填报和入库验收后，才在 Compose 中将 `ENTRY_EXTERNAL_WRITES_ENABLED` 改为 `1` 并重建应用容器。本次容器验收不代表真实业务库入库已验证。
