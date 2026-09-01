<script setup>
// ============================================================
// Market.vue — 「哥特月夜 · 插件市场」
// 顶部：标题 + 搜索框 + 分类筛选
// 主体：毛玻璃卡片网格（icon / name / description / category / 工具数）
// 交互：安装→弹配置对话框（env_template 字段）/ 已安装→卸载
// ============================================================
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMarketList, installMcp, uninstallMcp, getInstalledList } from '../api/mcp'

// 路由实例：用于返回聊天页
const router = useRouter()

// —— 市场数据 ——
const marketList = ref([])          // 全量市场列表
const loading = ref(false)         // 列表加载态

// —— 搜索 & 分类筛选 ——
const keyword = ref('')
const activeCategory = ref('all')  // all 表示不限分类

// 从市场数据动态推导分类集合（去重）
const categories = computed(() => {
  const set = new Set()
  marketList.value.forEach(m => m.category && set.add(m.category))
  return ['all', ...Array.from(set)]
})

// 过滤后的可见列表
const filteredList = computed(() => {
  return marketList.value.filter(m => {
    const catOk = activeCategory.value === 'all' || m.category === activeCategory.value
    const kw = (keyword.value || '').trim().toLowerCase()
    const kwOk = !kw ||
      (m.name && m.name.toLowerCase().includes(kw)) ||
      (m.description && m.description.toLowerCase().includes(kw)) ||
      (m.mcp_id && m.mcp_id.toLowerCase().includes(kw))
    return catOk && kwOk
  })
})

// —— 已安装集合（用 Set 存 mcp_id，O(1) 查询）——
const installedSet = ref(new Set())

// —— 安装对话框 ——
const installDialogVisible = ref(false)
const currentMcp = ref(null)              // 当前要安装的 MCP 元数据
const envForm = ref({})                    // 表单值：{ KEY: VALUE }
const installing = ref(false)

/**
 * 加载市场列表
 * 后端 McpController 代理 Agent 时会双重包装：
 *   Agent 返回 {data: [...]} → 后端 Result.success(agentData) → {code, data: {data: [...]}}
 * 这里兜底解包到纯数组，避免 marketList 是对象导致 v-for/filter 报错
 */
const loadMarket = async () => {
  loading.value = true
  try {
    const raw = await getMarketList(activeCategory.value === 'all' ? null : activeCategory.value, keyword.value)
    // 第一层：axios 拦截器已解包 response.data，raw 是后端 Result 对象 {code, data}
    let list = Array.isArray(raw) ? raw : (raw?.data || raw?.list || [])
    // 第二层：后端 data 字段可能还是 {data: [...]}（Agent 原始结构透传），继续解包
    if (!Array.isArray(list) && list && typeof list === 'object') {
      list = list.data || list.list || []
    }
    marketList.value = Array.isArray(list) ? list : []
  } catch (e) {
    ElMessage.error('市场列表加载失败')
    // 降级：保持空数组，避免渲染崩溃
    marketList.value = []
  } finally {
    loading.value = false
  }
}

/**
 * 加载已安装列表，刷新 installedSet
 * 同样需要兜底双重解包（后端 McpInstallService 返回也是 Result 套 Agent 结构）
 */
const loadInstalled = async () => {
  try {
    const raw = await getInstalledList()
    let list = Array.isArray(raw) ? raw : (raw?.data || raw?.list || [])
    if (!Array.isArray(list) && list && typeof list === 'object') {
      list = list.data || list.list || []
    }
    installedSet.value = new Set((Array.isArray(list) ? list : []).map(item => item.mcpId || item.mcp_id || item))
  } catch (e) {
    // 静默失败：未登录或后端未就绪时不阻塞市场浏览
    installedSet.value = new Set()
  }
}

/**
 * 点击「安装」按钮：打开配置对话框
 * 根据 env_template 渲染表单字段
 */
const openInstallDialog = (mcp) => {
  currentMcp.value = mcp
  const fields = mcp?.env_template || []
  // 初始化表单：空字符串，避免 v-model 双向绑定 undefined
  const form = {}
  fields.forEach(f => { form[f.key] = '' })
  envForm.value = form
  installDialogVisible.value = true
}

/**
 * 确认安装：提交 env 表单
 */
