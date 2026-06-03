# lingji-gateway-node (Spike)

Node.js 版 Gateway **并行 Spike**，协议与 [Go Gateway](../lingji-gateway) 对齐；**不替换**生产 `lingji.mygoal.tech`。

见 [SPIKE.md](./SPIKE.md)。

```bash
npm install
npm test
npm start   # 默认 :8766
```

对比脚本：`../scripts/compare-gateway-node.sh`

Compose（可选）：`docker compose --profile gateway-node up -d gateway-node`
