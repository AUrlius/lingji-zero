"""run_metrics 单元测试"""

from lingji_agent.foundation import run_metrics


class TestRunMetrics:
    def setup_method(self):
        run_metrics.reset_for_tests()

    def test_increment_and_snapshot(self):
        run_metrics.increment("cmd_total")
        run_metrics.increment("hitl_interrupt_total", 2)
        run_metrics.increment("upload_saved_total")
        run_metrics.increment("upload_fastpath_total")
        snap = run_metrics.snapshot()
        assert snap["cmd_total"] == 1
        assert snap["hitl_interrupt_total"] == 2
        assert snap["upload_saved_total"] == 1
        assert snap["upload_fastpath_total"] == 1
