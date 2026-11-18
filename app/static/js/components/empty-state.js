/** EmptyState 空状态：引导文案与跳转入口成对出现 */

const EmptyState = {
  props: {
    message: { type: String, default: '暂无数据' },
    actionText: { type: String, default: '' },
  },
  emits: ['action'],
  template: `
    <div class="empty-state">
      <div class="empty-icon">○</div>
      <div class="empty-message">{{ message }}</div>
      <button v-if="actionText" class="btn btn-primary" @click="$emit('action')">{{ actionText }}</button>
    </div>
  `,
};