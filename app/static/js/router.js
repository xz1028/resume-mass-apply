/**
 * hash 路由器：5 个一级页面、未匹配重定向 #/resumes、编程跳转。
 * 页面切换通过 Vue 动态组件 :key 重建视图，旧视图 onUnmounted 自动清理
 * （中止在途请求、停止轮询），无需额外清理钩子注册。
 */

const { ref: routerRef } = Vue;

/** @type {Object<string, Object>} path -> 视图组件 */
const routeTable = {};

function normalizeHash(hash) {
  const path = hash || '#/resumes';
  return routeTable[path] ? path : '#/resumes';
}

/** 当前路由（响应式） */
const currentRoute = routerRef('#/resumes');

/**
 * 注册路由表。
 * @param {Array<{path: string, view: Object}>} routes
 */
function registerRoutes(routes) {
  routes.forEach((r) => { routeTable[r.path] = r.view; });
  currentRoute.value = normalizeHash(location.hash);
}

/**
 * 编程跳转。
 * @param {string} path - 如 '#/resumes'
 */
function navigate(path) {
  if (location.hash === path) {
    currentRoute.value = path;
  } else {
    location.hash = path;
  }
}

window.addEventListener('hashchange', () => {
  const path = location.hash || '#/resumes';
  if (!routeTable[path]) {
    location.hash = '#/resumes'; // 未匹配 hash 重定向
    return;
  }
  currentRoute.value = path;
});