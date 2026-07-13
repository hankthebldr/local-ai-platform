// core/heartbeat.js — backend liveness banner (phase-2 U2 carve).
import { Net } from './net.js';
import { Toast } from './ui.js';

export const Heartbeat = (function () {
  let _timer = null;
  let _lastStatus = null;

  function _chip() {
    return document.getElementById('env-chip-label');
  }
  function _envChip() {
    return document.getElementById('env-chip');
  }

  async function _tick() {
    const r = await Net.call('/health', { silent: true, retries: 0 });
    const status = r.ok && r.data ? (r.data.status || 'unknown') : 'offline';
    // /health returns ollama: { status: "healthy" | "degraded", models_loaded: N }
    const ollamaUp = !!(r.ok && r.data && r.data.ollama && r.data.ollama.status === 'healthy');
    _paint(status, ollamaUp, r.data);
    _lastStatus = status;
  }

  function _paint(status, ollamaUp, data) {
    const chip = _chip();
    const env = _envChip();
    if (!chip || !env) return;
    env.classList.remove('healthy', 'degraded', 'offline');
    const modelCount = (data && data.ollama && (data.ollama.models_loaded || (data.ollama.models || []).length)) || 0;
    if (status === 'healthy' && ollamaUp) {
      env.classList.add('healthy');
      chip.textContent = 'LOCAL';
      env.title = 'Healthy · ' + modelCount + ' models loaded';
    } else if (status === 'degraded' || (status === 'healthy' && !ollamaUp)) {
      env.classList.add('degraded');
      chip.textContent = 'DEGRADED';
      env.title = 'Ollama unreachable. Inference will fail until it comes back.';
      if (_lastStatus && _lastStatus !== 'degraded' && window.Toast) {
        Toast.warn('Ollama unreachable', 'Models won’t respond until the service is back.', { ttl: 4500 });
      }
    } else {
      env.classList.add('offline');
      chip.textContent = 'OFFLINE';
      env.title = 'API not responding to /health.';
    }
  }

  function start(intervalMs) {
    if (_timer) clearInterval(_timer);
    _tick();
    _timer = setInterval(_tick, intervalMs || 30_000);
  }
  function stop() { if (_timer) clearInterval(_timer); _timer = null; }
  function lastStatus() { return _lastStatus; }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => start(30_000));
  } else {
    start(30_000);
  }

  return { start, stop, tick: _tick, lastStatus };
})();
