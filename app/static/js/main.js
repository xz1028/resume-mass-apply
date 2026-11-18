/**
 * 应用入口：创建 Vue 应用、注册路由、挂载；启动健康探测与首页判定。
 * - 探测失败 → 连接失败页（不进入任何功能页面）
 * - 探测成功 → 并行拉取简历与平台信号；无简历 → 简历管理页，否则 → 职位推荐页
 */

const { createApp, computed: vueComputed } = Vue;

const App = {
  components: {
    GlobalNav,
    Toast,
    ResumePage,
    PositionPage,
    TaskPage,
    RecordPage,
    PlatformPage,
  },
  setup() {
    const currentView = vueComputed(() => routeTable[currentRoute.value] || ResumePage);

    function onChangeNav(path) {
      navigate(path);
    }

    function onRetryConnection() {
      boot();
    }

    return {
      store,
      hasResume,
      authAlert,
      currentRoute,
      currentView,
      toasts,
      dismissToast,
      onChangeNav,
      onRetryConnection,
    };
  },
  template: `
    <div v-if="store.connectionState === 'offline'" class="offline-page">
      <h1>无法连接本地服务</h1>
      <p>请确认服务已启动后重试</p>
      <button class="btn btn-primary" @click="onRetryConnection">重试</button>
    </div>
    <div v-else-if="store.connectionState === 'checking'" class="offline-page">
      <p>正在连接本地服务，请稍候…</p>
    </div>
    <div v-else class="app-shell">
      <global-nav :current="currentRoute" :alert="authAlert" @change="onChangeNav"></global-nav>
      <main class="app-content">
        <component :is="currentView" :key="currentRoute"></component>
      </main>
      <div class="toast-container">
        <toast
          v-for="t in toasts"
          :key="t.id"
          :message="t.message"
          :type="t.type"
          @close="dismissToast(t.id)"
        ></toast>
      </div>
    </div>
  `,
};

/** 启动判定：健康探测 → 全局信号 → 首页跳转 */
async function boot() {
  store.connectionState = 'checking';
  try {
    await checkHealth();
    store.connectionState = 'online';
    await refreshGlobalSignals();
    if (!location.hash) {
      navigate(store.resumeCount === 0 ? '#/resumes' : '#/positions');
    }
  } catch (e) {
    store.connectionState = 'offline';
  }
}

registerRoutes([
  { path: '#/resumes', view: ResumePage },
  { path: '#/positions', view: PositionPage },
  { path: '#/tasks', view: TaskPage },
  { path: '#/records', view: RecordPage },
  { path: '#/settings', view: PlatformPage },
]);

const app = createApp(App);
app.mount('#app');
boot();