/**
 * API 客户端层：对后端唯一通道。
 * - request()：fetch + AbortController，默认 15s 超时，错误统一归一化为 ApiError
 * - uploadResume()：XHR 封装（上传进度事件）
 * - 23 个接口调用函数（与后端 REST 接口一一对应）
 * 全部路径为 /api/v1 同源相对路径；写操作不内置任何自动重试。
 */

/** 统一错误对象：code=0 表示网络层错误（不可达/超时） */
class ApiError extends Error {
  /**
   * @param {number} code
   * @param {string} message
   * @param {number|null} httpStatus
   */
  constructor(code, message, httpStatus) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.message = message;
    this.httpStatus = httpStatus;
  }
}

const DEFAULT_TIMEOUT_MS = 15000;

/**
 * 统一 HTTP 客户端。
 * @param {string} path - 同源相对路径（/api/v1/... 或 /health）
 * @param {{method?: 'GET'|'POST'|'PUT'|'PATCH'|'DELETE', query?: Object<string, string|number>, body?: object, timeoutMs?: number, signal?: AbortSignal}} [options]
 * @returns {Promise<any>}
 */
async function request(path, options) {
  const opts = options || {};
  const method = opts.method || 'GET';
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  if (opts.signal) {
    if (opts.signal.aborted) { clearTimeout(timer); controller.abort(); }
    else opts.signal.addEventListener('abort', () => controller.abort(), { once: true });
  }
  let url = path;
  if (opts.query) {
    const params = new URLSearchParams();
    for (const key of Object.keys(opts.query)) {
      const value = opts.query[key];
      if (value !== undefined && value !== null && value !== '') params.append(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += (url.indexOf('?') >= 0 ? '&' : '?') + qs;
  }
  try {
    const resp = await fetch(url, {
      method,
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
    if (resp.status === 204) return null;
    let data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      if (data && data.error && typeof data.error.code === 'number') {
        throw new ApiError(data.error.code, data.error.message || '操作失败', resp.status);
      }
      throw new ApiError(0, '服务响应异常', resp.status);
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err && err.name === 'AbortError') {
      if (timedOut) throw new ApiError(0, '操作结果未知，请刷新查看最新状态', null);
      throw err; // 外部主动中止（路由切换/竞态控制），调用方自行忽略
    }
    throw new ApiError(0, '无法连接本地服务，请确认服务已启动后重试', null);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 简历上传（XHR 实现，支持进度回调）；multipart 字段名固定 file。
 * @param {File} file
 * @param {(percent: number) => void} [onProgress]
 * @returns {Promise<ResumeProfile>}
 */
function uploadResume(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append('file', file);
    xhr.open('POST', '/api/v1/resumes');
    xhr.timeout = DEFAULT_TIMEOUT_MS;
    let done = false;
    xhr.upload.onprogress = (e) => {
      if (done || !e.lengthComputable) return;
      if (onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      done = true;
      let body = null;
      try { body = typeof xhr.response === 'string' ? JSON.parse(xhr.response) : xhr.response; } catch (e) { body = null; }
      if (xhr.status >= 200 && xhr.status < 300 && body) {
        resolve(body);
        return;
      }
      if (body && body.error && typeof body.error.code === 'number') {
        reject(new ApiError(body.error.code, body.error.message || '上传失败', xhr.status));
      } else {
        reject(new ApiError(0, '服务响应异常', xhr.status));
      }
    };
    xhr.onerror = () => { done = true; reject(new ApiError(0, '无法连接本地服务，请确认服务已启动后重试', null)); };
    xhr.ontimeout = () => { done = true; reject(new ApiError(0, '操作结果未知，请刷新查看最新状态', null)); };
    xhr.onabort = () => { done = true; reject(new ApiError(0, '上传已中止', null)); };
    xhr.send(form);
  });
}

/* ==================== 23 个接口调用函数 ==================== */

/** 1. 简历档案列表 @returns {Promise<Array<ResumeProfile>>} */
function listResumes(signal) {
  return request('/api/v1/resumes', { signal });
}

/** 3. 重命名简历档案 @returns {Promise<ResumeProfile>} */
function renameResume(resumeId, name) {
  return request('/api/v1/resumes/' + encodeURIComponent(resumeId), { method: 'PATCH', body: { name } });
}

/** 4. 设为默认简历 @returns {Promise<ResumeProfile>} */
function setDefaultResume(resumeId) {
  return request('/api/v1/resumes/' + encodeURIComponent(resumeId) + '/default', { method: 'PUT' });
}

/** 5. 删除简历档案 @returns {Promise<null>} */
function deleteResume(resumeId) {
  return request('/api/v1/resumes/' + encodeURIComponent(resumeId), { method: 'DELETE' });
}

/** 6. 求职者档案（意向与联系方式） @returns {Promise<SeekerProfile>} */
function getProfile(signal) {
  return request('/api/v1/profile', { signal });
}

/**
 * 7. 更新求职者档案
 * @param {SeekerProfile} profile
 * @returns {Promise<SeekerProfile>}
 */
function updateProfile(profile) {
  return request('/api/v1/profile', { method: 'PUT', body: profile });
}

/**
 * 8. 添加黑名单
 * @param {'company'|'keyword'} type
 * @param {string} content
 * @returns {Promise<BlacklistEntry>}
 */
function addBlacklist(type, content) {
  return request('/api/v1/blacklist', { method: 'POST', body: { type, content } });
}

/** 9. 黑名单列表 @returns {Promise<Array<BlacklistEntry>>} */
function listBlacklist(signal) {
  return request('/api/v1/blacklist', { signal });
}

/** 10. 移除黑名单 @returns {Promise<null>} */
function removeBlacklist(entryId) {
  return request('/api/v1/blacklist/' + encodeURIComponent(entryId), { method: 'DELETE' });
}

/**
 * 11. 职位筛选列表（page_size 显式传 50，覆盖后端默认 20）
 * @param {{city?: string, salary_min?: number, salary_max?: number, industry?: string, keyword?: string, experience?: string, page?: number, page_size?: number}} [filters]
 * @returns {Promise<PositionPage>}
 */
function listPositions(filters, signal) {
  return request('/api/v1/positions', { query: Object.assign({ page: 1, page_size: 50 }, filters), signal });
}

/**
 * 12. 职位推荐列表（按匹配度降序）
 * @param {number} [topN]
 * @returns {Promise<RecommendationResponse>}
 */
function getRecommendations(topN, signal) {
  return request('/api/v1/recommendations', { query: { top_n: topN || 50 }, signal });
}

/**
 * 13. 设置自动投递匹配阈值
 * @param {number} value - 0-100
 * @returns {Promise<{auto_apply_threshold: number}>}
 */
function setMatchingThreshold(value) {
  return request('/api/v1/matching-settings', { method: 'PUT', body: { auto_apply_threshold: value } });
}

/**
 * 14. 创建投递任务（勾选职位或条件圈选）
 * @param {{position_ids?: Array<string>, filter_condition?: FilterCondition}} req
 * @returns {Promise<CreateTaskResponse>}
 */
function createDeliveryTask(req) {
  return request('/api/v1/delivery-tasks', { method: 'POST', body: req });
}

/** 15. 确认投递任务 @returns {Promise<DeliveryTask>} */
function confirmDeliveryTask(taskId) {
  return request('/api/v1/delivery-tasks/' + encodeURIComponent(taskId) + '/confirm', { method: 'POST' });
}

/** 16. 取消投递任务 @returns {Promise<CancelResponse>} */
function cancelDeliveryTask(taskId) {
  return request('/api/v1/delivery-tasks/' + encodeURIComponent(taskId) + '/cancel', { method: 'POST' });
}

/** 17. 查询单个投递任务 @returns {Promise<DeliveryTask>} */
function getDeliveryTask(taskId, signal) {
  return request('/api/v1/delivery-tasks/' + encodeURIComponent(taskId), { signal });
}

/**
 * 18. 设置每日投递上限
 * @param {number} value - >= 1
 * @returns {Promise<{daily_limit: number}>}
 */
function setDailyLimit(value) {
  return request('/api/v1/delivery-settings', { method: 'PUT', body: { daily_limit: value } });
}

/**
 * 19. 投递记录列表（page_size 显式传 50）
 * @param {{status?: string, platform?: string, since?: string, page?: number, page_size?: number}} [filters]
 * @returns {Promise<RecordPage>}
 */
function listDeliveryRecords(filters, signal) {
  return request('/api/v1/delivery-records', { query: Object.assign({ page: 1, page_size: 50 }, filters), signal });
}

/** 20. 投递统计报告 @returns {Promise<Statistics>} */
function getStatistics(signal) {
  return request('/api/v1/delivery-statistics', { signal });
}

/** 21. 平台列表 @returns {Promise<Array<Platform>>} */
function listPlatforms(signal) {
  return request('/api/v1/platforms', { signal });
}

/**
 * 22. 授予平台授权（凭证纯字符串）
 * @returns {Promise<Platform>}
 */
function authorizePlatform(platformId, credential) {
  return request('/api/v1/platforms/' + encodeURIComponent(platformId) + '/authorization', {
    method: 'POST', body: { credential },
  });
}

/** 23. 撤销平台授权 @returns {Promise<null>} */
function revokePlatform(platformId) {
  return request('/api/v1/platforms/' + encodeURIComponent(platformId) + '/authorization', { method: 'DELETE' });
}

/* ==================== 平台接入治理（真实平台） ==================== */

/** 24. 接入配置列表 @returns {Promise<Array<AccessConfig>>} */
function listAccessConfigs(signal) {
  return request('/api/v1/platform-access', { signal });
}

/** 25. 确认风险告知（幂等） @returns {Promise<null>} */
function confirmAccessRisk(platformId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/risk-confirmation', { method: 'POST' });
}

/** 26. 启用平台 @returns {Promise<{platform_id: string, enabled: boolean}>} */
function enableRealPlatform(platformId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/enable', { method: 'POST' });
}

/** 27. 禁用平台 @returns {Promise<{platform_id: string, enabled: boolean}>} */
function disableRealPlatform(platformId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/disable', { method: 'POST' });
}

/**
 * 28. 设置投递限流（安全上限 30/h）
 * @param {number} ratePerHour
 * @returns {Promise<{platform_id: string, delivery_rate_per_hour: number}>}
 */
function updateRatePolicy(platformId, ratePerHour) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/rate-policy', {
    method: 'PUT', body: { delivery_rate_per_hour: ratePerHour },
  });
}

/** 29. 创建浏览器授权会话 @returns {Promise<AuthSession>} */
function createBrowserAuthorization(platformId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/browser-authorization', { method: 'POST' });
}

/** 30. 轮询浏览器授权会话 @returns {Promise<AuthSession>} */
function pollBrowserAuthorization(platformId, sessionId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/browser-authorization/' + encodeURIComponent(sessionId));
}

/** 31. 取消授权会话 @returns {Promise<null>} */
function cancelBrowserAuthorization(platformId, sessionId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/browser-authorization/' + encodeURIComponent(sessionId) + '/cancel', { method: 'POST' });
}

/** 32. 待处理事件（挑战+风险事件，读取即告知） @returns {Promise<{challenges: Array, risk_events: Array}>} */
function getPendingEvents(signal) {
  return request('/api/v1/platform-access/pending-events', { signal });
}

/** 33. 验证码前往处理 @returns {Promise<{challenge_id: string, status: string, message: string}>} */
function handleCaptchaChallenge(platformId, challengeId) {
  return request('/api/v1/platform-access/' + encodeURIComponent(platformId) + '/captcha-challenges/' + encodeURIComponent(challengeId) + '/handle', { method: 'POST' });
}

/* ==================== AI 智能匹配与招呼语 ==================== */

/** 34. 模型配置列表（Key 不回显，仅 has_api_key） @returns {Promise<Array>} */
function listAiModelConfigs(signal) {
  return request('/api/v1/ai/model-configs', { signal });
}

/** 35. 新建模型配置 @returns {Promise<Object>} */
function createAiModelConfig(config) {
  return request('/api/v1/ai/model-configs', { method: 'POST', body: config });
}

/** 36. 更新模型配置（api_key 缺省=保留密文） @returns {Promise<Object>} */
function updateAiModelConfig(configId, patch) {
  return request('/api/v1/ai/model-configs/' + encodeURIComponent(configId), { method: 'PUT', body: patch });
}

/** 37. 删除模型配置（仅未激活） @returns {Promise<null>} */
function deleteAiModelConfig(configId) {
  return request('/api/v1/ai/model-configs/' + encodeURIComponent(configId), { method: 'DELETE' });
}

/** 38. 连通性测试（draft_key 不落库） @returns {Promise<{status, message, duration_ms}>} */
function testAiModelConfig(configId, draftKey) {
  return request('/api/v1/ai/model-configs/' + encodeURIComponent(configId) + '/test', {
    method: 'POST',
    body: draftKey ? { draft_key: draftKey } : {},
  });
}

/** 39. 激活模型配置（单激活） @returns {Promise<Object>} */
function activateAiModelConfig(configId, force) {
  return request('/api/v1/ai/model-configs/' + encodeURIComponent(configId) + '/activate', {
    method: 'POST',
    body: { force: !!force },
  });
}

/** 40. AI 设置读取 @returns {Promise<Object>} */
function getAiSettings(signal) {
  return request('/api/v1/ai/settings', { signal });
}

/** 41. AI 设置更新 @returns {Promise<Object>} */
function updateAiSettings(settings) {
  return request('/api/v1/ai/settings', { method: 'PUT', body: settings });
}

/** 42. AI 状态（四态 + 激活配置名） @returns {Promise<{state, message, active_config_name, provider}>} */
function getAiStatus(signal) {
  return request('/api/v1/ai/status', { signal });
}

/** 43. 发起 AI 匹配批任务（202 毫秒级；rejected 不报错） @returns {Promise<Object>} */
function createAiMatchingTask(topN) {
  return request('/api/v1/ai/matching-tasks', { method: 'POST', query: { top_n: topN || 50 } });
}

/** 44. 查询 AI 匹配任务（增量结果，轮询 3-5s） @returns {Promise<Object>} */
function getAiMatchingTask(taskId, signal) {
  return request('/api/v1/ai/matching-tasks/' + encodeURIComponent(taskId), { signal });
}

/** 45. 准备招呼语（202 毫秒级，后台生成） @returns {Promise<Object>} */
function prepareGreetings(deliveryTaskId) {
  return request('/api/v1/ai/delivery-tasks/' + encodeURIComponent(deliveryTaskId) + '/greetings/prepare', { method: 'POST' });
}

/** 46. 查询招呼语（渐进） @returns {Promise<{all_ready, status, items}>} */
function getGreetings(deliveryTaskId, signal) {
  return request('/api/v1/ai/delivery-tasks/' + encodeURIComponent(deliveryTaskId) + '/greetings', { signal });
}

/** 47. 编辑招呼语（43005/43006 映射） @returns {Promise<Object>} */
function editGreeting(deliveryTaskId, positionId, text) {
  return request(
    '/api/v1/ai/delivery-tasks/' + encodeURIComponent(deliveryTaskId) + '/greetings/' + encodeURIComponent(positionId),
    { method: 'PUT', body: { text } }
  );
}

/** 健康探测（启动判定） @returns {Promise<{status: string}>} */
function checkHealth() {
  return request('/health', { timeoutMs: 5000 });
}