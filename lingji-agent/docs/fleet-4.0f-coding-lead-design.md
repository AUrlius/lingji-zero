# Fleet 4.0f — 领队编排（工程摘要）

> **状态**：**实现中，未宣称已编码**（合入且全量回归绿前保持此态；2026-09-02）  
> **正文**：[Sprint Fleet 4.0f — 领队编排与施工队](../../../../docs/sprints/第六阶段：编码实现与测试/Sprint Fleet 4.0f — 领队编排与施工队.md)  
> **实现计划**：[Sprint Fleet 4.0f — 实现计划](../../../../docs/sprints/第六阶段：编码实现与测试/Sprint Fleet 4.0f — 实现计划.md)

秘书仍 `job_invoke_coding`。青铜剑领队（技术负责人）出方案并批复提问；无头 Cursor 只改 `workspace/`。串行、一把锁、提问最多 3 轮。领队运行时：**只读 Cursor**（`lead_cmd`，禁止 `--force`/`--yolo`）；见实现计划。

执行者包装脚本：`scripts/coding-run-cursor.sh`（cwd=`{job}/workspace`，读 `executor_prompt.md` 否则 `brief.md`，`agent -p --force --trust --sandbox disabled`）。青铜剑本地若仍用 `/mnt/d/LingjiJobs/bin/run-cursor.sh`，改为读 `executor_prompt.md` 或把 `start_cmd` 指到仓库脚本；未配 `lead_cmd` 的派单会 `runner_missing`。

实现本模块时用 Subagent-Driven（同 4.0e），与产品工单的串行施工不是一回事。
