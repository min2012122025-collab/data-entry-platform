"""Stable HTTP request contracts for the public API."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserCreateRequest(BaseModel):
    username: str
    display_name: str
    role: Literal["admin", "submitter"]
    department: str = "业务部门"
    password: str = Field(min_length=8)


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[Literal["admin", "submitter"]] = None
    department: Optional[str] = None
    disabled: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8)


class TemplateWriteRequest(BaseModel):
    code: Optional[str] = None
    name: str
    short_name: Optional[str] = None
    description: str = ""
    status: str = "draft"
    version: str = "1.0"
    effective_month: str = "2026-08"
    sample_filename: str = ""
    required_fields: list[str] = []
    numeric_fields: list[str] = []
    date_fields: list[str] = []
    header_keywords: list[str] = []
    match: list[str] = []
    validation_rules: list[dict] = []


class TemplateVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    effective_month: str = Field(pattern=r"^\d{4}-\d{2}$")


class TemplateHeaderRequest(BaseModel):
    sheets: dict[str, int]


class ResponsibilityRequest(BaseModel):
    template_code: str
    owner_user_id: Optional[int] = None
    effective_month: str


class DataConnectionRequest(BaseModel):
    name: str
    connection_type: str = "mysql"
    host: str
    port: int = 3306
    username: str
    password: Optional[str] = None
    database_name: Optional[str] = None
    status: str = "active"


class VoidRequest(BaseModel):
    reason: str = Field(min_length=2)
    report_month: str = Field(pattern=r"^\d{4}-\d{2}$")


class CommitRequest(BaseModel):
    report_month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ReportingDeadlineRequest(BaseModel):
    closes_at: datetime


class TableMappingRequest(BaseModel):
    version: str
    source_sheet_name: str | None = Field(default=None, min_length=1, max_length=255)
    data_connection_id: int
    target_table: str = Field(min_length=1, max_length=128)
    field_mapping: dict[str, str] = {}
