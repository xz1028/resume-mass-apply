/** GlobalNav 全局导航：5 入口常驻、当前页高亮、授权异常入口徽标 */

const GlobalNav = {
  props: {
    current: { type: String, default: '#/resumes' },
    alert: { type: Boolean, default: false },
  },
  emits: ['change'],
  data() {
    return {
      navs: [
        { path: '#/resumes', label: '简历管理' },
        { path: '#/positions', label: '职位推荐' },
        { path: '#/tasks', label: '投递任务' },
        { path: '#/records', label: '投递记录' },
        { path: '#/settings', label: '平台授权与设置' },
      ],
    };
  },
  template: `
    <nav class="global-nav">
      <div class="nav-brand">就业海投简历</div>
      <div class="nav-links">
        <a
          v-for="n in navs"
          :key="n.path"
          href="#"
          :class="['nav-link', { active: current === n.path }]"
          @click.prevent="$emit('change', n.path)"
        >
          {{ n.label }}
          <span v-if="alert && n.path === '#/settings'" class="nav-badge" title="平台授权异常">!</span>
        </a>
      </div>
    </nav>
  `,
};