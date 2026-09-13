import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';

const app = express();
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_DIR = path.join(__dirname, '..', '..', 'web');
const PORT = process.env.GATEWAY_PORT ? Number(process.env.GATEWAY_PORT) : 5173;
const USERS_SERVICE_URL = process.env.USERS_SERVICE_URL || 'http://localhost:5174';
const SEGMENTATION_SERVICE_URL =
  process.env.SEGMENTATION_SERVICE_URL || 'http://localhost:8080';

const serviceProxy = (target, mountPath) =>
  createProxyMiddleware({
    target,
    changeOrigin: true,
    logLevel: 'warn',
    pathRewrite: (requestPath) => `${mountPath}${requestPath}`,
  });

app.use(
  '/api/v1/segmentation',
  serviceProxy(SEGMENTATION_SERVICE_URL, '/api/v1/segmentation'),
);
app.use(
  '/api/v1/classification',
  serviceProxy(SEGMENTATION_SERVICE_URL, '/api/v1/classification'),
);
app.use('/api', serviceProxy(USERS_SERVICE_URL, '/api'));

app.use(express.static(WEB_DIR));
app.get('*', (_req, res) => {
  res.sendFile(path.join(WEB_DIR, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`API gateway: http://0.0.0.0:${PORT}`);
  console.log(`Users service → ${USERS_SERVICE_URL}`);
  console.log(`Segmentation service → ${SEGMENTATION_SERVICE_URL}`);
});
