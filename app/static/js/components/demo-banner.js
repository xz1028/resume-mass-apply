/** 演示模式横幅（tasks 2.7）：active 时固定定位叠加展示"演示数据"标识 + 退出入口。
 * 独立 DOM 注入，不修改既有 5 页面 views 文件与字段语义；退出复用 Modal 二次确认。 */

const DemoBanner = {
  components: { Modal },
  data() {
    return {
      active: false,
      state: '',
      summary: { resumes: 0, records: 0, positions: 0 },
      showConfirm: false,
      resetting: false,
      dismissed: false,
    };
  },
  computed: {
    bannerText() {
      return '当前为演示模式：数据为虚构演示数据（' + this.summary.positions + ' 个职位 / ' + this.summary.records + ' 条投递记录），仅用于体验软件功能';
    },
  },
  async mounted() {
    try {
      const data = await request('/api/v1/demo-mode');
      this.active = !!data.active;
      this.state = data.state || '';
      this.summary = data.clearable_summary || { resumes: 0, records: 0, positions: 0 };
    } catch (e) { /* 演示状态查询失败静默：不影响正常使用 */ }
  },
  methods: {
    askExit() {
      this.showConfirm = true;
    },
    async confirmExit() {
      this.showConfirm = false;
      this.resetting = true;
      try {
        const result = await request('/api/v1/demo-mode/reset', { method: 'POST' });
        showToast('已退出演示模式：清除演示简历 ' + result.resumes + ' 份、投递记录 ' + result.records + ' 条、演示职位 ' + result.positions + ' 个');
        window.location.reload();
      } catch (e) {
        showToast(errorText(e), 'failure');
      } finally {
        this.resetting = false;
      }
    },
  },
  template: `
    <div v-if="active && !dismissed" style="position:fixed;top:0;left:0;right:0;z-index:250;
      background:#4338ca;color:#fff;display:flex;align-items:center;gap:12px;
      padding:8px 20px;font-size:13px;flex-wrap:wrap">
      <span style="font-weight:600">演示模式</span>
      <span style="opacity:.9">{{ bannerText }}</span>
      <span style="flex:1"></span>
      <button class="btn btn-sm" style="background:rgba(255,255,255,.16);border-color:rgba(255,255,255,.4);color:#fff"
        @click="dismissed = true" title="本次会话隐藏横幅">隐藏</button>
      <button class="btn btn-sm" style="background:#fff;color:#4338ca;border-color:#fff"
        :disabled="resetting" @click="askExit">{{ resetting ? '清除中…' : '退出演示模式' }}</button>
    </div>
    <modal
      v-if="showConfirm"
      title="退出演示模式"
      :body="'将清除全部演示数据：演示简历 ' + summary.resumes + ' 份、演示投递任务与 ' + summary.records + ' 条记录、' + summary.positions + ' 个演示职位。\\n\\n该操作不可恢复；您的平台授权与真实数据不受影响。确认退出并清除？'"
      confirm-text="确认退出并清除"
      :danger="true"
      @confirm="confirmExit"
      @cancel="showConfirm = false"
    ></modal>
  `,
};
/** 浏览器组件预检守卫（tasks 2.7b）：启用真实平台前调用；组件缺失时弹一次性获取引导。
 * 返回 true = 组件可用（继续启用流程）；false = 已弹引导或查询失败（不阻断其余功能）。 */
let _browserComponentGuardShown = false;
async function browserComponentGuard() {
  try {
    const data = await request('/api/v1/platform-access/browser-component');
    if (data && data.available) return true;
    if (_browserComponentGuardShown) return false;
    _browserComponentGuardShown = true;
    showToast((data && data.guide) || '浏览器自动化组件未安装，无法启用真实平台投递', 'failure');
    return false;
  } catch (e) {
    return true; // 查询失败不阻断：交给后端启用链路自行校验
  }
}