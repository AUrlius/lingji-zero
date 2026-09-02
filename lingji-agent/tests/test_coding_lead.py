from lingji_agent.execution.coding_lead import lead_cmd_is_safe


def test_lead_cmd_rejects_force_and_yolo():
    assert lead_cmd_is_safe(None) is False
    assert lead_cmd_is_safe([]) is False
    assert lead_cmd_is_safe(["/bin/agent", "-p", "--trust"]) is True
    assert lead_cmd_is_safe(["/bin/agent", "-p", "--force", "--trust"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--YOLO"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--force=true"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--sandbox", "disabled"]) is True
