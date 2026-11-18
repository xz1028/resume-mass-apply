/** Modal 二次确认框：高危操作统一确认入口，body 强制承载操作后果说明 */

const Modal = {
  props: {
    title: { type: String, default: '请确认' },
    body: { type: String, default: '' },
    confirmText: { type: String, default: '确认' },
    danger: { type: Boolean, default: false },
  },
  emits: ['confirm', 'cancel'],
  template: `
    <div class="modal-mask" @click.self="$emit('cancel')">
      <div class="modal-box">
        <h3 class="modal-title">{{ title }}</h3>
        <p class="modal-body">{{ body }}</p>
        <div class="modal-actions">
          <button class="btn" @click="$emit('cancel')">取消</button>
          <button
            :class="['btn', danger ? 'btn-danger' : 'btn-primary']"
            @click="$emit('confirm')"
          >{{ confirmText }}</button>
        </div>
      </div>
    </div>
  `,
};