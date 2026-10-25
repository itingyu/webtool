#!/usr/bin/env node
// 外部插件示例（Node.js）：一行 JSON 进、一行 JSON 出
const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin, terminal: false });

const hit = (kind, sign, why) => ({ hit: { kind, sign, why } });
const bypass = (how, url) => ({ bypass: { how, url, retry: true } });

rl.on('line', (line) => {
  if (!line.trim()) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  const ctx = msg.ctx || {};
  let out = {};
  switch (msg.op) {
    case 'ping':
      out = { ok: true, protocol: 1, name: 'node_example' };
      break;
    case 'inspect': {
      const text = (ctx.text || '').slice(0, 200000).toLowerCase();
      if (text.includes('cf-challenge') || text.includes('just a moment')) {
        out = hit('waf', 'cf-challenge', 'Cloudflare 质询页');
      }
      break;
    }
    case 'bypass':
      out = bypass('换移动端入口', (ctx.url || '').replace('www.', 'm.'));
      break;
    default:
      out = {};
  }
  process.stdout.write(JSON.stringify(out) + '\n');
});
