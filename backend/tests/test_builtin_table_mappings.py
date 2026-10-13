from app.services.templates import BUILTIN_TABLE_MAPPINGS


def test_builtin_template_modules_use_configured_business_tables():
    expected_targets = {
        "member_order_dimension_v1": "example_member_order_dimension_btl",
        "bad_debt_customer_v1": "example_bad_debt_customer_btl",
        "self_operated_uncollected_v1": "example_self_operated_uncollected_btl",
        "cash_flow_detail_v1": "example_cash_flow_detail_btl",
        "payroll_headcount_v1": "example_payroll_headcount_btl",
        ("ap_performance_aging_v1", "履约率分析"): "example_ap_performance_detail_btl",
        ("ap_performance_aging_v1", "应付账款账龄"): "example_ap_aging_detail_btl",
        ("wealth_income_v1", "实际"): "example_wealth_income_actual_btl",
        ("wealth_income_v1", "预测"): "example_wealth_income_forecast_btl",
    }

    for module, target_table in expected_targets.items():
        if isinstance(module, tuple):
            template_code, sheet_name = module
            mapping = BUILTIN_TABLE_MAPPINGS[template_code]["sheets"][sheet_name]
        else:
            mapping = BUILTIN_TABLE_MAPPINGS[module]
        assert mapping["target_table"] == target_table
