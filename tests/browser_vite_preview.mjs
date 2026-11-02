/** Serve the existing production build with the browser harness's isolated API. */
import { preview } from '../web/node_modules/vite/dist/node/index.js';

const port = Number(process.argv[process.argv.indexOf('--port') + 1]);
if (!Number.isInteger(port) || port <= 0) throw new Error('Expected --port');
await preview({ preview: { host: '127.0.0.1', port, strictPort: true } });