const confirmInstall = async () => {
  const mcp = currentMcp.value
  if (!mcp) return
  // 必填校验：env_template 里 required=true 的字段不能为空
  const fields = mcp.env_template || []
  for (const f of fields) {
    if (f.required && !envForm.value[f.key]) {
      ElMessage.warning(`请填写：${f.label}`)
      return
    }
  }
  installing.value = true
  try {
    await installMcp(mcp.mcp_id, envForm.value)
    // 安装成功：加入已安装集合 + 关闭对话框 + 提示
    installedSet.value.add(mcp.mcp_id)
    // 强制触发响应式（Set 的 add 不会自动触发 ref 更新）
    installedSet.value = new Set(installedSet.value)
    installDialogVisible.value = false
    ElMessage.success(`「${mcp.name}」已安装`)
  } catch (e) {
    ElMessage.error('安装失败，请稍后重试')
  } finally {
    installing.value = false
  }
}

/**
 * 卸载 MCP（带二次确认）
 */
const handleUninstall = async (mcp) => {
  try {
    await ElMessageBox.confirm(
      `确定要卸载「${mcp.name}」吗？相关配置将被清除。`,
      '卸载确认',
      { confirmButtonText: '卸载', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    // 用户取消，不做任何事
    return
  }
  try {
    await uninstallMcp(mcp.mcp_id)
    installedSet.value.delete(mcp.mcp_id)
    installedSet.value = new Set(installedSet.value)
    ElMessage.success(`「${mcp.name}」已卸载`)
  } catch (e) {
    ElMessage.error('卸载失败，请稍后重试')
  }
}

// 组件挂载：并行加载市场列表与已安装列表
onMounted(() => {
  loadMarket()
  loadInstalled()
})
</script>

<template>
  <div class="market-container">
    <!-- ===== 顶部：标题 + 搜索 + 分类筛选 ===== -->
    <header class="market-header">
      <!-- 返回聊天页入口：放在左上角，避免进入市场后无法返回 -->
      <button class="market-back-btn" @click="router.push('/chat')" title="返回对话">
        <span class="market-back-btn__icon">←</span>
        <span>返回对话</span>
      </button>
      <div class="market-title-row">
        <h1 class="market-title">插件市场</h1>
        <p class="market-subtitle">MCP Registry · 月下典藏</p>
      </div>

      <div class="market-toolbar">
        <el-input
          v-model="keyword"
          class="search-input"
          placeholder="搜索插件名 / 描述 / 标识…"
          clearable
          @keyup.enter="loadMarket"
        />
        <el-button class="search-btn" @click="loadMarket">检索</el-button>
      </div>

      <!-- 分类标签 -->
      <div class="category-tags">
        <span
          v-for="cat in categories"
          :key="cat"
          class="category-tag"
          :class="{ 'category-tag--active': activeCategory === cat }"
          @click="activeCategory = cat"
        >
          {{ cat === 'all' ? '全部' : cat }}
        </span>
      </div>
    </header>

    <!-- ===== 主体：卡片网格 ===== -->
    <main class="market-grid" v-loading="loading">
      <el-empty
        v-if="!loading && filteredList.length === 0"
        description="月下无此典藏"
        class="market-empty"
      />

      <article
        v-for="mcp in filteredList"
        :key="mcp.mcp_id"
        class="mcp-card"
        :class="{ 'mcp-card--installed': installedSet.has(mcp.mcp_id) }"
      >
        <!-- 已安装角标 -->
        <span v-if="installedSet.has(mcp.mcp_id)" class="installed-badge">已安装</span>

        <div class="mcp-icon">{{ mcp.icon || '📦' }}</div>

        <div class="mcp-body">
          <div class="mcp-name-row">
            <h3 class="mcp-name">{{ mcp.name }}</h3>
            <el-tag v-if="mcp.category" size="small" class="mcp-category-tag">{{ mcp.category }}</el-tag>
          </div>
          <p class="mcp-desc">{{ mcp.description || '暂无描述' }}</p>

          <div class="mcp-meta">
            <span class="mcp-tools-count">
              工具 · {{ (mcp.tools && mcp.tools.length) || 0 }}
            </span>
            <span v-if="mcp.author" class="mcp-author">著者 · {{ mcp.author }}</span>
          </div>
        </div>

        <!-- 操作区 -->
        <div class="mcp-actions">
          <button
            v-if="!installedSet.has(mcp.mcp_id)"
            class="action-btn action-btn--install"
            @click="openInstallDialog(mcp)"
          >
            安装
          </button>
          <button
            v-else
            class="action-btn action-btn--uninstall"
            @click="handleUninstall(mcp)"
          >
            卸载
          </button>
        </div>
      </article>
    </main>

    <!-- ===== 安装配置对话框 ===== -->
    <el-dialog
      v-model="installDialogVisible"
      :title="currentMcp ? `配置 · ${currentMcp.name}` : '配置'"
      width="520px"
      :close-on-click-modal="false"
      class="install-dialog"
    >
      <el-form label-position="top" class="env-form">
        <el-form-item
          v-for="field in (currentMcp?.env_template || [])"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <el-input
            v-model="envForm[field.key]"
            :type="field.type === 'password' ? 'password' : 'text'"
            :show-password="field.type === 'password'"
            :placeholder="field.help || `请输入 ${field.label}`"
          />
          <div v-if="field.help" class="field-help">{{ field.help }}</div>
        </el-form-item>

        <el-empty
          v-if="currentMcp && !(currentMcp.env_template && currentMcp.env_template.length)"
          description="此插件无需配置项"
          :image-size="80"
        />
      </el-form>

      <template #footer>
        <el-button @click="installDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="installing" @click="confirmInstall">
          {{ installing ? '正在安装…' : '确认安装' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ============================================================
 * 哥特月夜 · 插件市场
 * 背景透明继承 body 星空，卡片用毛玻璃，月光紫/朱砂红配色
 * ============================================================ */
.market-container {
  min-height: 100vh;
  padding: 40px clamp(20px, 4vw, 64px) 80px;
  position: relative;
}

/* ===== 顶部 ===== */
.market-header {
  max-width: 1280px;
  margin: 0 auto 36px;
}
/* 返回对话按钮：细边框胶囊，月光紫 hover，放在市场页左上角 */
.market-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--line-glow);
  color: var(--text-secondary);
  padding: 7px 16px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 1px;
  cursor: pointer;
  margin-bottom: 18px;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.market-back-btn__icon { font-size: 14px; line-height: 1; }
.market-back-btn:hover {
  background: rgba(139, 124, 255, 0.14);
  border-color: var(--moonlight-300);
  color: #fff;
  transform: translateX(-2px);
}
.market-title-row {
  display: flex;
  align-items: baseline;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}
.market-title {
  font-family: var(--font-display);
  font-size: 42px;
  font-weight: 700;
  letter-spacing: 6px;
  background: linear-gradient(180deg, #fff 0%, #d9d5ff 55%, #9a8cff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  line-height: 1.1;
}
.market-subtitle {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 14px;
  letter-spacing: 3px;
  color: var(--text-tertiary);
}

.market-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
}
.search-input {
  flex: 1;
  max-width: 560px;
}
.search-btn {
  background: linear-gradient(135deg, var(--moonlight-400), var(--moonlight-500)) !important;
  border: 1px solid rgba(255,255,255,0.25) !important;
  color: var(--text-inverse) !important;
  letter-spacing: 2px !important;
  font-family: var(--font-display) !important;
}
.search-btn:hover {
  filter: brightness(1.08);
}

/* 分类标签 */
.category-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.category-tag {
  padding: 6px 16px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 1px;
  color: var(--text-secondary);
  background: rgba(169, 156, 255, 0.06);
  border: 1px solid rgba(169, 156, 255, 0.2);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out-expo);
  user-select: none;
}
.category-tag:hover {
  color: var(--moonlight-100);
  border-color: var(--line-glow);
  background: rgba(169, 156, 255, 0.12);
}
.category-tag--active {
  color: var(--text-inverse);
  background: linear-gradient(135deg, var(--moonlight-400), var(--moonlight-500));
  border-color: rgba(255,255,255,0.32);
  box-shadow: 0 6px 18px -6px rgba(139, 124, 255, 0.65);
}

/* ===== 卡片网格 ===== */
.market-grid {
  max-width: 1280px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 22px;
  min-height: 200px;
}
.market-empty {
  grid-column: 1 / -1;
  padding: 60px 0;
}

/* 单个 MCP 卡片：毛玻璃 + 月光描边 */
.mcp-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 22px 22px 18px;
  border-radius: 18px;
  background: linear-gradient(180deg,
    rgba(21, 26, 68, 0.55) 0%,
    rgba(11, 14, 46, 0.68) 100%);
  border: 1px solid rgba(169, 156, 255, 0.2);
  backdrop-filter: blur(12px) saturate(135%);
  -webkit-backdrop-filter: blur(12px) saturate(135%);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.03) inset,
    0 18px 44px -22px rgba(0, 0, 0, 0.7),
    0 10px 30px -18px rgba(139, 124, 255, 0.25);
  transition: transform var(--dur-base) var(--ease-out-expo),
              border-color var(--dur-base) var(--ease-out-expo),
              box-shadow var(--dur-base) var(--ease-out-expo);
  overflow: hidden;
}
.mcp-card:hover {
  transform: translateY(-4px);
  border-color: var(--line-glow);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.06) inset,
    0 28px 60px -24px rgba(0, 0, 0, 0.8),
    0 18px 40px -18px rgba(139, 124, 255, 0.5);
}
/* 已安装卡片：左侧朱砂细条 */
.mcp-card--installed::before {
  content: '';
  position: absolute;
  left: 0; top: 16px; bottom: 16px;
  width: 2px;
  background: linear-gradient(180deg, transparent, var(--crimson-400), transparent);
  box-shadow: 0 0 8px rgba(200, 16, 46, 0.6);
}

