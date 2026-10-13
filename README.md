# 通用录入平台

支持 Excel 模板管理、月度填报任务、负责人分配、数据校验、导入预览、数据库字段映射和操作审计。管理员可以上传自己的品牌图片、更换平台名称。

## 环境

- Python 3.11 或更新版本
- 开发演示：SQLite
- 正式部署：MySQL，或经验证兼容的 PostgreSQL

## 本地启动

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp .env.example .env
./scripts/dev.sh
```

启动脚本首次运行会创建本地演示库。访问 http://127.0.0.1:8125 。演示管理员为 `admin`，演示密码为 `sqlite-test-admin-password`，仅用于本地开发。正式环境由部署人员设置独立密码，首次登录强制修改。

## 品牌设置

管理员登录后在“数据设置”页面使用“主题设置”。可修改平台名称，上传 PNG、JPEG 或 WebP 品牌图片，或恢复默认图标。图片最大 2MB，尺寸最大 2048 × 2048，会重新编码为 PNG。登录页和平台顶部同步使用品牌配置。配置保存在 `ENTRY_DATA_DIR` 下，重启后保留。登录页大幅背景为内置山水图片，目前不支持通过此设置上传更换。

## 模板与数据

正式初始化只创建管理员，不创建业务模板、人员或入库映射。通过模板管理上传自己的 Excel 文件，在数据设置中配置目标连接及字段映射。开发演示附带匿名的财务模板示例；它们不构成任何组织的真实数据。

业务文件、数据库、密码、连接密钥、证书和备份不纳入 Git 管理。环境参数请参阅 [.env.example](.env.example) 和 [部署说明](docs/DEPLOYMENT.md)。

## 验证

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
.venv/bin/python scripts/check_public_source.py
```

## 前端维护限制

当前版本包含可运行的前端构建文件 `frontend/dist/`，原始 React 工程和构建配置未包含在已有交付材料中，因此无法重建原界面。新增的品牌设置源码位于 `frontend/src/branding.js` 和 `frontend/src/branding.css`；运行 `python3 scripts/build_branding.py` 将它们同步到静态目录。其余界面的长期迭代需要补齐原始前端工程，或单独规划重建。

此仓库尚未声明开源许可证；公开可见不代表授予使用或再分发许可。

## Git 管理

日常修改、提交与同步的步骤请参阅 [Git 使用说明](docs/GIT.md)。
