# lingji-gateway-node Spike

> **决策日期：** 2026-06-03  
> **状态：** 并行 Spike（**不替换**生产 Go Gateway）

## Timing 决策

| 项 | 决定 |
|----|------|
| G6 实机 P0/P1（#26、#5–7、#17–18） | **继续**；Spike 不阻塞人工验收 |
| 生产 cutover | **不做**；`lingji.mygoal.tech` 仍跑 Go |
| Spike 范围 | 新建 `lingji-gateway-node/`，协议 1:1，本地/compose 8766 双跑 |
| Cutover 门禁 | Go 与 Node 同 `prod-e2e-smoke` section 全绿 + 实机 1 轮 |

## 运行

```bash
cd LingjiZero/lingji-gateway-node
npm install
npm test
npm start   # 默认 LINGJI_PORT=8766（避免与 Go 8765 冲突）
```

## 对比冒烟

```bash
cd LingjiZero
./scripts/compare-gateway-node.sh
```

## Agent 侧

**无改动** — WS JSON 与 Go Gateway 相同。
