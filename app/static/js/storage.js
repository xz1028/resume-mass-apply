/**
 * 本地辅助存储：弥补后端缺口（无任务列表接口、设置项无 GET 回显）。
 * - rma_task_index：任务 ID 有序索引（新任务前插，上限 100 条 FIFO 淘汰）
 * - rma_matching_threshold / rma_daily_limit：设置镜像（默认值与后端 config 一致）
 * 读取解析失败一律回落默认值，不阻塞页面渲染。
 */

const TASK_INDEX_KEY = 'rma_task_index';
const THRESHOLD_KEY = 'rma_matching_threshold';
const DAILY_LIMIT_KEY = 'rma_daily_limit';
const TASK_INDEX_LIMIT = 100;
const DEFAULT_THRESHOLD = 60;
const DEFAULT_DAILY_LIMIT = 100;

/** @returns {Array<string>} */
function getTaskIndex() {
  try {
    const raw = localStorage.getItem(TASK_INDEX_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter((x) => typeof x === 'string');
  } catch (e) {
    return [];
  }
}

/** 新任务前插，超限 FIFO 淘汰 */
function addTaskId(taskId) {
  const next = [taskId].concat(getTaskIndex().filter((x) => x !== taskId));
  if (next.length > TASK_INDEX_LIMIT) next.length = TASK_INDEX_LIMIT;
  try { localStorage.setItem(TASK_INDEX_KEY, JSON.stringify(next)); } catch (e) { /* 存储不可用时静默 */ }
}

/** 从索引剔除（单查 40401 时调用） */
function removeTaskId(taskId) {
  const next = getTaskIndex().filter((x) => x !== taskId);
  try { localStorage.setItem(TASK_INDEX_KEY, JSON.stringify(next)); } catch (e) { /* ignore */ }
}

/** @returns {number} 匹配阈值镜像（默认 60，与后端 config 默认一致） */
function getMatchingThresholdMirror() {
  const value = parseInt(localStorage.getItem(THRESHOLD_KEY), 10);
  return Number.isFinite(value) && value >= 0 && value <= 100 ? value : DEFAULT_THRESHOLD;
}

function setMatchingThresholdMirror(value) {
  try { localStorage.setItem(THRESHOLD_KEY, String(value)); } catch (e) { /* ignore */ }
}

/** @returns {number} 每日上限镜像（默认 100，与后端 config 默认一致） */
function getDailyLimitMirror() {
  const value = parseInt(localStorage.getItem(DAILY_LIMIT_KEY), 10);
  return Number.isFinite(value) && value >= 1 ? value : DEFAULT_DAILY_LIMIT;
}

function setDailyLimitMirror(value) {
  try { localStorage.setItem(DAILY_LIMIT_KEY, String(value)); } catch (e) { /* ignore */ }
}