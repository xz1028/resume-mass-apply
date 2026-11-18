/** 简历管理页：档案列表（默认标识）、上传（前置校验+进度）、设默认/重命名/删除、意向表单 */

const { ref: _ref, reactive: _reactive, onMounted: _onMounted } = Vue;

const ResumePage = {
  components: { Modal, EmptyState, LoadingSkeleton, ErrorBanner },
  setup() {
    /* ---------- 档案列表 ---------- */
    const listPhase = _ref('loading');
    const resumes = _ref([]);
    const listError = _ref(null);

    async function loadResumes() {
      listPhase.value = 'loading';
      try {
        const data = await listResumes();
        resumes.value = Array.isArray(data) ? data : [];
        listPhase.value = resumes.value.length > 0 ? 'ready' : 'empty';
      } catch (e) {
        if (e && e.name === 'AbortError') return;
        listError.value = e;
        listPhase.value = 'error';
      }
    }

    /* ---------- 上传（前置校验 + 进度反馈） ---------- */
    const uploading = _ref(false);
    const uploadProgress = _ref(0);
    const uploadError = _ref('');
    const ALLOWED_EXT = ['pdf', 'doc', 'docx'];
    const MAX_SIZE_BYTES = 20 * 1024 * 1024;

    function validateFile(file) {
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      if (ALLOWED_EXT.indexOf(ext) < 0) return '仅支持 PDF 或 Word 格式（错误码 40001）';
      if (file.size > MAX_SIZE_BYTES) return '文件大小超过限制（20MB）（错误码 40002）';
      return '';
    }

    async function onFileChange(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      if (!file || uploading.value) return;
      uploadError.value = validateFile(file);
      if (uploadError.value) return;
      uploading.value = true;
      uploadProgress.value = 0;
      try {
        await uploadResume(file, (percent) => { uploadProgress.value = percent; });
        showToast('简历上传成功');
        await loadResumes();
        refreshGlobalSignals();
      } catch (e) {
        uploadError.value = errorText(e, 'upload');
      } finally {
        uploading.value = false;
      }
    }

    /* ---------- 设为默认 ---------- */
    async function onSetDefault(resume) {
      try {
        await setDefaultResume(resume.resume_id);
        showToast('已设为默认简历：' + resume.name);
        await loadResumes();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- 重命名（40004 内联提示，不关闭编辑态） ---------- */
    const renaming = _ref(null);
    const renameError = _ref('');

    function startRename(resume) {
      renaming.value = { resume_id: resume.resume_id, name: resume.name };
      renameError.value = '';
    }

    function cancelRename() {
      renaming.value = null;
      renameError.value = '';
    }

    async function submitRename() {
      if (!renaming.value || !renaming.value.name.trim()) {
        renameError.value = '档案名称不能为空';
        return;
      }
      try {
        await renameResume(renaming.value.resume_id, renaming.value.name.trim());
        showToast('重命名成功');
        renaming.value = null;
        renameError.value = '';
        await loadResumes();
      } catch (e) {
        renameError.value = errorText(e, 'form');
      }
    }

    /* ---------- 删除（二次确认，含快照保留说明） ---------- */
    const deleteTarget = _ref(null);

    async function confirmDelete() {
      const target = deleteTarget.value;
      deleteTarget.value = null;
      if (!target) return;
      try {
        await deleteResume(target.resume_id);
        showToast('简历已删除');
        await loadResumes();
        refreshGlobalSignals();
      } catch (e) {
        showToast(errorText(e), 'failure');
      }
    }

    /* ---------- 求职意向与联系方式表单 ---------- */
    const profileForm = _reactive({
      phone: '', email: '', city: '', salary_min: '', salary_max: '', industry: '',
    });
    const profileError = _ref('');
    const savingProfile = _ref(false);

    async function loadProfile() {
      try {
        const p = await getProfile();
        const contact = p.contact || {};
        const intent = p.intention || {};
        profileForm.phone = contact.phone || '';
        profileForm.email = contact.email || '';
        profileForm.city = intent.city || '';
        profileForm.salary_min = intent.salary_min != null ? intent.salary_min : '';
        profileForm.salary_max = intent.salary_max != null ? intent.salary_max : '';
        profileForm.industry = intent.industry || '';
      } catch (e) { /* 回显失败保持表单默认值 */ }
    }

    function validContact() {
      const phone = (profileForm.phone || '').trim();
      const email = (profileForm.email || '').trim();
      const phoneOk = /^1[3-9]\d{9}$/.test(phone);
      const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
      return phoneOk || emailOk;
    }

    async function saveProfile() {
      profileError.value = '';
      if (!validContact()) {
        profileError.value = '请输入有效的手机号或邮箱';
        return;
      }
      savingProfile.value = true;
      try {
        await updateProfile({
          user_id: 'local_user',
          contact: {
            phone: (profileForm.phone || '').trim() || null,
            email: (profileForm.email || '').trim() || null,
          },
          intention: {
            city: (profileForm.city || '').trim() || null,
            salary_min: profileForm.salary_min ? Number(profileForm.salary_min) : null,
            salary_max: profileForm.salary_max ? Number(profileForm.salary_max) : null,
            industry: (profileForm.industry || '').trim() || null,
          },
        });
        showToast('求职意向已保存，下个拉取周期按新意向执行');
      } catch (e) {
        showToast(errorText(e, 'form'), 'failure');
      } finally {
        savingProfile.value = false;
      }
    }

    _onMounted(() => {
      loadResumes();
      loadProfile();
    });

    return {
      listPhase, resumes, listError, loadResumes,
      uploading, uploadProgress, uploadError, onFileChange,
      onSetDefault,
      renaming, renameError, startRename, cancelRename, submitRename,
      deleteTarget, confirmDelete,
      profileForm, profileError, savingProfile, saveProfile,
      formatSize, formatTime,
    };
  },
  template: `
    <div>
      <div class="card">
        <div class="card-title">
          <span>简历档案</span>
          <label class="btn btn-primary" :class="{ disabled: uploading }" style="cursor:pointer">
            <input
              type="file"
              hidden
              accept=".pdf,.doc,.docx"
              :disabled="uploading"
              @change="onFileChange"
            >{{ uploading ? '上传中…' : '上传简历' }}
          </label>
        </div>
        <div v-if="uploadError" class="banner banner-warn">{{ uploadError }}</div>
        <div v-if="uploading" class="row" style="margin-bottom:14px">
          <div class="progress-track"><div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div></div>
          <span class="muted">{{ uploadProgress }}%</span>
        </div>

        <loading-skeleton v-if="listPhase === 'loading'" :rows="4"></loading-skeleton>
        <error-banner
          v-else-if="listPhase === 'error'"
          message="简历列表加载失败"
          @retry="loadResumes"
        ></error-banner>
        <empty-state
          v-else-if="listPhase === 'empty'"
          message="请先上传简历，上传后即可开始职位推荐与批量投递"
        ></empty-state>
        <table v-else class="table">
          <thead>
            <tr><th>档案名称</th><th>格式</th><th>大小</th><th>创建时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in resumes" :key="r.resume_id">
              <td>
                <template v-if="renaming && renaming.resume_id === r.resume_id">
                  <input class="input" v-model="renaming.name" @keyup.enter="submitRename">
                  <div v-if="renameError" class="form-error">{{ renameError }}</div>
                </template>
                <template v-else>
                  <span>{{ r.name }}</span>
                  <span v-if="r.is_default" class="badge badge-blue" style="margin-left:8px">默认</span>
                </template>
              </td>
              <td>{{ r.format }}</td>
              <td>{{ formatSize(r.size_bytes) }}</td>
              <td>{{ formatTime(r.created_at) }}</td>
              <td>
                <div class="cell-actions">
                  <template v-if="renaming && renaming.resume_id === r.resume_id">
                    <button class="btn btn-sm btn-primary" @click="submitRename">保存</button>
                    <button class="btn btn-sm" @click="cancelRename">取消</button>
                  </template>
                  <template v-else>
                    <button v-if="!r.is_default" class="btn btn-sm" @click="onSetDefault(r)">设为默认</button>
                    <button class="btn btn-sm" @click="startRename(r)">重命名</button>
                    <button class="btn btn-sm btn-danger" @click="deleteTarget = r">删除</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-title">求职意向与联系方式</div>
        <div class="form-grid">
          <div class="form-item">
            <label>手机号</label>
            <input class="input" v-model="profileForm.phone" placeholder="13800138000">
          </div>
          <div class="form-item">
            <label>邮箱</label>
            <input class="input" v-model="profileForm.email" placeholder="user@example.com">
          </div>
          <div class="form-item">
            <label>期望城市</label>
            <input class="input" v-model="profileForm.city" placeholder="深圳">
          </div>
          <div class="form-item">
            <label>期望最低薪资（元/月）</label>
            <input class="input" type="number" v-model="profileForm.salary_min" placeholder="15000">
          </div>
          <div class="form-item">
            <label>期望最高薪资（元/月）</label>
            <input class="input" type="number" v-model="profileForm.salary_max" placeholder="30000">
          </div>
          <div class="form-item">
            <label>期望行业</label>
            <input class="input" v-model="profileForm.industry" placeholder="互联网">
          </div>
        </div>
        <div v-if="profileError" class="form-error" style="margin-top:10px">{{ profileError }}</div>
        <div class="row" style="margin-top:14px">
          <button class="btn btn-primary" :disabled="savingProfile" @click="saveProfile">
            {{ savingProfile ? '保存中…' : '保存意向' }}
          </button>
          <span class="muted">联系方式用于投递请求，必须为有效手机号或邮箱</span>
        </div>
      </div>

      <modal
        v-if="deleteTarget"
        title="删除简历档案"
        :body="'删除后档案不可恢复。历史投递记录仍会保留投递时的简历版本信息（快照）。确认删除「' + deleteTarget.name + '」？'"
        confirm-text="确认删除"
        :danger="true"
        @confirm="confirmDelete"
        @cancel="deleteTarget = null"
      ></modal>
    </div>
  `,
};