import re


DEMO_TEMPLATES = [
    {
        "code": "member_order_dimension_v1",
        "name": "分维度会员数据",
        "short_name": "会员数据",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "会员订单明细，按会员类型与子类别填报。",
        "match": ["会员数据"],
        "header_keywords": ["日期", "类别", "会员订单数"],
        "date_fields": ["日期"],
        "required_fields": ["日期", "类别", "子类别"],
        "numeric_fields": ["会员订单数", "会员订单数(支付成功)", "会员订单金额"],
        "sample_filename": "示例-分维度会员数据 2026.07.xlsx",
        "default_owner": "demo_member",
        "sort_order": 10,
    },
    {
        "code": "bad_debt_customer_v1",
        "name": "应收坏账线下录入模板",
        "short_name": "应收坏账",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "坏账分客户计提明细。",
        "match": ["应收坏账"],
        "header_keywords": ["坏账截至统计日期", "客户名称", "坏账计提金额_元"],
        "date_fields": ["坏账截至统计日期"],
        "required_fields": ["坏账截至统计日期", "客户名称", "坏账计提金额_元"],
        "numeric_fields": ["坏账计提金额_元"],
        "sample_filename": "应收坏账相关线下录入模板-2026.07.xlsx",
        "default_owner": "demo_member",
        "sort_order": 20,
    },
    {
        "code": "self_operated_uncollected_v1",
        "name": "自营未回款线下录入模板",
        "short_name": "自营未回款",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "自营广告未回款线下明细。",
        "match": ["自营未回款"],
        "header_keywords": ["统计截至日期", "项目名称", "未回款金额"],
        "date_fields": ["统计截至日期"],
        "required_fields": ["统计截至日期", "项目名称", "未回款金额"],
        "numeric_fields": ["暂估金额", "发票情况", "未开票", "结款金额", "返点比例", "未回款金额"],
        "sample_filename": "示例-自营未回款线下录入模板2026.07.xlsx",
        "default_owner": None,
        "sort_order": 30,
    },
    {
        "code": "cash_flow_detail_v1",
        "name": "现金流量明细表",
        "short_name": "现金流量明细表",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "全合并公司现金流量凭证明细。",
        "match": ["现金流量明细表"],
        "header_keywords": ["日期", "来源", "现金流量表项"],
        "date_fields": ["日期", "会计期间自："],
        "required_fields": ["日期", "来源", "现金流量表项"],
        "numeric_fields": ["原币金额", "本币金额"],
        "sample_filename": "现金流量明细表-202607.xlsx",
        "default_owner": "demo_cash",
        "sort_order": 40,
    },
    {
        "code": "payroll_headcount_v1",
        "name": "发薪人数录入模板",
        "short_name": "发薪人数",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "各部门发薪人数、在职及实习生数。",
        "match": ["发薪人数"],
        "header_keywords": ["日期", "部门名称", "发薪人数"],
        "date_fields": ["日期"],
        "required_fields": ["日期", "部门名称", "发薪人数"],
        "numeric_fields": ["实习生薪酬", "发薪人数", "在职员工数", "实习生数"],
        "sample_filename": "1、发薪人数录入模板-7月.xlsx",
        "default_owner": "demo_payroll",
        "sort_order": 50,
    },
    {
        "code": "ap_performance_aging_v1",
        "name": "履约率、应付账龄录入模板",
        "short_name": "履约率、应付账龄",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "履约率分析与应付账款账龄。",
        "match": ["履约率", "应付账龄"],
        "header_keywords": ["统计截至时间", "类别", "供应商名称"],
        "date_fields": ["统计截至时间"],
        "required_fields": ["统计截至时间", "类别", "供应商名称"],
        "numeric_fields": ["应付余额", "0-3个月", "4-6个月", "7-12个月", "1年以上"],
        "sample_filename": "3、履约率、应付账龄录入模板-2026.07-V1.xlsx",
        "default_owner": "demo_payroll",
        "sort_order": 60,
    },
    {
        "code": "wealth_income_v1",
        "name": "理财收益 BI 导入模板",
        "short_name": "理财收益",
        "version": "1.0",
        "status": "enabled",
        "effective_month": "2026-08",
        "description": "各行理财及结构性存款收益。",
        "match": ["理财收益"],
        "header_keywords": ["年月", "银行", "收益"],
        "date_fields": ["年月"],
        "required_fields": ["年月", "银行", "收益"],
        "numeric_fields": ["实收金额", "收益", "收益率", "全年天数"],
        "sample_filename": "2026.7 理财收益BI导入模板.xlsx",
        "default_owner": "demo_income",
        "sort_order": 70,
    },
]

