/**
 * 全局状态：连接状态、简历档案数、授权提醒信号、Toast 通道、清单确认传递。
 */

const { reactive, ref, computed } = Vue;

const store = reactive({
  /** @type {'checking'|'online'|'offline'} */
  connectionState: 'checking',
  resumeCount: 0,
  /** @type {Array<Platform>} */
  platforms: [],
  /** @type {{state: 'off'|'ready'|'degraded_cooldown'|'degraded_transient', message: string, active_config_name: string|null}|null} */
  aiStatus: null,
});

/** 是否已有简历档案（首页判定与投递入口置灰依据） */
const hasResume = computed(() => store.resumeCount > 0);

/** 授权提醒：存在过期或降级平台时为真，驱动导航徽标 */
const authAlert = computed(() =>
  store.platforms.some((p) => p.auth_status === 'expired' || p.degraded === true)
);

/** 并行拉取简历列表与平台状态，更新全局信号（简历增删、授权变更后调用） */
async function refreshGlobalSignals() {
  const [resumes, platforms, aiStatus] = await Promise.all([
    listResumes().catch(() => null),
    listPlatforms().catch(() => null),
    (typeof getAiStatus === 'function' ? getAiStatus().catch(() => null) : Promise.resolve(null)),
  ]);
  if (Array.isArray(resumes)) store.resumeCount = resumes.length;
  if (Array.isArray(platforms)) store.platforms = platforms;
  if (aiStatus && typeof aiStatus.state === 'string') store.aiStatus = aiStatus;
}

/* ---------- Toast 全局通道 ---------- */

const toasts = reactive([]);
let toastSeq = 0;

/**
 * @param {string} message
 * @param {'success'|'failure'} [type] - 失败类停留时间加长，保证错误码可读
 */
function showToast(message, type) {
  const toastType = type || 'success';
  const id = ++toastSeq;
  toasts.push({ id, message, type: toastType });
  const duration = toastType === 'failure' ? 6000 : 2500;
  setTimeout(() => dismissToast(id), duration);
}

function dismissToast(id) {
  const idx = toasts.findIndex((t) => t.id === id);
  if (idx >= 0) toasts.splice(idx, 1);
}

/* ---------- 投递清单确认传递（职位推荐页 → 投递任务页） ---------- */

/** @type {import('./types.js').CreateTaskResponse|null} */
const pendingChecklist = ref(null);