/* 已安装角标 */
.installed-badge {
  position: absolute;
  top: 14px; right: 14px;
  padding: 3px 10px;
  font-size: 11px;
  letter-spacing: 1.5px;
  font-family: var(--font-display);
  color: var(--crimson-100);
  background: rgba(200, 16, 46, 0.16);
  border: 1px solid var(--line-crimson);
  border-radius: 999px;
}

.mcp-icon {
  font-size: 38px;
  line-height: 1;
  filter: drop-shadow(0 4px 12px rgba(139, 124, 255, 0.4));
}

.mcp-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mcp-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.mcp-name {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--moonlight-100);
}
.mcp-category-tag {
  background: rgba(169, 156, 255, 0.12) !important;
  border-color: var(--line-soft) !important;
  color: var(--moonlight-300) !important;
}
.mcp-desc {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  flex: 1;
}
.mcp-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  letter-spacing: 0.5px;
  color: var(--text-tertiary);
  font-family: var(--font-display);
  font-style: italic;
}
.mcp-tools-count {
  color: var(--moonlight-300);
}

/* 操作区按钮 */
.mcp-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
.action-btn {
  padding: 9px 22px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 2px;
  font-family: var(--font-display);
  cursor: pointer;
  border: 1px solid rgba(255,255,255,0.22);
  transition: transform var(--dur-fast) var(--ease-out-expo),
              box-shadow var(--dur-fast) var(--ease-out-expo),
              filter var(--dur-fast) var(--ease-out-expo);
}
.action-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.08);
}
/* 安装按钮：月光紫渐变 */
.action-btn--install {
  background: linear-gradient(135deg, var(--moonlight-400) 0%, var(--moonlight-500) 100%);
  color: var(--text-inverse);
  box-shadow: 0 12px 28px -12px rgba(139, 124, 255, 0.85);
}
/* 卸载按钮：朱砂红渐变 */
.action-btn--uninstall {
  background: linear-gradient(135deg, var(--crimson-400) 0%, var(--crimson-500) 100%);
  color: #fff;
  box-shadow: 0 12px 28px -12px rgba(200, 16, 46, 0.8);
}

/* ===== 安装对话框 ===== */
.install-dialog .env-form {
  padding: 4px 4px 8px;
}
.field-help {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-display);
  font-style: italic;
  letter-spacing: 0.5px;
}

/* 响应式：窄屏单列 */
@media (max-width: 680px) {
  .market-grid {
    grid-template-columns: 1fr;
  }
  .market-toolbar {
    flex-direction: column;
  }
}
</style>
