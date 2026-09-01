# LingjiZero playbooks

Tier 0 固定脚本：禁止把参数当 shell 执行。预期 cwd：`/mnt/e/LingjiPlan/LingjiZero`。

WSL:

```bash
cd /mnt/e/LingjiPlan/LingjiZero
bash scripts/playbooks/agent_status.sh
```

Last line is evidence: `STATUS=ok` or `STATUS=fail` plus a compact JSON object.

| playbook_id | script | what |
|-------------|--------|------|
| `agent.status` | `agent_status.sh` | Gateway `/health` (curl skip-on-fail), incoming writable, `pgrep` / `python3 -m lingji_agent.main --status` |
| `agent.restart` | `agent_restart.sh` | `git pull --ff-only origin main` (pull fail is not fatal), then `./scripts/restart-agent-wsl.sh`; missing restart script → fail |
| `git-pull-deploy` | `git_pull_deploy.sh` | `git pull --ff-only` only; prints would-run `./scripts/deploy-gateway.sh` and **does not deploy** |
| `fleet-smoke` | `fleet_smoke.sh` | Write a tiny file to incoming and `ls` it; no fleet HTTP |

Incoming dir: `lingji-agent/data/incoming`, or `$HOME/lingji-incoming` if that exists.
