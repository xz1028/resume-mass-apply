/**
 * 展示映射层：状态中文标签、错误码文案、格式化函数。
 * 枚举键名与 app/domain/models.py 逐字一致；未知枚举兜底"未知状态"（禁止透出英文原文）。
 */

const DELIVERY_STATUS_MAP = {
  pending: { label: '待投递', tone: 'gray' },
  delivered: { label: '已投递', tone: 'blue' },
  viewed: { label: '已查看', tone: 'cyan' },
  interview_invited: { label: '面试邀请', tone: 'green' },
  rejected: { label: '不合适', tone: 'orange' },
  failed: { label: '投递失败', tone: 'red' },
  expired: { label: '已过期', tone: 'gray' },
};

const TASK_STATUS_MAP = {
  pending_confirm: { label: '待确认', tone: 'blue' },
  executing: { label: '执行中', tone: 'cyan' },
  completed: { label: '已完成', tone: 'green' },
  cancelled: { label: '已取消', tone: 'gray' },
};

const AUTH_STATUS_MAP = {
  authorized: { label: '已授权', tone: 'green' },
  expired: { label: '已过期', tone: 'orange' },
  unauthorized: { label: '未授权', tone: 'gray' },
};

const BLACKLIST_TYPE_MAP = {
  company: '公司',
  keyword: '职位关键词',
};

const UNKNOWN_LABEL = { label: '未知状态', tone: 'gray' };

/** 投递状态 → 中文标签 + 视觉类别 */
function deliveryStatusLabel(v) {
  return DELIVERY_STATUS_MAP[v] || UNKNOWN_LABEL;
}

/** 任务状态 → 中文标签 + 视觉类别 */
function taskStatusLabel(v) {
  return TASK_STATUS_MAP[v] || UNKNOWN_LABEL;
}

/** 授权状态 → 中文标签 + 视觉类别 */
function authStatusLabel(v) {
  return AUTH_STATUS_MAP[v] || UNKNOWN_LABEL;
}

/** 黑名单类型 → 中文标签 */
function blacklistTypeLabel(v) {
  return BLACKLIST_TYPE_MAP[v] || '未知类型';
}

/**
 * 错误码 → 界面文案（含错误码尾注与后续操作建议）。
 * @param {ApiError|{code:number, message:string}} err
 * @param {string} [scene] - 场景标识（如 'upload' / 'form'），支持同码分场景
 * @returns {string}
 */
function errorText(err, scene) {
  const code = err && typeof err.code === 'number' ? err.code : 0;
  const raw = (err && err.message) || '';
  switch (code) {
    case 40001:
      return '仅支持 PDF 或 Word 格式（错误码 40001）';
    case 40002:
      return '文件大小超过限制（20MB）（错误码 40002）';
    case 40003:
      return scene === 'form'
        ? '参数非法，请检查输入（错误码 40003）'
        : '文件无法识别，请确认文件完整性后重新上传（错误码 40003）';
    case 40004:
      return '已存在同名简历档案，请更换名称（错误码 40004）';
    case 40901:
      return (raw || '该职位已于近期投递过') + '（错误码 40901）';
    case 40902:
      return (raw || '已达今日投递上限') + '，可在投递设置中调整（错误码 40902）';
    case 40903:
      return '任务状态已变化，请刷新后查看（错误码 40903）';
    case 41001:
      return '授权凭证无效，请检查后重试（错误码 41001）';
    case 41002:
      return '平台限流/风控拦截，请稍后再试（错误码 41002）';
    case 41003:
      return '平台暂不可用，请稍后再试（错误码 41003）';
    case 40401:
      return '资源不存在或已被删除，请刷新（错误码 40401）';
    default:
      if (/无法连接/.test(raw)) return raw;
      if (/操作结果未知/.test(raw)) return raw;
      return raw ? raw + '（错误码 ' + code + '）' : '操作失败，请稍后重试';
  }
}

/** 文件大小可读单位 */
function formatSize(bytes) {
  if (typeof bytes !== 'number' || bytes < 0) return '-';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/** ISO 时间 → YYYY-MM-DD HH:mm */
function formatTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '-';
  const pad = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

/** ISO 时间 → 相对时间（"N 小时前"） */
function relativeTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '-';
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return formatTime(iso);
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return minutes + ' 分钟前';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + ' 小时前';
  const days = Math.floor(hours / 24);
  if (days < 30) return days + ' 天前';
  return formatTime(iso);
}