TEMPLATES = DEMO_TEMPLATES


# Offsets are relative to the task/reporting month. The task month remains the
# platform and write-ledger scope; only the business date inside each sheet is
# allowed to follow its documented period semantics.
SHEET_REPORT_MONTH_OFFSETS = {
    "wealth_income_v1": {
        "实际": 0,
        "预测": 1,
    },
}


BUILTIN_TABLE_MAPPINGS = {
    "member_order_dimension_v1": {
        "target_table": "example_member_order_dimension_btl",
        "fields": {
            "日期": "order_date",
            "类别": "member_category",
            "子类别": "member_subcategory",
            "会员订单数": "member_order_count",
            "会员订单数(支付成功)": "paid_member_order_count",
            "会员订单金额": "member_order_amount",
        },
    },
    "bad_debt_customer_v1": {
        "target_table": "example_bad_debt_customer_btl",
        "fields": {
            "坏账截至统计日期": "bad_debt_stat_date",
            "业务类型": "business_type",
            "匹配前台展示分类": "display_category",
            "客户名称": "customer_name",
            "坏账计提金额_元": "bad_debt_provision_amount",
            "生效时间": "effective_time",
            "失效时间": "expiry_time",
        },
    },
    "self_operated_uncollected_v1": {
        "target_table": "example_self_operated_uncollected_btl",
        "fields": {
            "统计截至日期": "stat_date",
            "合同编号": "contract_no",
            "起投日期": "campaign_start_date",
            "结束日期": "campaign_end_date",
            "暂估金额": "estimated_amount",
            "合同名称": "contract_name",
            "项目名称": "project_name",
            "最终客户": "end_customer",
            "代理公司": "agency_company",
            "发票情况": "invoiced_amount",
            "开票日期": "invoice_date_raw",
            "未开票": "uninvoiced_amount",
            "结款金额": "settlement_amount",
            "到款日期": "receipt_date_raw",
            "返点比例": "rebate_rate",
            "现金折扣比例": "cash_discount_rate",
            "未回款金额（净额）=应收账款ebs": "uncollected_net_amount",
            "逾期天数": "overdue_days_raw",
            "投放方式": "placement_method",
            "客户简称": "customer_short_name",
            "框架合同": "framework_contract_flag",
            "单笔合同": "individual_contract_flag",
            "合同状态": "contract_status",
            "是否正常": "normal_status",
            "合同约定": "contract_terms",
        },
    },
    "cash_flow_detail_v1": {
        "target_table": "example_cash_flow_detail_btl",
        "fields": {
            "日期": "transaction_date",
            "来源": "source_system",
            "单据编号": "document_no",
            "单据名称": "document_name",
            "行号": "line_no",
            "现金流量表项": "cash_flow_item",
            "描述": "description",
            "账户": "account_code",
            "账户说明": "account_description",
            "原币币种": "transaction_currency",
            "是否拆分": "split_flag",
            "原币金额": "original_currency_amount",
            "本币金额": "local_currency_amount",
        },
    },
    "payroll_headcount_v1": {
        "target_table": "example_payroll_headcount_btl",
        "fields": {
            "日期": "report_date",
            "部门名称": "department_name",
            "实习生薪酬": "intern_compensation",
            "发薪人数": "payroll_headcount",
            "在职员工数": "active_employee_count",
            "实习生数": "intern_count",
            "录入时间": "entry_time",
            "录入备注": "entry_remark",
            "录入人": "entry_user",
        },
    },
    "ap_performance_aging_v1": {
        "sheets": {
            "履约率分析": {
                "target_table": "example_ap_performance_detail_btl",
                "fields": {
                    "统计截至时间": "stat_date", "类别": "category", "业务明细": "business_detail",
                    "供应商名称": "supplier_name", "应付余额": "accounts_payable_balance",
                    "合同签署账期": "contract_payment_term", "应付账期": "payable_term",
                    "实际付款账期及情况": "actual_payment_term_status",
                },
            },
            "应付账款账龄": {
                "target_table": "example_ap_aging_detail_btl",
                "fields": {
                    "统计截至时间": "stat_date", "类别": "category", "业务明细": "business_detail",
                    "供应商名称": "supplier_name", "应付余额": "accounts_payable_balance",
                    "0-3个月": "aging_0_3_months", "4-6个月": "aging_4_6_months",
                    "7-12个月": "aging_7_12_months", "1年以上": "aging_over_1_year",
                    "录入时间": "entry_time", "录入人": "entry_user", "录入备注": "entry_remark",
                },
            },
        },
    },
    "wealth_income_v1": {
        "sheets": {
            "实际": {
                "target_table": "example_wealth_income_actual_btl",
                "fields": {
                    "年月": "income_month",
                    "银行": "bank_name",
                    "理财产品类型": "product_type",
                    "实收金额": "actual_received_amount",
                    "收益": "income_amount",
                    "收益率": "yield_rate",
                    "全年天数": "days_in_year",
                },
            },
            "预测": {
                "target_table": "example_wealth_income_forecast_btl",
                "fields": {
                    "年月": "income_month",
                    "银行": "bank_name",
                    "理财产品类型": "product_type",
                    "收益": "income_amount",
                    "收益率": "yield_rate",
                    "全年天数": "days_in_year",
                },
            },
        },
    },
}


