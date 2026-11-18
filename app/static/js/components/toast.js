/** Toast 操作反馈：单击类操作 1 秒内反馈；失败类停留时间由 store 控制（加长保证错误码可读） */

const Toast = {
  props: {
    message: { type: String, default: '' },
    type: { type: String, default: 'success' },
  },
  emits: ['close'],
  template: `
    <div
      :class="['toast', type === 'failure' ? 'toast-failure' : 'toast-success']"
      @click="$emit('close')"
    >{{ message }}</div>
  `,
};