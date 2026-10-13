"""Audit, external data connection, and template mapping endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ...container import database, service
from ...services.templates import suggest_template_field_mapping
from ..dependencies import admin_user
from ..schemas import DataConnectionRequest, TableMappingRequest

router = APIRouter(tags=["data settings and audit"])


@router.get("/api/audit-logs")
def list_audit_logs(limit: int = 100, user=Depends(admin_user)):
    return database.list_audit_logs(user, limit=limit)


@router.get("/api/data-connections")
def list_data_connections(user=Depends(admin_user)):
    return database.list_data_connections()


@router.post("/api/data-connections")
def create_data_connection(payload: DataConnectionRequest, user=Depends(admin_user)):
    try:
        return database.create_data_connection(user["id"], payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/data-connections/{connection_id}")
def update_data_connection(connection_id: int, payload: DataConnectionRequest, user=Depends(admin_user)):
    try:
        return database.update_data_connection(user["id"], connection_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/data-connections/{connection_id}/test")
def test_data_connection(connection_id: int, user=Depends(admin_user)):
    try:
        return database.test_data_connection(user["id"], connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/data-connections/{connection_id}/deletion-impact")
def data_connection_deletion_impact(connection_id: int, user=Depends(admin_user)):
    try:
        return database.data_connection_deletion_impact(connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/data-connections/{connection_id}")
def delete_data_connection(connection_id: int, user=Depends(admin_user)):
    try:
        return database.delete_data_connection(user["id"], connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/data-connections/{connection_id}/tables")
def list_connection_tables(connection_id: int, refresh: bool = False, user=Depends(admin_user)):
    try:
        return {"tables": database.list_connection_tables(connection_id, refresh=refresh)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/data-connections/{connection_id}/tables/{table_name}/columns")
def get_connection_table_columns(connection_id: int, table_name: str, user=Depends(admin_user)):
    try:
        return {"columns": database.get_connection_table_columns(connection_id, table_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/template-mappings")
def list_template_mappings(user=Depends(admin_user)):
    return database.list_template_mappings()


@router.get("/api/templates/{template_code}/table-mapping")
def get_template_mapping(template_code: str, version: Optional[str] = None, source_sheet_name: Optional[str] = None, user=Depends(admin_user)):
    return database.get_template_mapping(template_code, version, source_sheet_name)


@router.get("/api/templates/{template_code}/table-mapping/suggestion")
def suggest_template_mapping(
    template_code: str,
    version: str,
    data_connection_id: int,
    target_table: str,
    source_sheet_name: Optional[str] = None,
    user=Depends(admin_user),
):
    try:
        source_fields = service.get_template_version_source_fields(template_code, version, source_sheet_name)
        if not source_fields:
            raise ValueError("请先上传并确认模板文件表头")
        columns = database.get_connection_table_columns(data_connection_id, target_table)
        return suggest_template_field_mapping(template_code, source_sheet_name, source_fields, columns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/templates/{template_code}/table-mapping")
def save_template_mapping(template_code: str, payload: TableMappingRequest, user=Depends(admin_user)):
    try:
        source_fields = service.get_template_version_source_fields(template_code, payload.version, payload.source_sheet_name)
        if not source_fields:
            raise ValueError("请先上传并确认模板文件表头")
        args = (user["id"], template_code, payload.version, payload.data_connection_id, payload.target_table, source_fields, payload.field_mapping)
        return database.save_template_mapping(*args, source_sheet_name=payload.source_sheet_name) if payload.source_sheet_name else database.save_template_mapping(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/template-mappings/{mapping_id}")
def delete_template_mapping(mapping_id: int, user=Depends(admin_user)):
    try:
        return database.delete_template_mapping(user["id"], mapping_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/templates/{template_code}/table-mapping/validate")
def validate_template_mapping(template_code: str, version: Optional[str] = None, source_sheet_name: Optional[str] = None, user=Depends(admin_user)):
    try:
        mapping = database.get_template_mapping(template_code, version, source_sheet_name) if source_sheet_name else database.get_template_mapping(template_code, version)
        if not mapping:
            raise ValueError("请先保存模板入库映射")
        selected_version = version or mapping["template"]["version"]
        source_fields = service.get_template_version_source_fields(template_code, selected_version, source_sheet_name or mapping.get("source_sheet_name"))
        if not source_fields:
            raise ValueError("请先上传并确认模板文件表头")
        return database.validate_template_mapping(user["id"], mapping["id"], source_fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
