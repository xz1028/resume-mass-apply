/** 平台授权与设置页：真实平台接入治理（风险告知/启停/浏览器授权/轮询/待处理事件横幅）
 * + 既有能力（凭证授权、撤销、黑名单、降级标注） */

const PlatformPage = {
  components: { Modal, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    const { ref, reactive, computed, onMounted, onUnmounted } = Vue;

    /* ---------- 平台列表（既有） ---------- */
    const platformsState = reactive({ phase: 'loading', items: [] });
    const authForms = reactive({});

    async function loadPlatforms() {
      platformsState.phase = 'loading';
      try {
        // 先取接入配置（三个真实平台无论启停均包含），再取已注册平台列表
        await loadAccessConfigs();
        const data = await listPlatforms();
        const registered = Array.isArray(data) ? data : [];
        // 卡片渲染 = 真实平台（来自接入配置，禁用也展示启用入口）+ 已注册其他平台（mock 等）
        const realCards = accessState.items
          .filter((c) => REAL_PLATFORM_IDS.indexOf(c.platform_id) >= 0)
          .map((c) => ({
            platform_id: c.platform_id,
            name: c.name,
            auth_status: c.auth_status,
            degraded: c.degraded,
          }));
        const others = registered.filter((p) => REAL_PLATFORM_IDS.indexOf(p.platform_id) < 0);
        const merged = realCards.concat(others);
        platformsState.items = merged;
        platformsState.phase = merged.length > 0 ? 'ready' : 'empty';
        store.platforms = registered;
      } catch (e) {
        platformsState.phase = 'error';
      }
    }

    function formOf(platformId) {
      if (!authForms[platformId]) {
        authForms[platformId] = { credential: '', error: '', submitting: false };
      }
      return authForms[platformId];
    }

    async function submitAuthorize(platform) {
      const form = formOf(platform.platform_id);
      form.error = '';
      if (!form.credential.trim()) {
        form.error = '请输入授权凭证';
        return;
      }
      if (platform.degraded) {
        form.error = '平台 ' + platform.platform_id + ' 暂不可用，请稍后再试（错误码 41003）';
        return;
      }
      form.submitting = true;
      try {
        await authorizePlatform(platform.platform_id, form.credential);
        form.credential = '';
        showToast('平台「' + platform.name + '」授权成功');
        await loadPlatforms();
        refreshGlobalSignals();
      } catch (e) {
        form.error = errorText(e, 'form');
      } finally {
        form.submitting = false;
      }
    }

    /* ---------- 接入配置（真实平台治理） ---------- */
    const accessState = reactive({ phase: 'loading', items: [] });
    const REAL_PLATFORM_IDS = ['boss_zhipin', 'zhilian', 'job51'];
    const realConfigs = computed(() => accessState.items);

    async function loadAccessConfigs() {
      try {
        const data = await listAccessConfigs();
        accessState.items = Array.isArray(data) ? data : [];
        accessState.phase = accessState.items.length > 0 ? 'ready' : 'empty';
      } catch (e) {
        accessState.phase = 'error';
      }
    }

    function isRealPlatform(platformId) {
      return REAL_PLATFORM_IDS.indexOf(platformId) >= 0;
    }

    function configOf(platformId) {
      return accessState.items.find((c) => c.platform_id === platformId) || null;
    }

    /* ---------- 风险告知确认弹窗（首次启用强制） ---------- */
    const riskConfirmTarget = ref(null);
    const RISK_DISCLOSURE = [
      '接入方式为浏览器自动化（非平台官方渠道），模拟人工操作页面完成职位检索与投递',
      '该方式可能违反招聘平台的用户协议或服务条款',
      '平台可能对使用自动化工具的账号采取限制功能、要求人机验证甚至封禁账号的措施',
      '授权仅使用您本人拥有的账号，账号安全与合规责任由使用者自行承担',
    ];

    async function askEnable(config) {
      // 浏览器组件预检（tasks 2.7b）：核心绿色包无 playwright 时弹一次性引导，不进入启用流程
      if (typeof browserComponentGuard === 'function' && !await browserComponentGuard()) {
        return;
      }
      if (config.risk_confirmed) {
        doEnable(config.platform_id);
        return;
      }
      riskConfirmTarget.value = config;
    }

    async function confirmRiskAndEnable() {
      const target = riskConfirmTarget.value;
      riskConfirmTarget.value = null;
      if (!target) return;
      try {
        await confirmAccessRisk(target.platform_id);
        await doEnable(target.platform_id);
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    async function doEnable(platformId) {
      try {
        await enableRealPlatform(platformId);
        showToast('平台已启用，可发起浏览器登录授权');
        await loadPlatforms();
        refreshGlobalSignals();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- 禁用平台（二次确认：历史记录保留） ---------- */
    const disableTarget = ref(null);

    async function confirmDisable() {
      const target = disableTarget.value;
      disableTarget.value = null;
      if (!target) return;
      try {
        await disableRealPlatform(target.platform_id);
        showToast('平台已禁用：停止一切交互，历史投递记录保留可查');
        await loadPlatforms();
        refreshGlobalSignals();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- 限流设置（安全上限 30/h，选择式档位） ---------- */
    const rateOptions = [5, 10, 15, 20, 25, 30];
    const rateSaving = ref('');

    async function changeRate(config, event) {
      const value = Number(event.target.value);
      rateSaving.value = config.platform_id;
      try {
        await updateRatePolicy(config.platform_id, value);
        showToast('限流已生效：' + value + '/小时');
        await loadAccessConfigs();
      } catch (e) {
        showToast(errorText(e), 'failure');
      } finally {
        rateSaving.value = '';
      }
    }

    /* ---------- 浏览器授权会话（创建→轮询→取消） ---------- */
    const authSession = reactive({
      session_id: '', platform_id: '', status: '', remaining_seconds: 0,
      failure_reason: null,
    });
    const authSessionActive = ref(false);
    let sessionPollTimer = null;

    async function startBrowserAuth(config) {
      if (authSessionActive.value) {
        showToast('已有进行中的授权会话', 'failure');
        return;
      }
      try {
        const data = await createBrowserAuthorization(config.platform_id);
        authSession.session_id = data.session_id;
        authSession.platform_id = config.platform_id;
        authSession.status = data.status;
        authSessionActive.value = true;
        showToast('浏览器窗口即将打开，请在窗口中登录平台完成授权');
        startSessionPolling();
      } catch (e) {
        if (e && e.code === 42001) {
          showToast('请先完成风险告知确认并启用平台（错误码 42001）', 'failure');
        } else {
          showToast(errorText(e), 'failure');
        }
      }
    }

    const SESSION_STATUS_TEXT = {
      created: '会话已创建',
      browser_opening: '正在打开浏览器…',
      waiting_login: '等待您在浏览器窗口中完成登录',
      captcha_pending: '平台要求人机验证，请在浏览器窗口中完成',
      validating: '正在校验登录态…',
      success: '授权成功',
      failed: '授权失败',
      expired: '会话超时（10 分钟）',
      cancelled: '已取消',
    };

    function sessionStatusText(status) {
      return SESSION_STATUS_TEXT[status] || status;
    }

    function startSessionPolling() {
      stopSessionPolling();
      sessionPollTimer = setInterval(async () => {
        if (!authSessionActive.value || !authSession.session_id) return;
        try {
          const data = await pollBrowserAuthorization(authSession.platform_id, authSession.session_id);
          authSession.status = data.status;
          authSession.remaining_seconds = data.remaining_seconds;
          authSession.failure_reason = data.failure_reason;
          if (data.status === 'success') {
            stopSessionPolling();
            authSessionActive.value = false;
            showToast('浏览器登录授权成功，职位即将自动拉取');
            await loadPlatforms();
            refreshGlobalSignals();
          } else if (['failed', 'expired', 'cancelled'].indexOf(data.status) >= 0) {
            stopSessionPolling();
            authSessionActive.value = false;
            showToast('授权未完成：' + (data.failure_reason || sessionStatusText(data.status)), 'failure');
          }
        } catch (e) {
          if (e && e.code === 40401) {
            stopSessionPolling();
            authSessionActive.value = false;
          }
        }
      }, 3000);
    }

    function stopSessionPolling() {
      if (sessionPollTimer) {
        clearInterval(sessionPollTimer);
        sessionPollTimer = null;
      }
    }

    async function cancelAuthSession() {
      if (!authSession.session_id) return;
      try {
        await cancelBrowserAuthorization(authSession.platform_id, authSession.session_id);
        showToast('已取消授权会话，浏览器将关闭且不保存凭证');
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
      stopSessionPolling();
      authSessionActive.value = false;
    }

    /* ---------- 授权方式选择（真实平台未授权且已启用） ---------- */
    const authModeChoice = reactive({});

    function authModeOf(platformId) {
      if (authModeChoice[platformId] === undefined) {
        authModeChoice[platformId] = 'browser';
      }
      return authModeChoice[platformId];
    }

    /* ---------- 待处理事件横幅（挑战+风险事件，30s 轮询） ---------- */
    const pendingEvents = reactive({ challenges: [], riskEvents: [] });
    let eventsPollTimer = null;

    async function pollPendingEvents() {
      try {
        const data = await getPendingEvents();
        pendingEvents.challenges = data.challenges || [];
        pendingEvents.riskEvents = data.risk_events || [];
      } catch (e) { /* 静默：横幅轮询失败不打扰 */ }
    }

    function startEventsPolling() {
      stopEventsPolling();
      pollPendingEvents();
      eventsPollTimer = setInterval(pollPendingEvents, 30000);
    }

    function stopEventsPolling() {
      if (eventsPollTimer) {
        clearInterval(eventsPollTimer);
        eventsPollTimer = null;
      }
    }

    async function handleChallenge(challenge) {
      try {
        await handleCaptchaChallenge(challenge.platform_id, challenge.challenge_id);
        showToast('已打开浏览器窗口，请在窗口中完成人机验证');
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- 撤销授权（真实平台：先终止会话再撤销） ---------- */
    const revokeTarget = ref(null);

    async function confirmRevoke() {
      const target = revokeTarget.value;
      revokeTarget.value = null;
      if (!target) return;
      try {
        if (isRealPlatform(target.platform_id)) {
          try { await disableRealPlatform(target.platform_id); } catch (e) { /* 会话终止失败不阻断撤销 */ }
        }
        await revokePlatform(target.platform_id);
        showToast('已撤销「' + target.name + '」授权，立即停止该平台一切投递行为');
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
      await loadPlatforms();
      refreshGlobalSignals();
    }

    /* ---------- 黑名单管理（既有） ---------- */
    const blacklistState = reactive({ phase: 'loading', items: [] });
    const blForm = reactive({ type: 'company', content: '' });
    const blError = ref('');
    const addingBl = ref(false);

    async function loadBlacklist() {
      blacklistState.phase = 'loading';
      try {
        const data = await listBlacklist();
        blacklistState.items = Array.isArray(data) ? data : [];
        blacklistState.phase = blacklistState.items.length > 0 ? 'ready' : 'empty';
      } catch (e) {
        blacklistState.phase = 'error';
      }
    }

    async function addBlacklistEntry() {
      blError.value = '';
      if (!blForm.content.trim()) {
        blError.value = '请输入黑名单内容';
        return;
      }
      addingBl.value = true;
      try {
        await addBlacklist(blForm.type, blForm.content.trim());
        showToast('已加入黑名单，对推荐与投递立即生效');
        blForm.content = '';
        await loadBlacklist();
      } catch (e) {
        blError.value = errorText(e, 'form');
      } finally {
        addingBl.value = false;
      }
    }

    async function removeEntry(entry) {
      try {
        await removeBlacklist(entry.entry_id);
        showToast('已移除「' + entry.content + '」，后续推荐不再过滤该条目');
        await loadBlacklist();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    onMounted(() => {
      loadPlatforms();
      loadBlacklist();
      startEventsPolling();
    });

    onUnmounted(() => {
      stopSessionPolling();
      stopEventsPolling();
    });

    return {
      platformsState, authForms, formOf, submitAuthorize,
      accessState, realConfigs, isRealPlatform, configOf,
      riskConfirmTarget, RISK_DISCLOSURE, askEnable, confirmRiskAndEnable,
      disableTarget, confirmDisable,
      rateOptions, rateSaving, changeRate,
      authSession, authSessionActive, startBrowserAuth, cancelAuthSession,
      sessionStatusText, authModeChoice, authModeOf,
      pendingEvents, handleChallenge,
      revokeTarget, confirmRevoke,
      blacklistState, blForm, blError, addingBl, addBlacklistEntry, removeEntry,
      authStatusLabel, blacklistTypeLabel, formatTime,
    };
  },
  template: `
    <div>
      <!-- 待处理事件横幅：验证码挑战 + 风险事件 -->
      <div v-for="c in pendingEvents.challenges" :key="c.challenge_id" class="banner banner-warn">
        <span>{{ c.message }}</span>
        <button class="btn btn-sm" @click="handleChallenge(c)">前往处理</button>
      </div>
      <div v-for="r in pendingEvents.riskEvents" :key="r.event_id" class="banner banner-warn">
        <span>平台 {{ r.platform_id }} 风险事件（{{ r.event_type }}）：{{ r.advice }}</span>
      </div>

      <!-- 浏览器授权会话进度 -->
      <div v-if="authSessionActive" class="card" style="border-color: var(--primary)">
        <div class="card-title">浏览器登录授权进行中</div>
        <div class="row">
          <span class="badge badge-blue">{{ sessionStatusText(authSession.status) }}</span>
          <span class="muted">剩余 {{ Math.floor(authSession.remaining_seconds / 60) }} 分 {{ authSession.remaining_seconds % 60 }} 秒</span>
          <span class="spacer"></span>
          <button class="btn" @click="cancelAuthSession">取消授权</button>
        </div>
        <p class="muted" style="margin-top:8px">
          浏览器窗口已打开，请在窗口中完成登录；如遇人机验证请直接在窗口中完成。
          授权成功后登录态将加密保存并自动拉取职位。
        </p>
      </div>

      <div class="card">
        <div class="card-title">招聘平台接入与授权</div>
        <loading-skeleton v-if="platformsState.phase === 'loading'" :rows="3"></loading-skeleton>
        <error-banner v-else-if="platformsState.phase === 'error'" message="平台列表加载失败" @retry="loadPlatforms"></error-banner>
        <empty-state v-else-if="platformsState.phase === 'empty'" message="暂无已接入的招聘平台"></empty-state>
        <template v-else>
          <template v-for="p in platformsState.items" :key="p.platform_id">
            <div class="platform-card">
              <div>
                <div class="platform-name">
                  {{ p.name }}
                  <span :class="['badge', 'badge-' + authStatusLabel(p.auth_status).tone]" style="margin-left:8px">
                    {{ authStatusLabel(p.auth_status).label }}
                  </span>
                  <span v-if="p.degraded" class="badge badge-orange" style="margin-left:6px">降级中</span>
                  <span v-if="isRealPlatform(p.platform_id)" class="badge badge-blue" style="margin-left:6px">已接入</span>
                </div>
                <div v-if="p.degraded" class="degraded-note">暂不可用（仅浏览），恢复后自动补拉数据</div>
                <div v-if="isRealPlatform(p.platform_id) && configOf(p.platform_id)" class="degraded-note" style="color: var(--text-secondary)">
                  接入方式：浏览器自动化（本机 Chrome/Edge 受控操作）
                </div>
              </div>
              <div class="spacer"></div>
              <template v-if="isRealPlatform(p.platform_id) && configOf(p.platform_id)">
                <!-- 真实平台：启用开关 + 限流 -->
                <div class="row">
                  <span class="muted">{{ configOf(p.platform_id).enabled ? '已启用' : '未启用' }}</span>
                  <button
                    v-if="!configOf(p.platform_id).enabled"
                    class="btn btn-sm btn-primary"
                    @click="askEnable(configOf(p.platform_id))"
                  >启用</button>
                  <button
                    v-else
                    class="btn btn-sm"
                    @click="disableTarget = configOf(p.platform_id)"
                  >禁用</button>
                </div>
              </template>
              <template v-if="p.auth_status === 'authorized'">
                <button class="btn btn-danger" @click="revokeTarget = p">撤销授权</button>
              </template>
            </div>

            <!-- 真实平台详情区：限流档位 + 授权方式选择 -->
            <div v-if="isRealPlatform(p.platform_id) && configOf(p.platform_id)" style="margin:-6px 0 14px; padding-left:8px">
              <div class="row" style="margin-top:4px">
                <span class="muted">投递限流</span>
                <select
                  class="select"
                  style="width:110px"
                  :value="configOf(p.platform_id).delivery_rate_per_hour"
                  :disabled="rateSaving === p.platform_id"
                  @change="changeRate(configOf(p.platform_id), $event)"
                >
                  <option v-for="r in rateOptions" :key="r" :value="r">{{ r }}/小时</option>
                </select>
                <span class="muted">安全上限 30/小时</span>
              </div>

              <div v-if="configOf(p.platform_id).enabled && p.auth_status !== 'authorized'" class="row" style="margin-top:10px">
                <span class="muted">授权方式</span>
                <button
                  :class="['btn', 'btn-sm', authModeOf(p.platform_id) === 'browser' ? 'btn-primary' : '']"
                  @click="authModeChoice[p.platform_id] = 'browser'"
                >浏览器登录授权（推荐）</button>
                <button
                  :class="['btn', 'btn-sm', authModeOf(p.platform_id) === 'paste' ? 'btn-primary' : '']"
                  @click="authModeChoice[p.platform_id] = 'paste'"
                >手动粘贴凭证</button>
              </div>
              <div v-if="configOf(p.platform_id).enabled && p.auth_status !== 'authorized' && authModeOf(p.platform_id) === 'browser'" class="row" style="margin-top:8px">
                <button class="btn btn-primary" :disabled="authSessionActive" @click="startBrowserAuth(configOf(p.platform_id))">
                  打开浏览器登录授权
                </button>
                <span class="muted">将打开浏览器窗口，在窗口中登录平台即可，密码不保存</span>
              </div>
              <div v-if="configOf(p.platform_id).enabled && p.auth_status !== 'authorized' && authModeOf(p.platform_id) === 'paste'" class="row" style="margin-top:8px">
                <input
                  class="input"
                  style="width:220px"
                  type="password"
                  v-model="formOf(p.platform_id).credential"
                  placeholder="粘贴登录态凭证 JSON"
                  @keyup.enter="submitAuthorize(p)"
                >
                <button
                  class="btn btn-primary"
                  :disabled="formOf(p.platform_id).submitting"
                  @click="submitAuthorize(p)"
                >{{ formOf(p.platform_id).submitting ? '授权中…' : '授权' }}</button>
              </div>
              <div v-if="!configOf(p.platform_id).enabled" class="form-hint" style="margin-top:6px">
                启用前需确认平台接入风险告知；未启用时不发起任何该平台交互
              </div>
            </div>

            <!-- mock 平台：既有凭证输入 -->
            <template v-if="!isRealPlatform(p.platform_id) && p.auth_status !== 'authorized'">
              <div style="margin:-10px 0 10px">
                <input
                  class="input"
                  style="width:220px"
                  type="password"
                  v-model="formOf(p.platform_id).credential"
                  placeholder="输入授权凭证"
                  @keyup.enter="submitAuthorize(p)"
                >
                <button
                  class="btn btn-primary"
                  :disabled="formOf(p.platform_id).submitting"
                  @click="submitAuthorize(p)"
                >{{ formOf(p.platform_id).submitting ? '授权中…' : '授权' }}</button>
              </div>
              <div
                v-if="p.platform_id === 'mock_platform'"
                class="form-hint"
                style="margin:-6px 0 10px"
              >
                模拟平台演示凭证：valid-token（授权成功后自动拉取演示职位，即可体验筛选与投递全流程）
              </div>
            </template>

            <div v-for="pid in [p.platform_id]" :key="'err-' + pid">
              <div v-if="authForms[pid] && authForms[pid].error" class="form-error" style="margin:-6px 0 10px">
                {{ authForms[pid].error }}
              </div>
            </div>
          </template>
          <p class="muted">凭证加密存储，界面不回显明文；撤销后立即停止该平台一切投递行为</p>
        </template>
      </div>

      <div class="card">
        <div class="card-title">投递黑名单</div>
        <div class="row" style="margin-bottom:14px">
          <select class="select" style="width:150px" v-model="blForm.type">
            <option value="company">公司</option>
            <option value="keyword">职位关键词</option>
          </select>
          <input class="input" style="width:260px" v-model="blForm.content" placeholder="公司全名或职位关键词" @keyup.enter="addBlacklistEntry">
          <button class="btn btn-primary" :disabled="addingBl" @click="addBlacklistEntry">
            {{ addingBl ? '添加中…' : '添加' }}
          </button>
        </div>
        <div v-if="blError" class="form-error" style="margin-bottom:10px">{{ blError }}</div>

        <loading-skeleton v-if="blacklistState.phase === 'loading'" :rows="2"></loading-skeleton>
        <error-banner v-else-if="blacklistState.phase === 'error'" message="黑名单加载失败" @retry="loadBlacklist"></error-banner>
        <empty-state v-else-if="blacklistState.phase === 'empty'" message="暂无黑名单条目"></empty-state>
        <table v-else class="table">
          <thead><tr><th>类型</th><th>内容</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="e in blacklistState.items" :key="e.entry_id">
              <td><span class="badge badge-gray">{{ blacklistTypeLabel(e.type) }}</span></td>
              <td>{{ e.content }}</td>
              <td>
                <button class="btn btn-sm btn-danger" @click="removeEntry(e)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="muted" style="margin-top:10px">公司类型按全名精确匹配，关键词类型按职位名称包含匹配；变更后立即生效</p>
      </div>

      <!-- 风险告知确认弹窗（四项风险内容） -->
      <modal
        v-if="riskConfirmTarget"
        title="平台接入风险告知"
        :body="'即将启用「' + riskConfirmTarget.name + '」真实平台接入。请仔细阅读并知悉以下风险：\\n\\n' + RISK_DISCLOSURE.map((r, i) => (i + 1) + '. ' + r).join('\\n') + '\\n\\n确认后才开始启用；不确认则关闭弹窗，平台保持未启用。'"
        confirm-text="确认知悉并启用"
        :danger="true"
        @confirm="confirmRiskAndEnable"
        @cancel="riskConfirmTarget = null"
      ></modal>

      <!-- 禁用二次确认 -->
      <modal
        v-if="disableTarget"
        title="禁用平台"
        :body="'禁用「' + disableTarget.name + '」后将停止该平台一切交互（拉取/投递/状态同步），历史投递记录保留可查。确认禁用？'"
        confirm-text="确认禁用"
        :danger="true"
        @confirm="confirmDisable"
        @cancel="disableTarget = null"
      ></modal>

      <!-- 撤销授权二次确认 -->
      <modal
        v-if="revokeTarget"
        title="撤销平台授权"
        :body="'撤销后将立即停止「' + revokeTarget.name + '」的一切投递行为，进行中的投递任务会跳过该平台，浏览器会话与本地登录态将被清理。确认撤销？'"
        confirm-text="确认撤销"
        :danger="true"
        @confirm="confirmRevoke"
        @cancel="revokeTarget = null"
      ></modal>
    </div>
  `,
};