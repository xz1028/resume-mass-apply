/** EmptyState 空状态：引导文案与跳转入口成对出现（SVG 图标，无 emoji） */

const EMPTY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M8.5 11h5" opacity="0.6"/></svg>';

const EmptyState = {
  props: {
    message: { type: String, default: '暂无数据' },
    actionText: { type: String, default: '' },
  },
  emits: ['action'],
  computed: {
    emptyIcon() {
      return EMPTY_ICON;
    },
  },
  template: `
    <div class="empty-state">
      <div class="empty-icon" v-html="emptyIcon"></div>
      <div class="empty-message">{{ message }}</div>
      <button v-if="actionText" class="btn btn-primary" @click="$emit('action')">{{ actionText }}</button>
    </div>
  `,
};