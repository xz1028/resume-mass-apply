/** 投递任务页：清单确认（核心流程）、条件圈选、任务列表（本地索引组装）、5s 轮询、取消、每日上限 */

const TaskPage = {
  components: { Modal, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    const { ref, reactive, computed, onMounted, onUnmounted } = Vue;

    /* ---------- 投递清单确认视图 ---------- */
    const confirmView = ref(null);
    const confirming = ref(false);
    const confirmModal = ref(false);

    const platformDistText = computed(() => {
      if (!confirmView.value) return '';
      const dist = confirmView.value.checklist.platform_distribution || {};
      return Object.keys(dist).map((pid) => pid + ' × ' + dist[pid]).join('，') || '无';
    });

    /** 清单中授权过期平台的职位将被跳过（标注 + 去授权入口） */
    const expiredPlatforms = computed(() => {
      if (!confirmView.value) return [];
      const dist = confirmView.value.checklist.platform_distribution || {};
      return Object.keys(dist).filter((pid) => {
        const platform = store.platforms.find((x) => x.platform_id === pid);
        return platform && platform.auth_status !== 'authorized';
      });
    });

    function takePendingChecklist() {
      if (pendingChecklist.value) {
        confirmView.value = pendingChecklist.value;
        pendingChecklist.value = null;
        prepareGreetingsForTask();
      }
    }

    /* ---------- AI 招呼语交互（进入清单 → prepare → 渐进轮询 → 预览/编辑） ---------- */
    const greetingsState = reactive({
      phase: 'idle', allReady: false, status: '', items: [],
    });
    const editTarget = ref(null); // { position_id, text }
    const editDraft = ref('');
    let greetingsTimer = null;

    async function prepareGreetingsForTask() {
      if (!confirmView.value) return;
      greetingsState.phase = 'loading';
      greetingsState.allReady = false;
      greetingsState.items = [];
      try {
        await prepareGreetings(confirmView.value.task.task_id);
        startGreetingsPolling();
      } catch (e) {
        greetingsState.phase = 'ready';
        greetingsState.allReady = true;
      }
    }

    function startGreetingsPolling() {
      stopGreetingsPolling();
      greetingsTimer = setInterval(async () => {
        if (!confirmView.value) {
          stopGreetingsPolling();
          return;
        }
        try {
          const data = await getGreetings(confirmView.value.task.task_id);
          greetingsState.items = data.items || [];
          greetingsState.allReady = !!data.all_ready;
          greetingsState.status = data.status || '';
          if (greetingsState.allReady) {
            greetingsState.phase = 'ready';
            stopGreetingsPolling();
          } else {
            greetingsState.phase = 'loading';
          }
        } catch (e) {
          greetingsState.phase = 'ready';
          greetingsState.allReady = true;
          stopGreetingsPolling();
        }
      }, 3000);
    }

    function stopGreetingsPolling() {
      if (greetingsTimer) {
        clearInterval(greetingsTimer);
        greetingsTimer = null;
      }
    }

    function greetingOf(positionId) {
      return greetingsState.items.find((g) => g.position_id === positionId) || null;
    }

    function openEditGreeting(positionId) {
      const item = greetingOf(positionId);
      editTarget.value = { position_id: positionId };
      editDraft.value = item ? (item.text || '') : '';
    }

    async function saveEditGreeting() {
      const target = editTarget.value;
      if (!target || !confirmView.value) return;
      const text = editDraft.value.trim();
      if (!text) {
        showToast('招呼语不能为空', 'failure');
        return;
      }
      try {
        await editGreeting(confirmView.value.task.task_id, target.position_id, text);
        showToast('招呼语已保存，投递时将发送该编辑版');
        editTarget.value = null;
        const data = await getGreetings(confirmView.value.task.task_id);
        greetingsState.items = data.items || [];
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      }
    }

    const GREETING_SOURCE_LABEL = { ai: 'AI', template: '模板', edited: '已编辑' };

    function greetingSourceBadge(source) {
      const tone = source === 'ai' ? 'badge-blue' : source === 'edited' ? 'badge-green' : 'badge-gray';
      return { label: GREETING_SOURCE_LABEL[source] || source, tone };
    }

    function cancelChecklist() {
      stopGreetingsPolling();
      confirmView.value = null;
    }

    async function confirmTask() {
      confirmModal.value = false;
      if (!confirmView.value) return;
      confirming.value = true;
      try {
        await confirmDeliveryTask(confirmView.value.task.task_id);
        showToast('投递任务已确认，开始执行');
        stopGreetingsPolling();
        confirmView.value = null;
        await refreshTasks();
        startPolling();
      } catch (e) {
        if (e && e.code === 40903) {
          showToast('任务状态已变化，请刷新后查看（错误码 40903）', 'failure');
          await refreshTasks();
        } else {
          showToast(errorText(e), 'failure');
        }
      } finally {
        confirming.value = false;
      }
    }

    /* ---------- 条件圈选投递 ---------- */
    const circleForm = reactive({
      city: '', salary_min: '', salary_max: '', industry: '', keyword: '', experience: '', min_match_score: '',
    });
    const circling = ref(false);

    async function startCircleApply() {
      const fc = {};
      if (circleForm.city.trim()) fc.city = circleForm.city.trim();
      if (circleForm.salary_min) fc.salary_min = Number(circleForm.salary_min);
      if (circleForm.salary_max) fc.salary_max = Number(circleForm.salary_max);
      if (circleForm.industry.trim()) fc.industry = circleForm.industry.trim();
      if (circleForm.keyword.trim()) fc.keyword = circleForm.keyword.trim();
      if (circleForm.experience.trim()) fc.experience = circleForm.experience.trim();
      if (circleForm.min_match_score !== '' && circleForm.min_match_score !== null) {
        fc.min_match_score = Number(circleForm.min_match_score);
      }
      if (Object.keys(fc).length === 0) {
        showToast('请至少填写一个圈选条件', 'failure');
        return;
      }
      circling.value = true;
      try {
        const result = await createDeliveryTask({ filter_condition: fc });
        confirmView.value = result;
      } catch (e) {
        if (e && e.code === 40401) {
          showToast('请先上传简历（错误码 40401）', 'failure');
          navigate('#/resumes');
        } else {
          showToast(errorText(e), 'failure');
        }
      } finally {
        circling.value = false;
      }
    }

    /* ---------- 任务列表（本地索引 + 并发单查组装） ---------- */
    const tasksState = reactive({ phase: 'loading', items: [] });
    const pollError = ref('');

    async function refreshTasks() {
      const ids = getTaskIndex();
      if (ids.length === 0) {
        tasksState.items = [];
        tasksState.phase = 'empty';
        return;
      }
      try {
        const results = await Promise.all(ids.map((id) =>
          getDeliveryTask(id).catch((e) => {
            if (e && e.code === 40401) {
              removeTaskId(id);
              return null;
            }
            throw e;
          })
        ));
        const items = results.filter(Boolean);
        items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        tasksState.items = items;
        tasksState.phase = items.length > 0 ? 'ready' : 'empty';
        pollError.value = '';
      } catch (e) {
        if (tasksState.phase === 'loading') {
          tasksState.phase = 'error';
        } else {
          pollError.value = '进度刷新失败，任务仍在后台执行，请稍后刷新查看';
        }
      }
    }

    /* ---------- 执行中任务 5s 轮询（单飞；页面隐藏暂停，恢复立即补查） ---------- */
    let pollTimer = null;
    let pollInFlight = false;

    function hasExecuting() {
      return tasksState.items.some((t) => t.status === 'executing');
    }

    function startPolling() {
      stopPolling();
      pollTimer = setInterval(async () => {
        if (document.hidden || pollInFlight || !hasExecuting()) return;
        pollInFlight = true;
        try {
          await refreshTasks();
        } finally {
          pollInFlight = false;
        }
      }, 5000);
    }

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function onVisibilityChange() {
      if (!document.hidden && hasExecuting()) {
        refreshTasks();
      }
    }

    /* ---------- 取消任务（二次确认） ---------- */
    const cancelTarget = ref(null);

    async function confirmCancel() {
      const target = cancelTarget.value;
      cancelTarget.value = null;
      if (!target) return;
      try {
        const result = await cancelDeliveryTask(target.task_id);
        showToast('任务已取消，已成功投递 ' + result.delivered + ' 个，剩余 ' + result.remaining + ' 个未投递');
      } catch (e) {
        if (e && e.code === 40903) {
          showToast('任务状态已变化，请刷新后查看（错误码 40903）', 'failure');
        } else {
          showToast(errorText(e), 'failure');
        }
      }
      await refreshTasks();
    }

    /* ---------- 每日投递上限设置（本地镜像回显） ---------- */
    const dailyLimitForm = ref(getDailyLimitMirror());
    const savingLimit = ref(false);

    async function saveDailyLimit() {
      const value = Number(dailyLimitForm.value);
      if (!Number.isFinite(value) || value < 1) {
        showToast('每日投递上限必须为不小于 1 的整数', 'failure');
        return;
      }
      savingLimit.value = true;
      try {
        await setDailyLimit(value);
        setDailyLimitMirror(value);
        showToast('每日投递上限已生效：' + value);
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      } finally {
        savingLimit.value = false;
      }
    }

    onMounted(() => {
      takePendingChecklist();
      refreshTasks().then(() => {
        if (hasExecuting()) startPolling();
      });
      document.addEventListener('visibilitychange', onVisibilityChange);
    });

    onUnmounted(() => {
      stopPolling();
      stopGreetingsPolling();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    });

    return {
      confirmView, confirming, confirmModal, platformDistText, expiredPlatforms,
      cancelChecklist, confirmTask,
      greetingsState, greetingOf, openEditGreeting, saveEditGreeting,
      editTarget, editDraft, greetingSourceBadge,
      circleForm, circling, startCircleApply,
      tasksState, pollError, refreshTasks,
      cancelTarget, confirmCancel,
      dailyLimitForm, savingLimit, saveDailyLimit,
      taskStatusLabel, formatTime, relativeTime,
      navigate,
    };
  },
  template: `
    <div>
      <!-- 投递清单确认视图 -->
      <div v-if="confirmView" class="card">
        <div class="card-title">投递清单确认</div>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value">{{ confirmView.checklist.position_count }}</div>
            <div class="stat-label">可投递职位</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ (confirmView.checklist.rejected || []).length }}</div>
            <div class="stat-label">被拦截职位</div>
          </div>
        </div>
        <p class="muted">使用简历：{{ confirmView.checklist.resume_name }}</p>
        <p class="muted">平台分布：{{ platformDistText }}</p>
        <div v-for="pid in expiredPlatforms" :key="pid" class="banner banner-warn">
          <span>平台 {{ pid }} 授权已过期，其 {{ confirmView.checklist.platform_distribution[pid] }} 个职位将被跳过</span>
          <button class="btn btn-sm" @click="navigate('#/settings')">去授权</button>
        </div>
        <div v-if="(confirmView.checklist.rejected || []).length" style="margin-top:12px">
          <p class="muted" style="margin-bottom:8px">以下职位已被拦截，不会投递：</p>
          <table class="table">
            <thead><tr><th>职位名称</th><th>拦截原因</th></tr></thead>
            <tbody>
              <tr v-for="r in confirmView.checklist.rejected" :key="r.position_id">
                <td>{{ r.title }}</td>
                <td class="muted">{{ r.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- AI 招呼语预览与编辑 -->
        <div v-if="greetingsState.items.length || greetingsState.phase === 'loading'" style="margin-top:16px">
          <div class="row" style="margin-bottom:10px">
            <span class="card-title" style="margin:0;font-size:15px">打招呼消息（BOSS直聘/模拟平台职位）</span>
            <span v-if="!greetingsState.allReady" class="badge badge-cyan">生成中 {{ greetingsState.items.length }}/{{ confirmView.task.position_count }}</span>
            <span v-else class="badge badge-green">已就绪</span>
          </div>
          <div v-for="g in greetingsState.items" :key="g.position_id" class="platform-card" style="align-items:flex-start">
            <div style="flex:1;min-width:0">
              <div class="row" style="margin-bottom:6px">
                <span :class="['badge', greetingSourceBadge(g.source).tone]">{{ greetingSourceBadge(g.source).label }}</span>
              </div>
              <p class="muted" style="white-space:pre-wrap">{{ g.text }}</p>
            </div>
            <button class="btn btn-sm" @click="openEditGreeting(g.position_id)">编辑</button>
          </div>
        </div>
        <div class="row" style="margin-top:16px">
          <button class="btn btn-primary" :disabled="confirming" @click="confirmModal = true">
            {{ confirming ? '确认中…' : '确认投递' }}
          </button>
          <button class="btn" @click="cancelChecklist">取消</button>
          <span v-if="!greetingsState.allReady && greetingsState.items.length" class="muted">招呼语生成中，可不等待直接确认（未就绪职位发送固定模板）</span>
          <span v-else class="muted">确认后才开始执行投递；取消不会产生任何投递记录</span>
        </div>
      </div>

      <!-- 条件圈选 -->
      <div class="card">
        <div class="card-title">按条件圈选投递</div>
        <div class="form-grid">
          <div class="form-item"><label>城市</label><input class="input" v-model="circleForm.city" placeholder="深圳"></div>
          <div class="form-item"><label>最低薪资（元/月）</label><input class="input" type="number" v-model="circleForm.salary_min"></div>
          <div class="form-item"><label>最高薪资（元/月）</label><input class="input" type="number" v-model="circleForm.salary_max"></div>
          <div class="form-item"><label>行业</label><input class="input" v-model="circleForm.industry"></div>
          <div class="form-item"><label>职位关键词</label><input class="input" v-model="circleForm.keyword"></div>
          <div class="form-item"><label>经验要求</label><input class="input" v-model="circleForm.experience" placeholder="3-5年"></div>
          <div class="form-item"><label>匹配度不低于</label><input class="input" type="number" min="0" max="100" v-model="circleForm.min_match_score" placeholder="80"></div>
        </div>
        <div class="row" style="margin-top:14px">
          <button class="btn btn-primary" :disabled="circling" @click="startCircleApply">
            {{ circling ? '圈选中…' : '按条件发起投递' }}
          </button>
          <span class="muted">如"投递所有匹配度 ≥ 80 的深圳职位"，圈选后进入清单确认</span>
        </div>
      </div>

      <!-- 任务列表 -->
      <div class="card">
        <div class="card-title">
          <span>投递任务</span>
          <button class="btn btn-sm" @click="refreshTasks">刷新</button>
        </div>
        <div v-if="pollError" class="banner banner-warn">{{ pollError }}</div>
        <loading-skeleton v-if="tasksState.phase === 'loading'" :rows="4"></loading-skeleton>
        <error-banner v-else-if="tasksState.phase === 'error'" message="任务列表加载失败" @retry="refreshTasks"></error-banner>
        <empty-state
          v-else-if="tasksState.phase === 'empty'"
          message="暂无投递任务，去职位推荐页发起第一次投递吧"
          action-text="去职位推荐页"
          @action="navigate('#/positions')"
        ></empty-state>
        <template v-else>
          <div v-for="t in tasksState.items" :key="t.task_id" class="platform-card">
            <div>
              <div class="platform-name">
                {{ t.resume_name }} 的投递任务
                <span :class="['badge', 'badge-' + taskStatusLabel(t.status).tone]" style="margin-left:8px">
                  {{ taskStatusLabel(t.status).label }}
                </span>
              </div>
              <div class="muted">创建时间：{{ formatTime(t.created_at) }}</div>
              <div v-if="t.status === 'completed' || t.status === 'cancelled'" class="task-summary" style="margin-top:8px">
                <span class="summary-item">共 <b>{{ t.position_count }}</b> 个职位：</span>
                <span class="summary-item">成功 <b style="color:var(--tone-green)">{{ t.success_count }}</b></span>
                <span class="summary-item">失败 <b style="color:var(--tone-red)">{{ t.failed_count }}</b></span>
                <span class="summary-item">跳过 <b>{{ t.skipped_count }}</b></span>
              </div>
              <div v-else-if="t.status === 'executing'" class="task-summary" style="margin-top:8px">
                <span class="summary-item">已成功 <b style="color:var(--tone-green)">{{ t.success_count }}</b></span>
                <span class="summary-item">已失败 <b style="color:var(--tone-red)">{{ t.failed_count }}</b></span>
                <span class="summary-item">已跳过 <b>{{ t.skipped_count }}</b></span>
                <span class="muted">每 5 秒自动刷新进度</span>
              </div>
            </div>
            <div class="spacer"></div>
            <button
              v-if="t.status === 'executing'"
              class="btn btn-danger"
              @click="cancelTarget = t"
            >取消任务</button>
          </div>
        </template>
      </div>

      <!-- 每日上限 -->
      <div class="card">
        <div class="card-title">投递设置</div>
        <div class="row">
          <span class="muted">每日投递上限</span>
          <input class="input" style="width:100px" type="number" min="1" v-model.number="dailyLimitForm">
          <button class="btn btn-primary" :disabled="savingLimit" @click="saveDailyLimit">
            {{ savingLimit ? '保存中…' : '保存' }}
          </button>
          <span class="muted">达到上限后当日停止自动投递</span>
        </div>
      </div>

      <modal
        v-if="confirmModal"
        title="确认执行批量投递"
        :body="'即将向 ' + (confirmView ? confirmView.checklist.position_count : 0) + ' 个职位投递简历（使用「' + (confirmView ? confirmView.checklist.resume_name : '') + '」）。确认后立即开始执行。'"
        confirm-text="确认投递"
        @confirm="confirmTask"
        @cancel="confirmModal = false"
      ></modal>

      <!-- 招呼语编辑弹层 -->
      <div v-if="editTarget" class="modal-mask" @click.self="editTarget = null">
        <div class="modal-box" style="max-width:520px">
          <h3 class="modal-title">编辑打招呼消息</h3>
          <textarea class="input" rows="5" style="width:100%;resize:vertical" v-model="editDraft" maxlength="500"></textarea>
          <p class="muted" style="margin-top:6px">{{ editDraft.length }}/200 字（超长将被截断并剔除联系方式）</p>
          <div class="modal-actions" style="margin-top:14px">
            <button class="btn" @click="editTarget = null">取消</button>
            <button class="btn btn-primary" @click="saveEditGreeting">保存</button>
          </div>
        </div>
      </div>

      <modal
        v-if="cancelTarget"
        title="取消投递任务"
        :body="'取消后将停止向未投递职位发送请求，已投递的记录会保留。确认取消该任务？'"
        confirm-text="确认取消"
        :danger="true"
        @confirm="confirmCancel"
        @cancel="cancelTarget = null"
      ></modal>
    </div>
  `,
};