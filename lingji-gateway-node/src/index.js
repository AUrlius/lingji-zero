import { startGateway } from './server.js';

const app = await startGateway();

function shutdown() {
  app.close().then(() => process.exit(0));
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
