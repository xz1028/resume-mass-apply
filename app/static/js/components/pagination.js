/** Pagination 分页：页码从 1 起、pageSize 选项固定 20/50/100、默认 50、展示总条数 */

const Pagination = {
  props: {
    page: { type: Number, required: true },
    pageSize: { type: Number, required: true },
    total: { type: Number, required: true },
  },
  emits: ['change'],
  computed: {
    totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize));
    },
    pages() {
      const list = [];
      const total = this.totalPages;
      const cur = this.page;
      const start = Math.max(1, cur - 2);
      const end = Math.min(total, cur + 2);
      if (start > 1) {
        list.push(1);
        if (start > 2) list.push('...');
      }
      for (let i = start; i <= end; i++) list.push(i);
      if (end < total) {
        if (end < total - 1) list.push('...');
        list.push(total);
      }
      return list;
    },
  },
  methods: {
    changePage(p) {
      if (typeof p === 'number' && p >= 1 && p <= this.totalPages && p !== this.page) {
        this.$emit('change', p, this.pageSize);
      }
    },
    changeSize(event) {
      const size = Number(event.target.value);
      if (size !== this.pageSize) this.$emit('change', 1, size);
    },
  },
  template: `
    <div class="pagination">
      <span class="page-total">共 {{ total }} 条</span>
      <button class="page-btn" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
      <template v-for="(p, i) in pages" :key="i">
        <span v-if="p === '...'" class="page-ellipsis">…</span>
        <button v-else :class="['page-btn', { active: p === page }]" @click="changePage(p)">{{ p }}</button>
      </template>
      <button class="page-btn" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
      <select class="select page-size-select" :value="pageSize" @change="changeSize">
        <option :value="20">20 条/页</option>
        <option :value="50">50 条/页</option>
        <option :value="100">100 条/页</option>
      </select>
    </div>
  `,
};