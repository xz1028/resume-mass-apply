/** 投递记录与统计页：记录筛选分页、状态时效提示、统计视图（自绘 SVG 趋势）、分区独立降级 */

const RecordPage = {
  components: { Pagination, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    const { reactive, computed, onMounted, onUnmounted } = Vue;

    /* ---------- 记录列表（独立 ViewState） ---------- */
    const filters = reactive({ status: '', platform: '', since: '' });
    const recordsState = reactive({
      phase: 'loading', items: [], total: 0, page: 1, pageSize: 50,
    });

    let recordsController = null;

    async function loadRecords() {
      if (recordsController) recordsController.abort();
      recordsController = new AbortController();
      recordsState.phase = 'loading';
      const query = { page: recordsState.page, page_size: recordsState.pageSize };
      if (filters.status) query.status = filters.status;
      if (filters.platform) query.platform = filters.platform;
      if (filters.since) query.since = filters.since;
      try {
        const data = await listDeliveryRecords(query, recordsController.signal);
        recordsState.items = data.items || [];
        recordsState.total = data.total || 0;
        recordsState.phase = recordsState.total > 0 ? 'ready' : 'empty';
      } catch (e) {
        if (e && e.name === 'AbortError') return;
        recordsState.phase = 'error';
      }
    }

    function onFilterChange() {
      recordsState.page = 1;
      loadRecords();
    }

    function onPageChange(page, pageSize) {
      recordsState.page = page;
      recordsState.pageSize = pageSize;
      loadRecords();
    }

    const STATUS_OPTIONS = [
      { value: '', label: '全部状态' },
      { value: 'pending', label: '待投递' },
      { value: 'delivered', label: '已投递' },
      { value: 'viewed', label: '已查看' },
      { value: 'interview_invited', label: '面试邀请' },
      { value: 'rejected', label: '不合适' },
      { value: 'failed', label: '投递失败' },
      { value: 'expired', label: '已过期' },
    ];

    /* ---------- 统计区（独立 ViewState，与记录区互不影响） ---------- */
    const statsState = reactive({ phase: 'loading', data: null });

    async function loadStats() {
      statsState.phase = 'loading';
      try {
        const data = await getStatistics();
        statsState.data = data;
        statsState.phase = 'ready';
      } catch (e) {
        statsState.phase = 'error';
      }
    }

    const statusDistItems = computed(() => {
      const dist = (statsState.data && statsState.data.status_distribution) || {};
      return Object.keys(dist).map((key) => {
        const mapped = deliveryStatusLabel(key);
        return { key, label: mapped.label, tone: mapped.tone, count: dist[key] };
      });
    });

    const platformDistText = computed(() => {
      const dist = (statsState.data && statsState.data.platform_distribution) || {};
      return Object.keys(dist).map((p) => p + ' × ' + dist[p]).join('，') || '暂无';
    });

    const TREND_W = 560;
    const TREND_H = 150;
    const TREND_PAD = 26;

    const trendBars = computed(() => {
      const days = (statsState.data && statsState.data.recent_7_days) || [];
      const max = Math.max(1, ...days.map((d) => d.count));
      const slot = (TREND_W - TREND_PAD * 2) / Math.max(days.length, 1);
      const barW = Math.max(10, Math.floor(slot) - 10);
      return days.map((d, i) => {
        const x = TREND_PAD + i * slot + 5;
        const h = Math.max(2, Math.round((d.count / max) * (TREND_H - TREND_PAD * 2)));
        return {
          x, y: TREND_H - TREND_PAD - h, w: barW, h,
          label: (d.date || '').slice(5), count: d.count,
        };
      });
    });

    onMounted(() => {
      loadRecords();
      loadStats();
    });

    onUnmounted(() => {
      if (recordsController) recordsController.abort();
    });

    return {
      filters, recordsState, loadRecords, onFilterChange, onPageChange, STATUS_OPTIONS,
      statsState, loadStats, statusDistItems, platformDistText, trendBars,
      TREND_W, TREND_H, TREND_PAD,
      deliveryStatusLabel, formatTime, relativeTime, isStale,
      navigate,
    };
  },
  template: `
    <div>
      <!-- 统计区（独立降级：失败不影响记录列表） -->
      <div class="card">
        <div class="card-title">投递统计</div>
        <loading-skeleton v-if="statsState.phase === 'loading'" :rows="3"></loading-skeleton>
        <error-banner
          v-else-if="statsState.phase === 'error'"
          message="统计数据加载失败，点击重试"
          @retry="loadStats"
        ></error-banner>
        <template v-else>
          <div class="stat-grid">
            <div class="stat-card">
              <div class="stat-value">{{ statsState.data ? statsState.data.total : 0 }}</div>
              <div class="stat-label">总投递数</div>
            </div>
            <div v-for="item in statusDistItems" :key="item.key" class="stat-card">
              <div class="stat-value" :style="{ color: 'var(--tone-' + item.tone + ')' }">{{ item.count }}</div>
              <div class="stat-label">{{ item.label }}</div>
            </div>
          </div>
          <p class="muted" style="margin-bottom:10px">各平台分布：{{ platformDistText }}</p>
          <svg class="trend-chart" :viewBox="'0 0 ' + TREND_W + ' ' + TREND_H" preserveAspectRatio="xMidYMid meet">
            <g v-for="b in trendBars" :key="b.label">
              <rect class="trend-bar" :x="b.x" :y="b.y" :width="b.w" :height="b.h"></rect>
              <text class="trend-count" :x="b.x + b.w / 2" :y="b.y - 4" text-anchor="middle">{{ b.count }}</text>
              <text class="trend-label" :x="b.x + b.w / 2" :y="TREND_H - 8" text-anchor="middle">{{ b.label }}</text>
            </g>
          </svg>
          <p class="muted">近 7 天投递趋势</p>
        </template>
      </div>

      <!-- 记录列表 -->
      <div class="card">
        <div class="card-title">投递记录</div>
        <div class="row" style="margin-bottom:14px">
          <select class="select" style="width:140px" v-model="filters.status" @change="onFilterChange">
            <option v-for="opt in STATUS_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <input class="input" style="width:160px" v-model="filters.platform" placeholder="平台 ID" @input="onFilterChange">
          <input class="input" style="width:160px" type="date" v-model="filters.since" @change="onFilterChange">
        </div>

        <loading-skeleton v-if="recordsState.phase === 'loading'" :rows="6"></loading-skeleton>
        <error-banner
          v-else-if="recordsState.phase === 'error'"
          message="记录加载失败，请重试"
          @retry="loadRecords"
        ></error-banner>
        <empty-state
          v-else-if="recordsState.phase === 'empty'"
          message="暂无投递记录，去职位推荐页发起第一次投递吧"
          action-text="去职位推荐页"
          @action="navigate('#/positions')"
        ></empty-state>
        <template v-else>
          <table class="table">
            <thead>
              <tr><th>职位名称</th><th>公司</th><th>平台</th><th>投递时间</th><th>当前状态</th><th>使用简历</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in recordsState.items" :key="r.record_id">
                <td>{{ r.position_title }}</td>
                <td>{{ r.company }}</td>
                <td>{{ r.platform_id }}</td>
                <td>{{ r.delivered_at ? formatTime(r.delivered_at) : '-' }}</td>
                <td>
                  <span :class="['badge', 'badge-' + deliveryStatusLabel(r.status).tone]">
                    {{ deliveryStatusLabel(r.status).label }}
                  </span>
                  <div class="muted">状态更新时间：{{ relativeTime(r.status_updated_at) }}</div>
                  <div v-if="isStale(r.status_updated_at, 12)" class="form-hint" style="color:var(--tone-orange)">
                    状态较久未同步
                  </div>
                </td>
                <td class="muted">{{ r.resume_snapshot ? r.resume_snapshot.name : '-' }}</td>
              </tr>
            </tbody>
          </table>
          <pagination
            :page="recordsState.page"
            :page-size="recordsState.pageSize"
            :total="recordsState.total"
            @change="onPageChange"
          ></pagination>
        </template>
      </div>
    </div>
  `,
};