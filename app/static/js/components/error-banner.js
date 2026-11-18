/** ErrorBanner 区域错误：仅用于读操作失败区域（写操作失败走 Toast），支持一键重试 */

const ErrorBanner = {
  props: {
    message: { type: String, default: '加载失败' },
  },
  emits: ['retry'],
  template: `
    <div class="error-banner">
      <span>{{ message }}</span>
      <button class="btn btn-sm" @click="$emit('retry')">重试</button>
    </div>
  `,
};