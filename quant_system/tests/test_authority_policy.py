from quant_system.iteration.authority_policy import authority_policy
from quant_system.iteration.trading_readiness import FINAL_SYSTEM_OBJECTIVE


def test_ai_is_data_only_and_cannot_affect_scoring():
    policy = authority_policy()
    assert policy["ai"]["scope"] == "data_processing_only"
    assert policy["deterministic_python"]["ai_output_may_enter_score_directly"] is False
    assert policy["deterministic_python"]["may_submit_broker_orders"] is False
    forbidden = " ".join(policy["ai"]["forbidden"])
    assert "评分" in forbidden
    assert "晋级" in forbidden
    assert "交易指令" in forbidden
    assert "券商" in forbidden


def test_material_external_actions_are_human_decisions():
    policy = authority_policy()
    decisions = " ".join(item["decision"] for item in policy["human_decisions"])
    assert "购买" in decisions
    assert "券商" in decisions
    assert "正式推荐" in decisions or "正式策略" in decisions
    assert "熔断" in decisions
    assert policy["product_mode"] == "recommendation_only"
    assert policy["broker_integration"] is False


def test_final_objective_is_recommendation_only_without_broker():
    objective = FINAL_SYSTEM_OBJECTIVE
    assert objective["id"] == "recommendation_strategy_only"
    fields = set(objective["instruction_contract"])
    assert {"action", "as_of", "target_quantity_or_weight", "risk_checks"} <= fields
    assert "recommendation_only" in objective["operating_modes"]
    assert "broker_automated_execution" in objective["abandoned_modes"]
    assert objective["execution_policy"]["broker_integration"] is False
    assert objective["execution_policy"]["auto_order_submission"] is False
