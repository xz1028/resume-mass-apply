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

/** 健康探测（启动判定） @returns {Promise<{status: string}>} */
function checkHealth() {
  return request('/health', { timeoutMs: 5000 });
}