/** LoadingSkeleton 加载骨架：数据区加载期间反馈，禁止无反馈空白 */

const LoadingSkeleton = {
  props: {
    rows: { type: Number, default: 5 },
  },
  template: `
    <div class="skeleton">
      <div v-for="i in rows" :key="i" class="skeleton-line" :style="{ width: (60 + ((i * 13) % 40)) + '%' }"></div>
    </div>
  `,
};