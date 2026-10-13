import os
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit


BASE_DIR = Path(__file__).resolve().parents[3]


class Settings:
    def __init__(self):
        environment = os.getenv("ENTRY_ENV")
        if environment not in {"production", "development", "test"}:
            raise RuntimeError("ENTRY_ENV 必须显式设置为 production、development 或 test")
        self.app_name = "通用录入平台"
        self.environment = environment
        self.allow_sqlite = os.getenv("ENTRY_ALLOW_SQLITE", "0") == "1"
        self.data_dir = Path(os.getenv("ENTRY_DATA_DIR", BASE_DIR / "business_files"))
        self.upload_dir = Path(os.getenv("ENTRY_UPLOAD_DIR", self.data_dir / "uploads"))
        self.source_dir = Path(os.getenv("ENTRY_SOURCE_DIR", BASE_DIR / "business_files" / "templates"))
        self.database_url = os.getenv("ENTRY_DATABASE_URL") or ("sqlite:///:memory:" if self.allow_sqlite else None)
        self.expected_database = os.getenv("ENTRY_EXPECTED_DATABASE")
        self.session_cookie = "entry_session"
        self.session_hours = int(os.getenv("ENTRY_SESSION_HOURS", "12"))
        self.cookie_secure = os.getenv("ENTRY_COOKIE_SECURE", "0") == "1"
        secret_key_value = os.getenv("ENTRY_SECRET_KEY")
        secret_key_file_value = os.getenv("ENTRY_SECRET_KEY_FILE")
        if secret_key_value and secret_key_file_value:
            raise RuntimeError("ENTRY_SECRET_KEY 与 ENTRY_SECRET_KEY_FILE 不能同时配置")
        self.secret_key_file = Path(secret_key_file_value).expanduser() if secret_key_file_value else None
        self.secret_key = secret_key_value or self._read_secret_key_file(self.secret_key_file)
        self.secret_key_source = "environment" if secret_key_value else "file" if self.secret_key_file else "missing"
        self.external_writes_enabled = os.getenv("ENTRY_EXTERNAL_WRITES_ENABLED", "0") == "1"
        self.test_external_writes_enabled = os.getenv("ENTRY_TEST_EXTERNAL_WRITES", "0") == "1"
        self.forwarded_allow_ips = os.getenv("ENTRY_FORWARDED_ALLOW_IPS", "127.0.0.1")

    @staticmethod
    def _read_secret_key_file(path):
        if not path:
            return None
        if not path.is_absolute():
            raise RuntimeError("ENTRY_SECRET_KEY_FILE 必须是绝对路径")
        if not path.is_file():
            raise RuntimeError("ENTRY_SECRET_KEY_FILE 指向的密钥文件不存在")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise RuntimeError("ENTRY_SECRET_KEY_FILE 权限必须为 0600")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("ENTRY_SECRET_KEY_FILE 不能为空")
        return value

    @property
    def is_production(self):
        return self.environment == "production"

    def validate_process_environment(self):
        if not self.secret_key:
            raise RuntimeError("缺少 ENTRY_SECRET_KEY 或 ENTRY_SECRET_KEY_FILE，不能保护数据连接凭据")
        if not self.is_production:
            return True
        if self.allow_sqlite or str(self.database_url or "").startswith("sqlite"):
            raise RuntimeError("production 环境禁止使用 SQLite 或 ENTRY_ALLOW_SQLITE=1")
        if not self.cookie_secure:
            raise RuntimeError("production 环境必须设置 ENTRY_COOKIE_SECURE=1")
        required_paths = {
            "ENTRY_DATA_DIR": self.data_dir,
            "ENTRY_UPLOAD_DIR": self.upload_dir,
            "ENTRY_SOURCE_DIR": self.source_dir,
        }
        for name, path in required_paths.items():
            if not os.getenv(name):
                raise RuntimeError(f"production 环境必须显式设置 {name}")
            resolved = path.expanduser().resolve()
            if not path.is_absolute() or resolved == BASE_DIR or resolved.is_relative_to(BASE_DIR):
                raise RuntimeError(f"production 环境的 {name} 必须是仓库外的绝对路径")
        self.validate_runtime()
        return True

    def validate_runtime(self, database_url=None):
        url = database_url or self.database_url
        if not url:
            raise RuntimeError("缺少 ENTRY_DATABASE_URL，生产数据库连接必须由外部环境提供")
        if str(url).startswith("sqlite"):
            if not self.allow_sqlite:
                raise RuntimeError("SQLite is allowed only when ENTRY_ALLOW_SQLITE=1")
            return
        if not self.expected_database:
            raise RuntimeError("缺少 ENTRY_EXPECTED_DATABASE，禁止使用未确认的生产数据库")
        actual_database = unquote(urlsplit(str(url)).path.lstrip("/"))
        if not actual_database or actual_database != self.expected_database:
            raise RuntimeError("ENTRY_DATABASE_URL 数据库名与 ENTRY_EXPECTED_DATABASE 不一致")
        if not self.secret_key:
            raise RuntimeError("缺少 ENTRY_SECRET_KEY 或 ENTRY_SECRET_KEY_FILE，生产密钥必须由外部环境提供")

    def seed_password(self, username, dialect):
        if dialect == "sqlite" and self.allow_sqlite:
            return f"sqlite-test-{username}-password"
        env_name = f"ENTRY_SEED_PASSWORD_{username.upper()}"
        password = os.getenv(env_name)
        if not password:
            raise RuntimeError(f"缺少 {env_name}，正式种子账号密码必须由外部环境提供")
        return password


settings = Settings()
