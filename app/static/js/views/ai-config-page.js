/** AI 模型配置页：服务商六选一、Key 配置（不回显）、连通性测试、单激活、脱敏与成本设置。 */

const AiConfigPage = {
  components: { Modal, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    const { ref, reactive, computed, onMounted } = Vue;

    /* ---------- 配置列表 ---------- */
    const configsState = reactive({ phase: 'loading', items: [] });

    async function loadConfigs() {
      configsState.phase = 'loading';
      try {
        const data = await listAiModelConfigs();
        configsState.items = Array.isArray(data) ? data : [];
        configsState.phase = configsState.items.length > 0 ? 'ready' : 'empty';
      } catch (e) {
        configsState.phase = 'error';
      }
    }

    /* ---------- 服务商预设（与后端 presets.py 对齐） ---------- */
    const providers = [
      { value: 'deepseek', label: 'DeepSeek', note: '性价比高，国内直连', model: 'deepseek-chat', needsKey: true },
      { value: 'qwen', label: '通义千问', note: '阿里云百炼兼容模式', model: 'qwen-plus', needsKey: true },
      { value: 'kimi', label: 'Kimi（月之暗面）', note: '长上下文', model: 'moonshot-v1-8k', needsKey: true },
      { value: 'zhipu', label: '智谱 GLM', note: 'GLM 系列', model: 'glm-4-flash', needsKey: true },
      { value: 'pangu', label: '华为云磐古大模型', note: '华为云 ModelArts 大模型服务，用户自带 Key', model: 'pangu-nlp', needsKey: true },
      { value: 'openai_compat', label: 'OpenAI 兼容接口', note: '自定义兼容服务必填接口地址', model: 'gpt-4o-mini', needsKey: true },
      { value: 'ollama', label: '本地 Ollama', note: '数据不出本机，需本机已启动 Ollama', model: 'qwen2.5:7b', needsKey: false },
    ];

    function providerOf(value) {
      return providers.find((p) => p.value === value) || providers[0];
    }

    /* ---------- 新建/编辑表单 ---------- */
    const form = reactive({
      editingId: '',
      name: '',
      provider: 'deepseek',
      base_url: '',
      model_name: '',
      api_key: '',
      error: '',
    });
    const showForm = ref(false);
    const saving = ref(false);

    function openCreate() {
      form.editingId = '';
      form.name = '';
      form.provider = 'deepseek';
      form.base_url = '';
      form.model_name = '';
      form.api_key = '';
      form.error = '';
      showForm.value = true;
    }

    function openEdit(config) {
      form.editingId = config.config_id;
      form.name = config.name;
      form.provider = config.provider;
      form.base_url = config.base_url;
      form.model_name = config.model_name;
      form.api_key = '';
      form.error = '';
      showForm.value = true;
    }

    function onProviderChange() {
      const preset = providerOf(form.provider);
      if (!form.model_name) form.model_name = preset.model;
    }

    async function saveConfig() {
      form.error = '';
      if (!form.name.trim()) {
        form.error = '请填写配置名称';
        return;
      }
      const preset = providerOf(form.provider);
      if (form.provider === 'openai_compat' && !form.base_url.trim()) {
        form.error = '自定义兼容接口必须填写接口地址';
        return;
      }
      if (preset.needsKey && !form.editingId && !form.api_key.trim()) {
        form.error = '云端服务商必须配置您自己的 API Key';
        return;
      }
      saving.value = true;
      try {
        if (form.editingId) {
          const patch = {
            name: form.name.trim(),
            base_url: form.base_url.trim() || null,
            model_name: form.model_name.trim() || null,
          };
          if (form.api_key.trim()) patch.api_key = form.api_key.trim();
          await updateAiModelConfig(form.editingId, patch);
          showToast('配置已更新');
        } else {
          await createAiModelConfig({
            name: form.name.trim(),
            provider: form.provider,
            base_url: form.base_url.trim() || null,
            model_name: form.model_name.trim() || preset.model,
            api_key: form.api_key.trim() || null,
          });
          showToast('配置已创建，建议先进行连通性测试');
        }
        showForm.value = false;
        await loadConfigs();
      } catch (e) {
        form.error = errorText(e, 'form');
      } finally {
        saving.value = false;
      }
    }

    /* ---------- 连通性测试 ---------- */
    const testingId = ref('');
    const testResults = reactive({});

    async function runTest(config) {
      testingId.value = config.config_id;
      try {
        const result = await testAiModelConfig(config.config_id);
        testResults[config.config_id] = result;
        if (result.status === 'success') {
          showToast('连通正常（' + result.duration_ms + ' ms）');
        } else {
          showToast(result.message || '测试失败', 'failure');
        }
        await loadConfigs();
      } catch (e) {
        showToast(errorText(e), 'failure');
      } finally {
        testingId.value = '';
      }
    }

    /* ---------- 激活 ---------- */
    const activateTarget = ref(null);

    function askActivate(config) {
      if (config.last_test_status === 'success') {
        doActivate(config.config_id, false);
        return;
      }
      activateTarget.value = config;
    }

    async function confirmForceActivate() {
      const target = activateTarget.value;
      activateTarget.value = null;
      if (!target) return;
      await doActivate(target.config_id, true);
    }

    async function doActivate(configId, force) {
      try {
        await activateAiModelConfig(configId, force);
        showToast('已激活，AI 评分与 AI 招呼语即生效');
        await loadConfigs();
        refreshGlobalSignals();
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      }
    }

    /* ---------- 删除（二次确认） ---------- */
    const deleteTarget = ref(null);

    async function confirmDelete() {
      const target = deleteTarget.value;
      deleteTarget.value = null;
      if (!target) return;
      try {
        await deleteAiModelConfig(target.config_id);
        showToast('配置已删除');
        await loadConfigs();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- AI 设置（脱敏与成本） ---------- */
    const settingsState = reactive({ phase: 'loading' });
    const settingsForm = reactive({
      ai_enabled: true,
      ai_mask_enabled: true,
      ai_mask_fields: ['phone', 'email'],
      ai_jd_truncate_limit: 2000,
      ai_resume_truncate_limit: 3000,
      ai_greeting_max_len: 200,
      ai_greeting_tone: 'professional',
      ai_send_full_resume: false,
    });
    const settingsNotice = ref('');
    const savingSettings = ref(false);

    async function loadSettings() {
      settingsState.phase = 'loading';
      try {
        const data = await getAiSettings();
        Object.assign(settingsForm, data);
        settingsState.phase = 'ready';
      } catch (e) {
        settingsState.phase = 'error';
      }
    }

    async function saveSettings() {
      savingSettings.value = true;
      settingsNotice.value = '';
      try {
        const result = await updateAiSettings(settingsForm);
        if (result && result.risk_notice) settingsNotice.value = result.risk_notice;
        showToast('AI 设置已保存');
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      } finally {
        savingSettings.value = false;
      }
    }

    onMounted(() => {
      loadConfigs();
      loadSettings();
    });

    return {
      configsState, loadConfigs,
      providers, providerOf,
      form, showForm, saving, openCreate, openEdit, onProviderChange, saveConfig,
      testingId, testResults, runTest,
      activateTarget, askActivate, confirmForceActivate,
      deleteTarget, confirmDelete,
      settingsState, settingsForm, settingsNotice, savingSettings, loadSettings, saveSettings,
      formatTime,
    };
  },
  template: `
    <div>
      <div class="card">
        <div class="card-title">
          <span>AI 模型服务配置</span>
          <button class="btn btn-primary" @click="openCreate">新增配置</button>
        </div>
        <loading-skeleton v-if="configsState.phase === 'loading'" :rows="3"></loading-skeleton>
        <error-banner v-else-if="configsState.phase === 'error'" message="配置列表加载失败" @retry="loadConfigs"></error-banner>
        <empty-state v-else-if="configsState.phase === 'empty'" message="尚未配置模型服务。未配置时软件使用规则评分与固定模板招呼语，全部功能不受影响"></empty-state>
        <template v-else>
          <div v-for="c in configsState.items" :key="c.config_id" class="platform-card">
            <div>
              <div class="platform-name">
                {{ c.name }}
                <span :class="['badge', c.is_active ? 'badge-green' : 'badge-gray']" style="margin-left:8px">
                  {{ c.is_active ? '使用中' : '未激活' }}
                </span>
                <span v-if="c.has_api_key" class="badge badge-blue" style="margin-left:6px">已配置 Key</span>
                <span v-if="c.degraded" class="badge badge-orange" style="margin-left:6px">冷却中</span>
              </div>
              <div class="muted">{{ providerOf(c.provider).label }} · {{ c.model_name }} · {{ c.base_url }}</div>
              <div class="muted">最近测试：
                <span :class="['badge', 'badge-' + (c.last_test_status === 'success' ? 'green' : c.last_test_status === 'none' ? 'gray' : 'orange')]" style="margin:0 6px 0 0">
                  {{ c.last_test_status === 'success' ? '成功' : c.last_test_status === 'none' ? '未测试' : c.last_test_status === 'invalid_key' ? 'Key 无效' : c.last_test_status === 'insufficient_quota' ? '余额不足' : '不可达' }}
                </span>
                {{ c.last_test_at ? formatTime(c.last_test_at) : '' }}
              </div>
              <div v-if="c.degraded_reason" class="degraded-note">{{ c.last_test_message }}</div>
            </div>
            <div class="spacer"></div>
            <div class="row">
              <button class="btn btn-sm" :disabled="testingId === c.config_id" @click="runTest(c)">
                {{ testingId === c.config_id ? '测试中…' : '测试连通' }}
              </button>
              <button v-if="!c.is_active" class="btn btn-sm btn-primary" @click="askActivate(c)">激活</button>
              <button class="btn btn-sm" @click="openEdit(c)">编辑</button>
              <button v-if="!c.is_active" class="btn btn-sm btn-danger" @click="deleteTarget = c">删除</button>
            </div>
          </div>
          <p class="muted">多配置仅一个激活；激活前建议先通过连通性测试。软件不内置任何 Key，请使用您自己的 API Key。</p>
        </template>
      </div>

      <!-- 新建/编辑弹层 -->
      <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
        <div class="modal-box" style="max-width:560px">
          <h3 class="modal-title">{{ form.editingId ? '编辑模型配置' : '新增模型配置' }}</h3>
          <div class="form-grid">
            <div class="form-item">
              <label>配置名称</label>
              <input class="input" v-model="form.name" placeholder="如 我的 DeepSeek">
            </div>
            <div class="form-item">
              <label>服务商</label>
              <select class="select" v-model="form.provider" @change="onProviderChange">
                <option v-for="p in providers" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>
            <div class="form-item">
              <label>接口地址（{{ providerOf(form.provider).needsKey ? '可选，默认官方端点' : '默认本机 11434' }}）</label>
              <input class="input" v-model="form.base_url" :placeholder="form.provider === 'openai_compat' ? '必填：https://your-service/v1' : '留空使用默认'">
            </div>
            <div class="form-item">
              <label>模型名称</label>
              <input class="input" v-model="form.model_name" :placeholder="providerOf(form.provider).model">
            </div>
            <div class="form-item" v-if="providerOf(form.provider).needsKey">
              <label>API Key{{ form.editingId ? '（留空保留原 Key）' : '' }}</label>
              <input class="input" type="password" v-model="form.api_key" placeholder="粘贴您的 API Key">
            </div>
          </div>
          <p class="muted" style="margin:8px 0">{{ providerOf(form.provider).note }}</p>
          <div v-if="form.error" class="form-error" style="margin-bottom:10px">{{ form.error }}</div>
          <div class="modal-actions">
            <button class="btn" @click="showForm = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="saveConfig">
              {{ saving ? '保存中…' : (form.editingId ? '保存修改' : '创建配置') }}
            </button>
          </div>
        </div>
      </div>

      <!-- AI 设置 -->
      <div class="card">
        <div class="card-title">AI 个性化设置</div>
        <loading-skeleton v-if="settingsState.phase === 'loading'" :rows="3"></loading-skeleton>
        <error-banner v-else-if="settingsState.phase === 'error'" message="设置加载失败" @retry="loadSettings"></error-banner>
        <template v-else>
          <div class="row" style="margin-bottom:14px">
            <label class="checkbox-label"><input type="checkbox" v-model="settingsForm.ai_enabled"> 启用 AI 评分与 AI 招呼语</label>
          </div>
          <div class="form-grid">
            <div class="form-item">
              <label>简历脱敏</label>
              <label class="checkbox-label"><input type="checkbox" v-model="settingsForm.ai_mask_enabled"> 遮蔽手机号/邮箱后发送</label>
            </div>
            <div class="form-item">
              <label>发送完整简历（风险自担）</label>
              <label class="checkbox-label"><input type="checkbox" v-model="settingsForm.ai_send_full_resume"> 不脱敏直接发送</label>
            </div>
            <div class="form-item">
              <label>JD 截断上限（字符）</label>
              <input class="input" type="number" min="500" max="20000" v-model.number="settingsForm.ai_jd_truncate_limit">
            </div>
            <div class="form-item">
              <label>简历截断上限（字符）</label>
              <input class="input" type="number" min="500" max="50000" v-model.number="settingsForm.ai_resume_truncate_limit">
            </div>
            <div class="form-item">
              <label>招呼语长度上限</label>
              <input class="input" type="number" min="50" max="1000" v-model.number="settingsForm.ai_greeting_max_len">
            </div>
            <div class="form-item">
              <label>招呼语语气</label>
              <select class="select" v-model="settingsForm.ai_greeting_tone">
                <option value="professional">稳重专业</option>
                <option value="enthusiastic">热情积极</option>
              </select>
            </div>
          </div>
          <div v-if="settingsNotice" class="banner banner-warn" style="margin-top:12px">{{ settingsNotice }}</div>
          <div class="banner banner-info" style="margin-top:12px">
            发送范围说明：简历内容（脱敏后）与职位描述将发送至您所配置的模型服务；选择本地 Ollama 时数据不出本机。
          </div>
          <div class="row" style="margin-top:14px">
            <button class="btn btn-primary" :disabled="savingSettings" @click="saveSettings">
              {{ savingSettings ? '保存中…' : '保存设置' }}
            </button>
          </div>
        </template>
      </div>

      <!-- 强制激活确认 -->
      <modal
        v-if="activateTarget"
        title="激活未通过测试的配置"
        :body="'配置「' + activateTarget.name + '」最近一次连通性测试未成功。未测试/失败的配置可能无法完成 AI 评分与招呼语生成（届时自动回退规则评分）。确认强制激活？'"
        confirm-text="确认强制激活"
        :danger="true"
        @confirm="confirmForceActivate"
        @cancel="activateTarget = null"
      ></modal>

      <!-- 删除确认 -->
      <modal
        v-if="deleteTarget"
        title="删除模型配置"
        :body="'确认删除配置「' + deleteTarget.name + '」？删除后不可恢复。'"
        confirm-text="确认删除"
        :danger="true"
        @confirm="confirmDelete"
        @cancel="deleteTarget = null"
      ></modal>
    </div>
  `,
};