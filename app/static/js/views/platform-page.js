/** 平台授权与设置页：平台卡片（授权+可用性双状态）、凭证掩码授权、撤销二次确认、黑名单管理、降级标注 */

const PlatformPage = {
  components: { Modal, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    const { ref, reactive, onMounted } = Vue;

    /* ---------- 平台列表 ---------- */
    const platformsState = reactive({ phase: 'loading', items: [] });
    const authForms = reactive({});

    async function loadPlatforms() {
      platformsState.phase = 'loading';
      try {
        const data = await listPlatforms();
        platformsState.items = Array.isArray(data) ? data : [];
        platformsState.phase = platformsState.items.length > 0 ? 'ready' : 'empty';
        store.platforms = platformsState.items;
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

    /* ---------- 撤销授权（二次确认，含停止投递文案） ---------- */
    const revokeTarget = ref(null);

    async function confirmRevoke() {
      const target = revokeTarget.value;
      revokeTarget.value = null;
      if (!target) return;
      try {
        await revokePlatform(target.platform_id);
        showToast('已撤销「' + target.name + '」授权，立即停止该平台一切投递行为');
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
      await loadPlatforms();
      refreshGlobalSignals();
    }

    /* ---------- 黑名单管理 ---------- */
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
    });

    return {
      platformsState, authForms, formOf, submitAuthorize,
      revokeTarget, confirmRevoke,
      blacklistState, blForm, blError, addingBl, addBlacklistEntry, removeEntry,
      authStatusLabel, blacklistTypeLabel,
    };
  },
  template: `
    <div>
      <div class="card">
        <div class="card-title">招聘平台授权</div>
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
                </div>
                <div v-if="p.degraded" class="degraded-note">
                  暂不可用（仅浏览），恢复后自动补拉数据
                </div>
              </div>
              <div class="spacer"></div>
              <template v-if="p.auth_status === 'authorized'">
                <button class="btn btn-danger" @click="revokeTarget = p">撤销授权</button>
              </template>
              <template v-else>
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
              </template>
            </div>
            <div
              v-if="p.platform_id === 'mock_platform' && p.auth_status !== 'authorized'"
              class="form-hint"
              style="margin:-6px 0 10px"
            >
              模拟平台演示凭证：valid-token（授权成功后自动拉取 30 个演示职位，即可体验筛选与投递全流程）
            </div>
          </template>
          <div v-for="p in platformsState.items" :key="'err-' + p.platform_id">
            <div v-if="authForms[p.platform_id] && authForms[p.platform_id].error" class="form-error" style="margin:-6px 0 10px">
              {{ authForms[p.platform_id].error }}
            </div>
          </div>
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

      <modal
        v-if="revokeTarget"
        title="撤销平台授权"
        :body="'撤销后将立即停止「' + revokeTarget.name + '」的一切投递行为，进行中的投递任务会跳过该平台。确认撤销？'"
        confirm-text="确认撤销"
        :danger="true"
        @confirm="confirmRevoke"
        @cancel="revokeTarget = null"
      ></modal>
    </div>
  `,
};