/** 职位推荐页：筛选（防抖+竞态）、职位/推荐双视图、匹配度、阈值设置、勾选批量投递、快捷拉黑 */

const PositionPage = {
  components: { Pagination, EmptyState, LoadingSkeleton, ErrorBanner, Modal },
  setup() {
    const { ref, reactive, computed, onMounted, onUnmounted } = Vue;

    const viewMode = ref('positions'); // positions | recommend
    const filters = reactive({
      city: '', salary: '', industry: '', keyword: '', experience: '',
    });

    /* ---------- 职位列表（300ms 防抖 + 竞态中止） ---------- */
    const positionsState = reactive({
      phase: 'loading', items: [], total: 0, page: 1, pageSize: 50,
      notUpdated: [], suggestion: null,
    });

    let searchController = null;
    let debounceTimer = null;

    async function loadPositions() {
      if (searchController) searchController.abort();
      searchController = new AbortController();
      const signal = searchController.signal;
      positionsState.phase = 'loading';
      const query = { page: positionsState.page, page_size: positionsState.pageSize };
      if (filters.city) query.city = filters.city;
      Object.assign(query, salaryTierParams(filters.salary));
      if (filters.industry) query.industry = filters.industry;
      if (filters.keyword.trim()) query.keyword = filters.keyword.trim();
      Object.assign(query, experienceTierParams(filters.experience));
      try {
        const data = await listPositions(query, signal);
        positionsState.items = data.items || [];
        positionsState.total = data.total || 0;
        positionsState.notUpdated = data.not_updated_platforms || [];
        positionsState.suggestion = data.suggestion || null;
        positionsState.phase = positionsState.total > 0 ? 'ready' : 'empty';
      } catch (e) {
        if (e && e.name === 'AbortError') return;
        positionsState.phase = 'error';
      }
    }

    function onFilterInput() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        positionsState.page = 1;
        loadPositions();
      }, 300);
    }

    function onPageChange(page, pageSize) {
      positionsState.page = page;
      positionsState.pageSize = pageSize;
      loadPositions();
    }

    /* ---------- 筛选选项（选择式交互：点击即选、再点取消、「不限」清空维度） ---------- */
    const cityExpanded = ref(false);
    const visibleCityOptions = computed(() =>
      cityExpanded.value
        ? FILTER_CITY_OPTIONS
        : FILTER_CITY_OPTIONS.slice(0, FILTER_CITY_HOT_COUNT + 1)
    );
    const salaryOptions = FILTER_SALARY_OPTIONS;
    const industryOptions = FILTER_INDUSTRY_OPTIONS;
    const experienceOptions = FILTER_EXPERIENCE_OPTIONS;
    const keywordShortcuts = FILTER_KEYWORD_SHORTCUTS;

    function toggleCity(option) {
      filters.city = option.value === '' ? '' : (filters.city === option.value ? '' : option.value);
      onFilterInput();
    }

    function toggleSalary(option) {
      filters.salary = option.value === '' ? '' : (filters.salary === option.value ? '' : option.value);
      onFilterInput();
    }

    function toggleIndustry(option) {
      filters.industry = option.value === '' ? '' : (filters.industry === option.value ? '' : option.value);
      onFilterInput();
    }

    function toggleExperience(option) {
      filters.experience = option.value === '' ? '' : (filters.experience === option.value ? '' : option.value);
      onFilterInput();
    }

    function toggleKeywordShortcut(word) {
      filters.keyword = filters.keyword === word ? '' : word;
      onFilterInput();
    }

    /* ---------- 推荐视图 ---------- */
    const recommendState = reactive({
      phase: 'loading', items: [], unavailable: false, message: '',
      needResume: false, loaded: false,
    });

    /* ---------- AI 渐进增强（D2：后端批任务 + 前端 3-5s 轮询，不阻塞首屏） ---------- */
    const aiState = reactive({
      active: false, taskId: '', status: '', done: 0, total: 0,
      summary: 'off', degradeMessage: '', scores: {}, reasons: {},
      scoreView: 'ai',
    });
    let aiPollTimer = null;

    async function startAiEnhancement() {
      stopAiPolling();
      const status = (store.aiStatus && store.aiStatus.state) || 'off';
      if (status !== 'ready') return;
      try {
        const task = await createAiMatchingTask(50);
        if (task.status === 'rejected') {
          aiState.degradeMessage = task.degrade_message || 'AI 暂不可用，已使用规则匹配';
          return;
        }
        aiState.taskId = task.task_id;
        aiState.total = task.total || 0;
        aiState.status = task.status;
        aiState.active = true;
        startAiPolling();
      } catch (e) { /* AI 发起失败静默：规则分列表不受影响 */ }
    }

    function startAiPolling() {
      stopAiPolling();
      aiPollTimer = setInterval(async () => {
        if (!aiState.taskId || !aiState.active) return;
        try {
          const task = await getAiMatchingTask(aiState.taskId);
          aiState.status = task.status;
          aiState.done = task.done || 0;
          aiState.total = task.total || 0;
          aiState.summary = task.ai_state_summary || 'off';
          if (task.degrade_message) aiState.degradeMessage = task.degrade_message;
          if (Array.isArray(task.items)) {
            for (const item of task.items) {
              if (item.status === 'ok' && item.ai_score != null) {
                aiState.scores[item.position_id] = item.ai_score;
                aiState.reasons[item.position_id] = item.reason || '';
              }
            }
            if (recommendState.items.length) {
              recommendState.items = [...recommendState.items];
            }
          }
          if (['completed', 'rejected', 'cancelled'].indexOf(task.status) >= 0) {
            stopAiPolling();
          }
        } catch (e) {
          if (e && e.code === 40401) stopAiPolling();
        }
      }, 3500);
    }

    function stopAiPolling() {
      if (aiPollTimer) {
        clearInterval(aiPollTimer);
        aiPollTimer = null;
      }
    }

    const aiCount = computed(() => Object.keys(aiState.scores).length);

    const aiBanner = computed(() => {
      if (!aiState.active && !aiState.degradeMessage) return '';
      if (aiState.degradeMessage) return aiState.degradeMessage;
      if (aiState.summary === 'all_fallback') return 'AI 暂不可用，已使用规则匹配与固定模板招呼语';
      return '';
    });

    function effectiveScoreOf(item) {
      if (aiState.scoreView === 'rule') return item.match_score;
      const ai = aiState.scores[item.position_id];
      return ai != null ? ai : item.match_score;
    }

    function hasAiScore(item) {
      return aiState.scores[item.position_id] != null;
    }

    const sortedRecommendItems = computed(() => {
      if (!recommendState.items.length) return recommendState.items;
      if (aiState.scoreView !== 'ai' || !aiCount.value) return recommendState.items;
      return [...recommendState.items].sort(
        (a, b) => (effectiveScoreOf(b) || 0) - (effectiveScoreOf(a) || 0)
      );
    });

    async function loadRecommendations() {
      recommendState.phase = 'loading';
      recommendState.needResume = false;
      try {
        const data = await getRecommendations(50);
        recommendState.items = data.items || [];
        recommendState.unavailable = !!data.matching_unavailable;
        recommendState.message = data.message || '';
        recommendState.loaded = true;
        recommendState.phase = recommendState.items.length > 0 ? 'ready' : 'empty';
        startAiEnhancement();
      } catch (e) {
        if (e && e.name === 'AbortError') return;
        if (e && e.code === 40401) {
          recommendState.needResume = true;
        }
        recommendState.phase = 'error';
      }
    }

    function switchView(mode) {
      viewMode.value = mode;
      if (mode === 'recommend' && !recommendState.loaded) {
        loadRecommendations();
      }
    }

    /* ---------- 匹配阈值设置（本地镜像回显） ---------- */
    const thresholdForm = ref(getMatchingThresholdMirror());
    const savingThreshold = ref(false);

    async function saveThreshold() {
      const value = Number(thresholdForm.value);
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        showToast('匹配阈值必须在 0-100 之间', 'failure');
        return;
      }
      savingThreshold.value = true;
      try {
        await setMatchingThreshold(value);
        setMatchingThresholdMirror(value);
        showToast('匹配阈值已生效：' + value + '，低于阈值的职位不进入自动投递范围');
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      } finally {
        savingThreshold.value = false;
      }
    }

    /* ---------- 勾选批量投递 ---------- */
    const selected = reactive(new Set());
    const selectedCount = computed(() => selected.size);
    const creatingTask = ref(false);

    function toggleSelect(positionId) {
      if (selected.has(positionId)) selected.delete(positionId);
      else selected.add(positionId);
    }

    async function startBatchApply() {
      if (!hasResume.value) {
        showToast('请先上传简历后再发起投递', 'failure');
        return;
      }
      if (selectedCount.value === 0) {
        showToast('请先勾选要投递的职位', 'failure');
        return;
      }
      creatingTask.value = true;
      try {
        const result = await createDeliveryTask({ position_ids: Array.from(selected) });
        pendingChecklist.value = result;
        selected.clear();
        navigate('#/tasks');
      } catch (e) {
        if (e && e.code === 40401) {
          showToast('请先上传简历（错误码 40401）', 'failure');
          navigate('#/resumes');
        } else {
          showToast(errorText(e), 'failure');
        }
      } finally {
        creatingTask.value = false;
      }
    }

    /* ---------- 快捷拉黑（Modal 确认，成功后即时消失） ---------- */
    const blacklistTarget = ref(null);

    function askBlacklistCompany(position) {
      blacklistTarget.value = {
        type: 'company', content: position.company, label: position.company,
        positionId: position.position_id,
      };
    }

    function askBlacklistKeyword(position) {
      blacklistTarget.value = {
        type: 'keyword', content: position.title, label: position.title,
        positionId: position.position_id,
      };
    }

    async function confirmBlacklist() {
      const target = blacklistTarget.value;
      blacklistTarget.value = null;
      if (!target) return;
      try {
        await addBlacklist(target.type, target.content);
        showToast('已加入黑名单，对推荐与投递立即生效');
        selected.delete(target.positionId);
        if (viewMode.value === 'positions') {
          positionsState.page = 1;
          await loadPositions();
        } else {
          recommendState.loaded = false;
          await loadRecommendations();
        }
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      }
    }

    onMounted(() => { loadPositions(); });

    onUnmounted(() => {
      if (searchController) searchController.abort();
      clearTimeout(debounceTimer);
      stopAiPolling();
    });

    return {
      viewMode, filters,
      positionsState, onFilterInput, onPageChange, loadPositions,
      recommendState, loadRecommendations, switchView,
      aiState, aiCount, aiBanner, effectiveScoreOf, hasAiScore, sortedRecommendItems,
      thresholdForm, savingThreshold, saveThreshold,
      selected, selectedCount, toggleSelect, creatingTask, startBatchApply,
      blacklistTarget, askBlacklistCompany, askBlacklistKeyword, confirmBlacklist,
      salaryText, relativeTime,
      hasResume, navigate,
      cityExpanded, visibleCityOptions, salaryOptions, industryOptions,
      experienceOptions, keywordShortcuts,
      toggleCity, toggleSalary, toggleIndustry, toggleExperience, toggleKeywordShortcut,
    };
  },
  template: `
    <div>
      <div class="card">
        <div class="card-title">
          <div class="row">
            <button :class="['btn', viewMode === 'positions' ? 'btn-primary' : '']" @click="switchView('positions')">全部职位</button>
            <button :class="['btn', viewMode === 'recommend' ? 'btn-primary' : '']" @click="switchView('recommend')">智能推荐</button>
          </div>
          <div class="row">
            <span class="muted">匹配阈值</span>
            <input type="range" class="range-slider" min="0" max="100" step="5" v-model.number="thresholdForm">
            <span class="match-score">{{ thresholdForm }}</span>
            <button class="btn btn-sm" :disabled="savingThreshold" @click="saveThreshold">
              {{ savingThreshold ? '保存中…' : '保存阈值' }}
            </button>
          </div>
        </div>

        <div v-if="viewMode === 'positions'" class="filter-group">
          <div class="filter-row">
            <span class="filter-label">城市</span>
            <div :class="['filter-chips', cityExpanded ? 'filter-grid' : '']">
              <span
                v-for="c in visibleCityOptions"
                :key="c.value || 'all'"
                :class="['filter-chip', { active: filters.city === c.value }]"
                @click="toggleCity(c)"
              >{{ c.label }}</span>
              <span class="filter-chip filter-toggle" @click="cityExpanded = !cityExpanded">
                {{ cityExpanded ? '收起' : '更多城市' }}
              </span>
            </div>
          </div>
          <div class="filter-row">
            <span class="filter-label">薪资</span>
            <div class="filter-chips">
              <span
                v-for="t in salaryOptions"
                :key="t.value || 'all'"
                :class="['filter-chip', { active: filters.salary === t.value }]"
                @click="toggleSalary(t)"
              >{{ t.label }}</span>
            </div>
          </div>
          <div class="filter-row">
            <span class="filter-label">行业</span>
            <div class="filter-chips">
              <span
                v-for="i in industryOptions"
                :key="i.value || 'all'"
                :class="['filter-chip', { active: filters.industry === i.value }]"
                @click="toggleIndustry(i)"
              >{{ i.label }}</span>
            </div>
          </div>
          <div class="filter-row">
            <span class="filter-label">经验</span>
            <div class="filter-chips">
              <span
                v-for="t in experienceOptions"
                :key="t.value || 'all'"
                :class="['filter-chip', { active: filters.experience === t.value }]"
                @click="toggleExperience(t)"
              >{{ t.label }}</span>
            </div>
          </div>
          <div class="filter-row">
            <span class="filter-label">关键词</span>
            <div class="filter-chips">
              <input class="input filter-keyword-input" v-model="filters.keyword" @input="onFilterInput" placeholder="搜索职位名称">
              <span
                v-for="k in keywordShortcuts"
                :key="k"
                :class="['filter-chip', { active: filters.keyword === k }]"
                @click="toggleKeywordShortcut(k)"
              >{{ k }}</span>
            </div>
          </div>
        </div>

        <div v-if="viewMode === 'positions' && positionsState.notUpdated.length" class="banner banner-warn">
          平台 {{ positionsState.notUpdated.join('、') }} 数据暂时未更新，展示最近一次成功拉取的数据
        </div>
        <div v-if="viewMode === 'recommend' && recommendState.unavailable && recommendState.phase === 'ready'" class="banner banner-warn">
          {{ recommendState.message || '当前简历无法解析文本，匹配功能暂不可用，建议上传文字版简历' }}
        </div>

        <div class="row" style="margin-bottom:14px">
          <span class="muted">已勾选 {{ selectedCount }} 个职位</span>
          <button
            class="btn btn-primary"
            :disabled="!hasResume || selectedCount === 0 || creatingTask"
            @click="startBatchApply"
          >{{ creatingTask ? '创建任务中…' : '批量投递' }}</button>
          <span v-if="!hasResume" class="muted">请先上传简历后再发起投递</span>
        </div>

        <template v-if="viewMode === 'positions'">
          <loading-skeleton v-if="positionsState.phase === 'loading'" :rows="6"></loading-skeleton>
          <error-banner v-else-if="positionsState.phase === 'error'" message="职位加载失败" @retry="loadPositions"></error-banner>
          <empty-state
            v-else-if="positionsState.phase === 'empty'"
            :message="positionsState.suggestion || '当前条件下暂无职位'"
          ></empty-state>
          <template v-else>
            <table class="table">
              <thead>
                <tr><th></th><th>职位名称</th><th>公司</th><th>城市</th><th>薪资</th><th>平台</th><th>拉取时间</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in positionsState.items" :key="p.position_id">
                  <td><input type="checkbox" :checked="selected.has(p.position_id)" @change="toggleSelect(p.position_id)"></td>
                  <td>{{ p.title }}</td>
                  <td>{{ p.company }}</td>
                  <td>{{ p.city }}</td>
                  <td>{{ salaryText(p.salary_min, p.salary_max) }}</td>
                  <td>{{ p.platform_id }}</td>
                  <td>{{ relativeTime(p.fetched_at) }}</td>
                  <td>
                    <div class="cell-actions">
                      <button class="btn btn-sm" @click="askBlacklistCompany(p)">拉黑公司</button>
                      <button class="btn btn-sm" @click="askBlacklistKeyword(p)">拉黑职位</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            <pagination
              :page="positionsState.page"
              :page-size="positionsState.pageSize"
              :total="positionsState.total"
              @change="onPageChange"
            ></pagination>
          </template>
        </template>

        <template v-else>
          <div v-if="aiBanner" class="banner banner-warn">{{ aiBanner }}</div>
          <div v-else-if="aiState.active && aiCount > 0 && aiState.status !== 'completed'" class="banner banner-info">
            AI 评分进行中：已完成 {{ aiCount }} 个职位，评分将自动刷新与重排序
          </div>
          <loading-skeleton v-if="recommendState.phase === 'loading'" :rows="6"></loading-skeleton>
          <empty-state
            v-else-if="recommendState.phase === 'error' && recommendState.needResume"
            message="请先上传简历后再使用职位推荐"
            action-text="去上传简历"
            @action="navigate('#/resumes')"
          ></empty-state>
          <error-banner
            v-else-if="recommendState.phase === 'error'"
            message="推荐生成中，请稍后刷新查看"
            @retry="loadRecommendations"
          ></error-banner>
          <empty-state v-else-if="recommendState.phase === 'empty'" message="暂无推荐职位"></empty-state>
          <template v-else>
            <div v-if="aiCount > 0" class="row" style="margin-bottom:10px">
              <span class="muted">评分视图</span>
              <button :class="['btn', 'btn-sm', aiState.scoreView === 'ai' ? 'btn-primary' : '']" @click="aiState.scoreView = 'ai'">AI 评分（{{ aiCount }}）</button>
              <button :class="['btn', 'btn-sm', aiState.scoreView === 'rule' ? 'btn-primary' : '']" @click="aiState.scoreView = 'rule'">规则评分</button>
            </div>
            <table class="table">
              <thead>
                <tr>
                  <th></th>
                  <th v-if="!recommendState.unavailable">匹配度</th>
                  <th v-if="aiCount > 0">评分理由</th>
                  <th>职位名称</th><th>公司</th><th>城市</th><th>薪资</th><th>平台</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in sortedRecommendItems" :key="p.position_id">
                  <td><input type="checkbox" :checked="selected.has(p.position_id)" @change="toggleSelect(p.position_id)"></td>
                  <td v-if="!recommendState.unavailable">
                    <span class="match-score">{{ effectiveScoreOf(p) }}</span>
                    <span v-if="hasAiScore(p) && aiState.scoreView === 'ai'" class="badge badge-blue" style="margin-left:4px">AI</span>
                    <span v-else-if="aiCount > 0" class="badge badge-gray" style="margin-left:4px">规则</span>
                  </td>
                  <td v-if="aiCount > 0" class="muted" style="max-width:260px">
                    {{ aiState.reasons[p.position_id] || (hasAiScore(p) ? '' : '—') }}
                  </td>
                  <td>{{ p.title }}</td>
                  <td>{{ p.company }}</td>
                  <td>{{ p.city }}</td>
                  <td>{{ salaryText(p.salary_min, p.salary_max) }}</td>
                  <td>{{ p.platform_id }}</td>
                  <td>
                    <div class="cell-actions">
                      <button class="btn btn-sm" @click="askBlacklistCompany(p)">拉黑公司</button>
                      <button class="btn btn-sm" @click="askBlacklistKeyword(p)">拉黑职位</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </template>
      </div>

      <modal
        v-if="blacklistTarget"
        title="加入投递黑名单"
        :body="'将「' + blacklistTarget.label + '」加入黑名单？加入后相关职位将从推荐与投递目标中排除，立即生效。'"
        confirm-text="加入黑名单"
        :danger="true"
        @confirm="confirmBlacklist"
        @cancel="blacklistTarget = null"
      ></modal>
    </div>
  `,
};