/** 薪资范围：空 → "面议" */
function salaryText(min, max) {
  if (min == null && max == null) return '面议';
  const fmt = (v) => (v >= 1000 ? (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + 'K' : String(v));
  if (min != null && max != null) return fmt(min) + '-' + fmt(max);
  if (min != null) return fmt(min) + ' 以上';
  return fmt(max) + ' 以下';
}

/** 距今超过指定小时数（用于状态时效提示，>12 小时） */
function isStale(iso, hours) {
  if (!iso) return false;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return false;
  return Date.now() - d.getTime() > hours * 3600 * 1000;
}
/* ---------- 筛选预设选项（BOSS 直聘风格选择式交互） ---------- */

/** 城市选项：value '' = 全部城市；前 10 位为默认展示的热门城市（精确匹配，值即城市名） */
const FILTER_CITY_OPTIONS = [
  { label: '全部城市', value: '' },
  { label: '北京', value: '北京' },
  { label: '上海', value: '上海' },
  { label: '深圳', value: '深圳' },
  { label: '广州', value: '广州' },
  { label: '杭州', value: '杭州' },
  { label: '成都', value: '成都' },
  { label: '武汉', value: '武汉' },
  { label: '南京', value: '南京' },
  { label: '西安', value: '西安' },
  { label: '长沙', value: '长沙' },
  { label: '苏州', value: '苏州' },
  { label: '东莞', value: '东莞' },
  { label: '佛山', value: '佛山' },
  { label: '重庆', value: '重庆' },
  { label: '郑州', value: '郑州' },
  { label: '宁波', value: '宁波' },
  { label: '厦门', value: '厦门' },
  { label: '青岛', value: '青岛' },
  { label: '天津', value: '天津' },
  { label: '济南', value: '济南' },
  { label: '合肥', value: '合肥' },
  { label: '福州', value: '福州' },
  { label: '珠海', value: '珠海' },
];
const FILTER_CITY_HOT_COUNT = 10;

/** 薪资档位：min/max 为元/月（null = 该边界不限）；「不限」两值均不传 */
const FILTER_SALARY_OPTIONS = [
  { label: '不限', value: '', min: null, max: null },
  { label: '3K以下', value: '3K以下', min: null, max: 3000 },
  { label: '3-5K', value: '3-5K', min: 3000, max: 5000 },
  { label: '5-10K', value: '5-10K', min: 5000, max: 10000 },
  { label: '10-20K', value: '10-20K', min: 10000, max: 20000 },
  { label: '20-50K', value: '20-50K', min: 20000, max: 50000 },
  { label: '50K以上', value: '50K以上', min: 50000, max: null },
];

/** 行业选项：精确匹配，值即行业名 */
const FILTER_INDUSTRY_OPTIONS = [
  { label: '不限', value: '' },
  { label: '互联网', value: '互联网' },
  { label: '金融', value: '金融' },
  { label: '教育', value: '教育' },
  { label: '医疗', value: '医疗' },
  { label: '电商', value: '电商' },
  { label: '游戏', value: '游戏' },
  { label: '硬件', value: '硬件' },
  { label: '制造业', value: '制造业' },
  { label: '房地产', value: '房地产' },
  { label: '咨询', value: '咨询' },
  { label: '传媒', value: '传媒' },
  { label: '物流', value: '物流' },
];

/** 经验档位：param 必须为后端 experience_req 实际取值的子串（contains 匹配） */
const FILTER_EXPERIENCE_OPTIONS = [
  { label: '不限', value: '', param: '' },
  { label: '应届', value: '应届', param: '应届' },
  { label: '1-3年', value: '1-3年', param: '1-3' },
  { label: '3-5年', value: '3-5年', param: '3-5' },
  { label: '5-10年', value: '5-10年', param: '5-10' },
  { label: '10年以上', value: '10年以上', param: '10' },
];

/** 热门职位关键词快捷标签 */
const FILTER_KEYWORD_SHORTCUTS = ['Java', 'Python', '前端', '测试', '产品', '运营', '算法', '数据分析'];

/** 薪资档位 → 查询参数（未选/不限返回空对象，不产生任何参数） */
function salaryTierParams(value) {
  const tier = FILTER_SALARY_OPTIONS.find((t) => t.value === value);
  if (!tier) return {};
  const params = {};
  if (tier.min != null) params.salary_min = tier.min;
  if (tier.max != null) params.salary_max = tier.max;
  return params;
}

/** 经验档位 → 查询参数（未选/不限返回空对象） */
function experienceTierParams(value) {
  const tier = FILTER_EXPERIENCE_OPTIONS.find((t) => t.value === value);
  if (!tier || !tier.param) return {};
  return { experience: tier.param };
}