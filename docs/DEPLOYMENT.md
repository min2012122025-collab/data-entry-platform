# 正式部署

源码与运行数据分开保存。请使用 Python 3.11+，安装 `backend/requirements.txt`。

在进程环境中配置以下参数，密码与密钥由部署人员生成：

```sh
ENTRY_ENV=production
ENTRY_DATABASE_URL=mysql+pymysql://entry_user:REPLACE_WITH_PASSWORD@localhost/data_entry
ENTRY_EXPECTED_DATABASE=data_entry
ENTRY_DATA_DIR=/var/lib/data-entry
ENTRY_UPLOAD_DIR=/var/lib/data-entry/uploads
ENTRY_SOURCE_DIR=/var/lib/data-entry/templates
ENTRY_SECRET_KEY_FILE=/etc/data-entry/secret.key
ENTRY_COOKIE_SECURE=1
ENTRY_SEED_PASSWORD_ADMIN=REPLACE_WITH_ADMIN_PASSWORD
ENTRY_EXTERNAL_WRITES_ENABLED=0
```

`ENTRY_SECRET_KEY_FILE` 必须使用绝对路径，文件权限为 `0600`。也可使用 `ENTRY_SECRET_KEY` 环境变量，两种方式只能选择一种。不要把真实配置提交到 Git。

设置环境变量后，在项目根目录运行：

```sh
PYTHONPATH=backend .venv/bin/python -m alembic -c database/alembic.ini upgrade head
PYTHONPATH=backend .venv/bin/python -m database.operations.seed_data
./run.sh
```

初始化仅创建管理员。登录后创建用户与模板，配置月度任务、外部数据库连接和入库映射。核验映射后设置 `ENTRY_EXTERNAL_WRITES_ENABLED=1` 并重启服务。正式服务必须通过 HTTPS 反向代理提供访问；默认只监听本机 `127.0.0.1:8125`。

品牌配置位于 `ENTRY_DATA_DIR/branding/`。请与数据库、上传文件和连接加密密钥一起备份。原客户的运行数据和证书没有包含在此项目中。

本版本未验证正式数据库迁移与实际入库；首次部署前应在独立测试数据库完成迁移、填报和入库验收。