MAPPING_SYSTEM_FIELDS = {
    "id",
    "report_month",
    "import_batch_id",
    "source_sheet_name",
    "source_row_number",
    "data_import_time",
    "data_import_user",
}


def _normalized_mapping_name(value):
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def suggest_template_field_mapping(template_code, source_sheet_name, source_fields, columns):
    """Return conservative, read-only field suggestions for an existing target table."""
    target_columns = [
        str(item.get("name") or "")
        for item in columns
        if item.get("name") and str(item.get("name")).casefold() not in MAPPING_SYSTEM_FIELDS
    ]
    available = set(target_columns)
    definition = BUILTIN_TABLE_MAPPINGS.get(template_code) or {}
    if definition.get("sheets"):
        definition = (definition["sheets"].get(source_sheet_name) or {})
    builtin = definition.get("fields") or {}
    suggested = {}
    used_targets = set()
    matches = []

    for source_field in source_fields:
        target_column = builtin.get(source_field)
        if target_column in available and target_column not in used_targets:
            suggested[source_field] = target_column
            used_targets.add(target_column)
            matches.append({"source_field": source_field, "target_column": target_column, "method": "builtin"})

    remaining_sources = [field for field in source_fields if field not in suggested]
    source_name_counts = {}
    for field in remaining_sources:
        normalized = _normalized_mapping_name(field)
        source_name_counts[normalized] = source_name_counts.get(normalized, 0) + 1
    targets_by_name = {}
    for target_column in target_columns:
        if target_column in used_targets:
            continue
        normalized = _normalized_mapping_name(target_column)
        targets_by_name.setdefault(normalized, []).append(target_column)

    for source_field in remaining_sources:
        normalized = _normalized_mapping_name(source_field)
        candidates = targets_by_name.get(normalized) or []
        if normalized and source_name_counts.get(normalized) == 1 and len(candidates) == 1:
            target_column = candidates[0]
            suggested[source_field] = target_column
            used_targets.add(target_column)
            matches.append({"source_field": source_field, "target_column": target_column, "method": "normalized_exact"})

    return {
        "columns": columns,
        "suggested_field_mapping": suggested,
        "matches": matches,
        "unmatched_source_fields": [field for field in source_fields if field not in suggested],
    }


def default_validation_rules(template):
    return []


def get_template(code):
    for template in TEMPLATES:
        if template["code"] == code:
            return template
    return None


def describe_template(template):
    return {
        "code": template["code"],
        "name": template["name"],
        "short_name": template["short_name"],
        "version": template["version"],
        "status": template["status"],
        "effective_month": template["effective_month"],
        "description": template["description"],
        "sample_filename": template["sample_filename"],
        "required_fields": template.get("required_fields", []),
        "numeric_fields": template.get("numeric_fields", []),
        "validation_rules": template.get("validation_rules", []),
        "date_fields": template.get("date_fields", []),
        "header_keywords": template.get("header_keywords", []),
        "target_strategy": "unconfigured",
        "sort_order": template["sort_order"],
    }


def detect_template(filename):
    for template in DEMO_TEMPLATES:
        if all(fragment in filename for fragment in template["match"]):
            return template
    return None
