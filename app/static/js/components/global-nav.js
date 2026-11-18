/** GlobalNav 全局导航：5 入口常驻、当前页高亮、授权异常入口徽标（SVG 图标，无 emoji） */

const NAV_ICONS = {
  resumes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6"/><path d="M9 17h6"/></svg>',
  positions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
  tasks: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13"/><path d="M22 2 15 22 11 15 2 11z"/></svg>',
  records: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="M7 17v-6"/><path d="M12 17V7"/><path d="M17 17v-9"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 12 17 7"/><path d="M12 12v-6"/></svg>',
  ai: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M9 14h.01"/><path d="M15 14h.01"/><path d="M9 18h6"/></svg>',
};

const BRAND_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>';

const GlobalNav = {
  props: {
    current: { type: String, default: '#/resumes' },
    alert: { type: Boolean, default: false },
    aiState: { type: String, default: '' },
  },
  emits: ['change'],
  data() {
    return {
      navs: [
        { path: '#/resumes', label: '简历管理', icon: NAV_ICONS.resumes },
        { path: '#/positions', label: '职位推荐', icon: NAV_ICONS.positions },
        { path: '#/tasks', label: '投递任务', icon: NAV_ICONS.tasks },
        { path: '#/records', label: '投递记录', icon: NAV_ICONS.records },
        { path: '#/settings', label: '平台授权与设置', icon: NAV_ICONS.settings },
        { path: '#/ai-config', label: 'AI 模型配置', icon: NAV_ICONS.ai },
      ],
    };
  },
  template: `
    <nav class="global-nav">
      <div class="nav-brand">
        <span v-html="brandIcon" style="display:inline-flex"></span>
        <span>就业海投简历</span>
      </div>
      <div class="nav-links">
        <a
          v-for="n in navs"
          :key="n.path"
          href="#"
          :class="['nav-link', { active: current === n.path }]"
          @click.prevent="$emit('change', n.path)"
        >
          <span v-html="n.icon" style="display:inline-flex"></span>
          <span>{{ n.label }}</span>
          <span v-if="alert && n.path === '#/settings'" class="nav-badge" title="平台授权异常">!</span>
          <span v-if="aiState && aiState !== 'off' && aiState !== 'ready' && n.path === '#/ai-config'" class="nav-badge" title="AI 服务异常">!</span>
          <span v-if="aiState === 'ready' && n.path === '#/ai-config'" class="badge badge-green" style="margin-left:4px">AI</span>
        </a>
      </div>
    </nav>
  `,
  computed: {
    brandIcon() {
      return BRAND_ICON;
    },
  },
};