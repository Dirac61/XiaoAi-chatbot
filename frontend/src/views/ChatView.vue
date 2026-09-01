<script setup>import { nextTick, onBeforeUnmount, onMounted, ref, reactive, watch } from 'vue';
import { useRouter } from 'vue-router';
import service from '../api/index.js';
import { marked } from 'marked';

// Markdown渲染函数（升级：启用 GFM 风格的表格 / 删除线 / task-list，仍保持 breaks=true 换行）
const renderMarkdown = (text) => {
  if (!text) return '';
  return marked.parse ? marked.parse(text, { breaks: true, gfm: true }) : marked(text, { breaks: true });
};

/* ============================================================
 * 前端美化 · 「全开」动效增强：
 *   1) 流式回复末尾添加「打字光标」caret（isLoading 时给 botMsg 加 class）
 *   2) 主按钮（发送/新建会话/模式切换）支持点击涟漪 data-ripple=true
 *   3) 主按钮 / 会话项 / 气泡 支持轻量 mousemove 磁性 / 3D 微倾斜
 *   4) reduce-motion 全部降级为静态（不在此处额外处理，依赖 media query）
 * ============================================================ */
let magentCleanup = null;

/* 磁性 & 3D 倾斜：作用于 .magent / .tilt 容器（rAF 节流，轻量） */
const attachMagent = () => {
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return;

  let rafId = null;
  let target = null;
  let cx = 0, cy = 0;

  const onMove = (e) => {
    // 找最近的 .magent 或 .tilt（.magent 偏平移，.tilt 偏 3D 旋转）
    const host = e.target && e.target.closest ? e.target.closest('.magent, .tilt') : null;
    if (!host) return;
    if (host !== target) {
      target = host;
    }
    cx = e.clientX;
    cy = e.clientY;
    if (rafId == null) {
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (!target) return;
        const rect = target.getBoundingClientRect();
        const px = (cx - rect.left) / rect.width;   // 0..1
        const py = (cy - rect.top) / rect.height;
        const isMagent = target.classList.contains('magent');
        if (isMagent) {
          // 平移：距离中心越远，位移越大（上限 6px），模拟"磁铁吸附"
          const dx = (px - 0.5) * 12;
          const dy = (py - 0.5) * 10;
          target.style.transform = `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0)`;
        } else {
          // 3D 倾斜：鼠标在哪一侧，气泡就向哪侧微微"抬起"
          const rx = (0.5 - py) * 6;   // -3..3deg
          const ry = (px - 0.5) * 6;   // -3..3deg
          target.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateY(-1px)`;
        }
      });
    }
  };
  const onLeave = (e) => {
    const host = e.target && e.target.closest ? e.target.closest('.magent, .tilt') : null;
    if (!host) return;
    host.style.transform = '';
    if (target === host) target = null;
  };
  window.addEventListener('mousemove', onMove, { passive: true });
  window.addEventListener('mouseout', onLeave, { passive: true });
  magentCleanup = () => {
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseout', onLeave);
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    target = null;
  };
};
const router = useRouter();
const currentUser = ref('');
const messages = ref([
 { type: 'system', content: '欢迎使用小爱，发送消息开始聊天' }
]);
watch(messages, () => {
 nextTick(() => {
 const container = chatContainer.value;
 if (container) {
 setTimeout(() => {
 container.scrollTop = container.scrollHeight;
 }, 30);
 }
 });
}, { deep: true });
const inputMessage = ref('');
const isLoading = ref(false);
const isLoadingMore = ref(false);
const hasMore = ref(true);
const pageNum = ref(1);
const pageSize = ref(20);
const chatContainer = ref(null);
const sessions = ref([]);
const currentSessionId = ref(null);
const sidebarOpen = ref(true);
const isRecording = ref(false);
const recordingTime = ref(0);
const mediaRecorder = ref(null);
const audioChunks = ref([]);
let recordingInterval = null;
const pendingMedia = ref(null);
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const pendingMedias = ref([]);
const showDeleteConfirm = ref(false);
const sessionToDelete = ref(null);
const expandedExtracted = reactive({});
const expandedSearch = reactive({});
const expandedSteps = reactive({});
// 工具调用结果折叠状态（key: "msgIdx-stepIdx"），默认折叠
const expandedTools = reactive({});
// 深度思考reasoning折叠状态（key: msgIdx），默认折叠
const expandedReasoning = reactive({});
// 统一「思考过程」面板折叠状态（key: msgIdx），合并工具调用 + 深度思考
const expandedThinking = reactive({});
const previewImage = ref(null);
// 模式切换：fast（快速模式）, expert（专家模式）
const currentMode = ref('fast');
const imageLoaded = () => {
 setTimeout(() => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 }, 50);
};
const ensureScrollToBottom = () => {
 const container = chatContainer.value;
 if (!container)
 return;
 const lastMessage = container.querySelector('.message:last-child');
 if (lastMessage) {
 const observer = new IntersectionObserver((entries) => {
 if (!entries[0].isIntersecting) {
 container.scrollTop = container.scrollHeight;
 }
 observer.disconnect();
 }, { root: container, threshold: 0.9 });
 observer.observe(lastMessage);
 }
};
onMounted(async () => {
 const token = localStorage.getItem('token');
 const username = localStorage.getItem('username');
 currentUser.value = username || '';
 if (!token) {
 router.push('/');
 return;
 }
 /* 绑定：磁性按钮 + 3D 气泡微倾斜（rAF 节流，单事件监听） */
 attachMagent();
 await loadSessions();
 if (sessions.value.length === 0) {
 await createNewSession();
 }
});

onBeforeUnmount(() => {
 /* 卸载时解绑磁性监听，避免路由切换后仍持有事件 */
 if (magentCleanup) magentCleanup();
});
const loadSessions = async () => {
 try {
 const token = localStorage.getItem('token');
 const data = await service.get('/sessions', {
 headers: { 'Authorization': token || '' }
 });
 if (data.code === 200) {
 sessions.value = data.data;
 }
 } catch (error) {
 console.error('加载会话失败:', error);
 }
};
const createNewSession = async () => {
 try {
 const token = localStorage.getItem('token');
 const data = await service.post('/session/new', {}, {
 headers: { 'Authorization': token || '' }
 });
 if (data.code === 200) {
 currentSessionId.value = data.data.sessionId;
 messages.value = [{ type: 'system', content: '欢迎使用小爱，发送消息开始聊天' }];
 await loadSessions();
 }
 } catch (error) {
 console.error('创建会话失败:', error);
 }
};
const scrollToBottom = () => {
 const doScroll = () => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 };
 nextTick(() => {
 doScroll();
 requestAnimationFrame(() => {
 doScroll();
 requestAnimationFrame(() => {
 doScroll();
 });
 });
 setTimeout(doScroll, 100);
 setTimeout(doScroll, 300);
 });
};
const loadMessages = async (page = 1) => {
 if (!currentSessionId.value || isLoadingMore.value)
 return;
 const container = chatContainer.value;
 const oldScrollHeight = container ? container.scrollHeight : 0;
 const oldScrollTop = container ? container.scrollTop : 0;
 isLoadingMore.value = true;
 try {
 const token = localStorage.getItem('token');
 const data = await service.get(`/session/messages/page?sessionId=${currentSessionId.value}&pageNum=${page}&pageSize=${pageSize.value}`, {
 headers: { 'Authorization': token || '' }
 });
 if (data.code === 200 && data.data) {
 const newMessages = data.data.messages || [];
 const formattedMessages = newMessages.map(msg => {
  const formatted = {
    type: msg.role === 'user' ? 'user' : 'bot',
    content: msg.content,
    messageType: msg.messageType || 'TEXT',
    mediaUrl: msg.mediaUrl,
    mediaUrls: msg.mediaUrls,
    fileNames: msg.fileNames,
    extractedText: msg.extractedText,
    searchResults: msg.searchResults,
    thinking: '',
    isThinking: false,
    searchStatus: null,
    thinkingSteps: [],
    thinkingStartTime: null,
    thinkingEndTime: null,
    deepThinkingReasoning: '',
    expandedDeepReasoning: false,
  };
  // 专家模式历史消息：从 expertTrace 解析出 thinkingSteps + deepThinkingReasoning
  if (msg.role === 'assistant' && msg.expertTrace) {
    try {
      const trace = typeof msg.expertTrace === 'string' ? JSON.parse(msg.expertTrace) : msg.expertTrace;
      if (trace && trace.history && Array.isArray(trace.history)) {
        formatted.thinkingSteps = trace.history.map((rec, idx) => ({
          id: idx + 1,
          phase: rec.action === 'collect_tools' ? 'planning' : 'thinking',
          iteration: rec.iteration || (idx + 1),
          analysis: rec.analysis || '',
          purpose: rec.purpose || null,
          action: rec.action || null,
          tools: (rec.tools || []).map(t => ({
            tool: t.tool,
            status: t.success ? 'done' : 'error',
            summary: `${t.tool}${t.resultCount ? ` · ${t.resultCount} 条结果` : ''}`,
            durationMs: t.durationMs || 0,
            resultCount: t.resultCount || 0,
            error: t.error || null,
            // 持久化的原始结果（折叠栏展开后显示）
            rawResult: t.rawResult || null,
          })),
          thinking: '',
          status: 'done',
        }));
      }
      // 深度思考推理链全文（从 expertTrace 加载）
      if (trace && trace.deepThinkingReasoning) {
        formatted.deepThinkingReasoning = trace.deepThinkingReasoning;
      }
    } catch (e) {
      console.warn('解析 expertTrace 失败：', e);
    }
  }
  return formatted;
});
 if (page === 1) {
 messages.value = [...formattedMessages.reverse()];
 }
 else {
 messages.value = [...formattedMessages.reverse(), ...messages.value];
 }
 hasMore.value = data.data.hasNext || false;
 pageNum.value = page;
 }
 }
 catch (error) {
 console.error('加载消息失败:', error);
 }
 finally {
 isLoadingMore.value = false;
 if (page === 1) {
 scrollToBottom();
 }
 else if (page > 1 && container) {
 nextTick(() => {
 container.scrollTop = (container.scrollHeight - oldScrollHeight) + oldScrollTop;
 });
 }
 }
};
const selectSession = async (session) => {
 currentSessionId.value = session.id;
 pageNum.value = 1;
 hasMore.value = true;
 await loadMessages(1);
 nextTick(() => {
 ensureScrollToBottom();
 setTimeout(() => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 }, 50);
 setTimeout(() => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 }, 150);
 setTimeout(() => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 }, 300);
 setTimeout(() => {
 const container = chatContainer.value;
 if (container) {
 container.scrollTop = container.scrollHeight;
 }
 }, 500);
 });
};
const handleScroll = async () => {
 const container = chatContainer.value;
 if (!container || isLoadingMore.value)
 return;
 if (container.scrollTop < 50 && hasMore.value) {
 await loadMessages(pageNum.value + 1);
 }
};
const handleLogout = () => {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
};
const confirmDeleteSession = (session) => {
 sessionToDelete.value = session;
 showDeleteConfirm.value = true;
};
const cancelDeleteSession = () => {
 showDeleteConfirm.value = false;
 sessionToDelete.value = null;
};
const deleteSession = async () => {
 if (!sessionToDelete.value)
 return;
 const sessionId = sessionToDelete.value.id;
 try {
 const token = localStorage.getItem('token');
 const data = await service.delete(`/session/delete/${sessionId}`, {
 headers: { 'Authorization': token || '' }
 });
 if (data.code === 200) {
 showDeleteConfirm.value = false;
 sessionToDelete.value = null;
 await loadSessions();
 if (currentSessionId.value === sessionId) {
 if (sessions.value.length > 0) {
 await selectSession(sessions.value[0]);
 }
 else {
 await createNewSession();
 }
 }
 }
 else {
 alert(data.message || '删除失败');
 }
 }
 catch (error) {
 console.error('删除会话失败:', error);
 alert('删除会话失败');
 showDeleteConfirm.value = false;
 sessionToDelete.value = null;
 }
};
const toggleExtracted = (index) => {
  if (expandedExtracted[index]) {
    delete expandedExtracted[index];
  }
  else {
    expandedExtracted[index] = true;
  }
};
const toggleSearch = (index) => {
  if (expandedSearch[index]) {
    delete expandedSearch[index];
  }
  else {
    expandedSearch[index] = true;
  }
};
const toggleThinkingSteps = (index) => {
  if (expandedSteps[index]) {
    delete expandedSteps[index];
  } else {
    expandedSteps[index] = true;
  }
};
// 切换工具调用结果折叠状态（每个工具独立折叠，三级key: msgIdx-stepIdx-toolIdx）
const toggleTools = (msgIdx, stepIdx, toolIdx) => {
  const key = `${msgIdx}-${stepIdx}-${toolIdx}`;
  if (expandedTools[key]) {
    delete expandedTools[key];
  } else {
    expandedTools[key] = true;
  }
};
// 切换深度思考reasoning折叠状态
const toggleReasoning = (index) => {
  if (expandedReasoning[index]) {
    delete expandedReasoning[index];
  } else {
    expandedReasoning[index] = true;
  }
};
// 切换统一「思考过程」面板（合并工具调用 + 深度思考）
const toggleThinking = (index) => {
  if (expandedThinking[index]) {
    delete expandedThinking[index];
  } else {
    expandedThinking[index] = true;
  }
};
const getSearchResults = (searchResultsStr) => {
  if (!searchResultsStr) {
    return [];
  }
  try {
    const results = JSON.parse(searchResultsStr);
    if (Array.isArray(results)) {
      return results;
    }
  } catch (e) {
    console.error('解析搜索结果失败:', e);
  }
  return [];
};
const openImagePreview = (url) => {
 previewImage.value = url;
};
const closeImagePreview = () => {
 previewImage.value = null;
};
const sendMessage = async () => {
  const hasPending = pendingMedias.value.length > 0;
  const textContent = inputMessage.value.trim();
  if (!textContent && !hasPending)
    return;
  if (isLoading.value)
    return;
  const finalMessageType = hasPending ? pendingMedias.value[0].type : 'TEXT';
  const finalMediaUrls = hasPending ? pendingMedias.value.map(m => m.url) : null;
  const finalFileNames = hasPending ? pendingMedias.value.map(m => m.name) : null;
  const displayContent = hasPending
    ? (textContent ? textContent : '')
    : textContent;
  const capturedType = finalMessageType;
  const capturedUrls = finalMediaUrls;
  const capturedText = textContent;
  inputMessage.value = '';
  const mediasToSend = [...pendingMedias.value];
  pendingMedias.value = [];
  messages.value.push({
    type: 'user',
    content: displayContent,
    messageType: capturedType,
    mediaUrls: capturedUrls,
    mediaUrl: capturedUrls ? capturedUrls[0] : null,
    fileNames: finalFileNames
  });
  const botMessageIndex = messages.value.push({
    type: 'bot', content: '', searchResults: null, thinking: '', isThinking: false,
    searchStatus: null, thinkingSteps: [], thinkingStartTime: Date.now(),
    // 思考结束固定时间戳（流结束时写入，用于显示固定总耗时）
    thinkingEndTime: null,
    // 深度思考推理链全文（独立于步骤列表，单独折叠显示）
    deepThinkingReasoning: '',
    // 面板内部深度思考步骤的二级折叠状态（默认 false = 折叠）
    expandedDeepReasoning: false
  }) - 1;
  isLoading.value = true;
  scrollToBottom();
  try {
    const token = localStorage.getItem('token');
    const requestBody = {
      message: hasPending ? (capturedText || finalFileNames.join(', ')) : capturedText,
      messageType: capturedType,
      sessionId: currentSessionId.value,
      mode: currentMode.value  // 添加模式参数
    };
    if (capturedUrls && capturedUrls.length > 0) {
      if (capturedUrls.length === 1) {
        requestBody.mediaUrl = capturedUrls[0];
      } else {
        requestBody.mediaUrls = capturedUrls;
      }
    }
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': token || ''
      },
      body: JSON.stringify(requestBody)
    });
 if (response.status === 401) {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
 return;
 }
 if (!response.ok)
 throw new Error('请求失败');
 const sessionIdHeader = response.headers.get('X-Session-Id');
 if (sessionIdHeader && !currentSessionId.value) {
 currentSessionId.value = sessionIdHeader;
 await loadSessions();
 }
 const reader = response.body.getReader();
 const decoder = new TextDecoder();
 let lineBuffer = '';
 // 【日志降噪 & 流式证据】统一一条 SSE DONE 汇总：收到多少 JSON 行、正文/搜索/思考各多少块、最终内容长度
 // 避免后续有人逐块 console.log 刷屏，同时给 F12 里一个"到底有没有收到字"的明确证据
 const sseStats = { lines: 0, jsonLines: 0, contentPieces: 0, thinkingPieces: 0, searchPieces: 0 };
 const botMsg = () => messages.value[botMessageIndex];
 // 把"单行解析 + 赋值"抽成一个函数，消除 line loop 与 remaining 分支两处重复（之前两处各写一遍易改漏）
 const applyChunkLine = (line) => {
   if (!line) return;
   sseStats.lines += 1;
   if (line.startsWith('{')) {
     try {
       const jsonChunk = JSON.parse(line);
       sseStats.jsonLines += 1;
       const type = jsonChunk.type;
       const data = jsonChunk.data;
       if (type === 'content') {
        // 正式回复内容：保留 isThinking 状态（思考栏 spinner 会保持动画直到流结束）
        botMsg().content += (data || '');
        sseStats.contentPieces += 1;
       } else if (type === 'orchestration_chunk') {
        // 编排器分析增量文本（流式打字机效果）：
        // 如果当前没有步骤（或最后一步已完成），创建新的占位步骤
        const steps = botMsg().thinkingSteps;
        if (steps.length === 0 || steps[steps.length - 1].status === 'done') {
          steps.push({
            id: steps.length + 1,
            phase: 'planning',
            iteration: steps.length + 1,
            analysis: data?.delta || '',
            purpose: null,
            action: null,
            tools: [],
            thinking: '',
            status: 'running',
          });
        } else {
          // 追加到当前正在进行的步骤
          steps[steps.length - 1].analysis += (data?.delta || '');
        }
        sseStats.searchPieces += 1;
       } else if (type === 'orchestration_step') {
        // 编排步骤完成：更新当前步骤的结构化信息（analysis 已通过 chunk 流式显示）
        const steps = botMsg().thinkingSteps;
        if (steps.length > 0) {
          const lastStep = steps[steps.length - 1];
          // 更新结构化字段（analysis 不覆盖，保留已流式显示的文本）
          lastStep.phase = data?.phase || lastStep.phase;
          lastStep.action = data?.action || lastStep.action;
          lastStep.purpose = data?.purpose || lastStep.purpose;
          lastStep.iteration = data?.iteration || lastStep.iteration;
          // 如果 chunk 没有产生过 analysis（fallback），用 step 里的 analysis 补上
          if (!lastStep.analysis && data?.analysis) {
            lastStep.analysis = data.analysis;
          }
        } else {
          // fallback：没有收到过 chunk，直接创建步骤
          steps.push({
            id: data?.iteration || 1,
            phase: data?.phase || 'planning',
            iteration: data?.iteration || 1,
            analysis: data?.analysis || '',
            purpose: data?.purpose || null,
            action: data?.action || null,
            tools: [],
            thinking: '',
            status: 'running',
          });
        }
        sseStats.searchPieces += 1;
       } else if (type === 'tool_call_start') {
        // 工具调用开始：在当前步骤 push 一个 running 状态的占位工具
        const steps = botMsg().thinkingSteps;
        // fallback：如果编排器事件未创建步骤，此处补创建一个
        if (steps.length === 0 || steps[steps.length - 1].status === 'done') {
          steps.push({
            id: steps.length + 1,
            phase: 'executing',
            iteration: steps.length + 1,
            analysis: '',
            purpose: null,
            action: null,
            tools: [],
            thinking: '',
            status: 'running',
          });
        }
        const currentStep = steps[steps.length - 1];
        currentStep.tools.push({
          tool: data?.tool || 'unknown',
          status: 'running',
          summary: '',
          durationMs: null,
          resultCount: null,
          params: data?.params || null,
        });
     } else if (type === 'tool_call_result') {
        // 工具调用完成：更新当前步骤中对应工具的状态和结果
        const steps = botMsg().thinkingSteps;
        // fallback：如果步骤不存在，补创建一个
        if (steps.length === 0) {
          steps.push({
            id: 1,
            phase: 'executing',
            iteration: 1,
            analysis: '',
            purpose: null,
            action: null,
            tools: [],
            thinking: '',
            status: 'running',
          });
        }
        const currentStep = steps[steps.length - 1];
        // 找到同步骤中对应的 running 工具并更新
        let tool = currentStep.tools.find(t => t.tool === data?.tool && t.status === 'running');
        if (!tool) {
          // 容错：直接 push 一个完成的
          tool = {
            tool: data?.tool || 'unknown',
            status: 'done',
            summary: data?.summary || '',
            durationMs: data?.durationMs || 0,
            resultCount: data?.resultCount || 0,
            results: data?.results || null,
          };
          currentStep.tools.push(tool);
        } else {
          tool.status = data?.success === false ? 'error' : 'done';
          tool.summary = data?.summary || '';
          tool.durationMs = data?.durationMs || 0;
          tool.resultCount = data?.resultCount || 0;
          tool.error = data?.error || null;
          // 保存搜索结果（[{title,url}]），用于折叠栏内渲染超链接
          tool.results = data?.results || null;
        }
        // 工具全部完成后标记步骤为 done
        if (currentStep.tools.length > 0 && currentStep.tools.every(t => t.status !== 'running')) {
          currentStep.status = 'done';
        }
        sseStats.searchPieces += 1;
       } else if (type === 'search_results') {
        // 兼容旧协议：search_results 仍然更新 searchResults 字段（用于搜索链接列表渲染）
        // 但优先使用 tool_call_result 中的数据（thinkingSteps），此字段仅作 fallback
        botMsg().searchResults = JSON.stringify(data);
        sseStats.searchPieces += 1;
       } else if (type === 'search_start') {
        // 兼容旧协议（快速模式旧版）：保留 searchStatus 字段用于渲染
        botMsg().searchStatus = {
          status: 'searching',
          keywords: data?.keywords || []
        };
        botMsg().isThinking = false;
        botMsg().thinking = '';
       } else if (type === 'search_summary') {
        // 兼容旧协议
        botMsg().searchStatus = {
          status: 'completed',
          keywords: data?.keywords || [],
          count: data?.count || 0,
          duration: data?.duration || 0
        };
        if (data?.results) {
          botMsg().searchResults = JSON.stringify(data.results);
        }
        sseStats.searchPieces += 1;
       } else if (type === 'thinking_start') {
        // 深度思考开始：标记思考状态，reasoning 将写入独立字段
        botMsg().isThinking = true;
        botMsg().deepThinkingReasoning = '';
        if (botMsg().searchStatus?.status === 'searching') {
          botMsg().searchStatus = null;
        }
       } else if (type === 'thinking') {
        // 深度思考推理链（流式）：累加到消息级独立字段，不再写入步骤
        botMsg().isThinking = true;
        botMsg().deepThinkingReasoning += (data || '');
        sseStats.thinkingPieces += 1;
      } else if (type === 'thinking_error') {
        // 思考错误
        botMsg().isThinking = false;
        botMsg().deepThinkingReasoning += `\n[思考错误] ${data?.error || '未知错误'}`;
       }
       return;
     } catch (e) {
       // JSON 解析失败兜底按纯文本写入（非空行，不再打印解析失败原因到 console，避免刷屏）
       botMsg().content += line;
       return;
     }
   }
   // 非 JSON 纯文本行（一般是旧模型的"错误: xxx"这类降级响应）
   botMsg().content += line;
 };
 try {
 while (true) {
 const { done, value } = await reader.read();
 if (done) break;
 lineBuffer += decoder.decode(value, { stream: true });
 let newlineIdx;
 while ((newlineIdx = lineBuffer.indexOf('\n')) >= 0) {
   const line = lineBuffer.substring(0, newlineIdx).trim();
   lineBuffer = lineBuffer.substring(newlineIdx + 1);
   applyChunkLine(line);
   scrollToBottom();
 }
 }
 // 最后残留无换行的半行（也走同一个 apply，避免重复 if-else）
 const remaining = lineBuffer.trim();
 if (remaining) applyChunkLine(remaining);
 } finally {
 reader.releaseLock();
 // 流结束：统一清除 isThinking spinner（之前 content 到来不清，避免思考栏过早隐藏）
 // 注意：thinking 文本保留，思考栏仍会显示，只是停止转圈动画
 if (botMsg()) {
   botMsg().isThinking = false;
   // 流结束：固定思考总耗时（避免每次渲染 Date.now() 变化导致耗时持续增加）
   if (!botMsg().thinkingEndTime) {
     botMsg().thinkingEndTime = Date.now();
   }
 }
 // 【STREAM DONE 诊断】统一一条 F12 可见证据：后端日志 [SSE完成] + 前端 sseStats 能对得上
 console.debug('[STREAM DONE]', {
   lines: sseStats.lines,
   jsonLines: sseStats.jsonLines,
   contentPieces: sseStats.contentPieces,
   thinkingPieces: sseStats.thinkingPieces,
   searchPieces: sseStats.searchPieces,
   contentLen: (botMsg()?.content || '').length,
   thinkingLen: (botMsg()?.thinking || '').length,
   isThinking: botMsg()?.isThinking,
   searchLen: (botMsg()?.searchResults || '').length,
 });
 }
 }
 catch (error) {
 messages.value[botMessageIndex].content = `请求失败: ${error.message}`;
 }
 finally {
 isLoading.value = false;
 }
};
const uploadFiles = async (type, files) => {
  if (isLoading.value)
    return;
  const maxSize = type === 'image' ? MAX_IMAGE_SIZE : MAX_FILE_SIZE;
  const validFiles = [];
  for (const file of files) {
    if (file.size > maxSize) {
      alert(`${type === 'image' ? '图片' : '文件'}大小超过限制（最大${type === 'image' ? '10MB' : '50MB'}）`);
      return;
    }
    validFiles.push(file);
  }
  if (validFiles.length === 0)
    return;
  try {
    const token = localStorage.getItem('token');
    const formData = new FormData();
    for (const file of validFiles) {
      formData.append('files', file);
    }
    const data = await service.post(`/upload/${type}s`, formData, {
      headers: { 'Authorization': token || '' }
    });
    if (data.code === 200) {
      const urls = data.data;
      for (let i = 0; i < urls.length && i < validFiles.length; i++) {
        pendingMedias.value.push({
          type: type === 'image' ? 'IMAGE' : 'FILE',
          url: urls[i],
          name: validFiles[i].name
        });
      }
    }
    else {
      alert(data.message || '上传失败');
    }
  }
  catch (error) {
    console.error('上传失败:', error);
    alert('上传失败');
  }
};
const removePendingMedia = async (index) => {
 const media = pendingMedias.value[index];
 if (media && media.url) {
 try {
 const token = localStorage.getItem('token');
 await service.delete('/upload/delete', {
 headers: { 'Authorization': token || '' },
 data: { url: media.url }
 });
 } catch (error) {
 console.error('删除待上传文件失败:', error);
 }
 }
 pendingMedias.value.splice(index, 1);
};
const clearAllPendingMedias = async () => {
 for (const media of pendingMedias.value) {
 if (media && media.url) {
 try {
 const token = localStorage.getItem('token');
 await service.delete('/upload/delete', {
 headers: { 'Authorization': token || '' },
 data: { url: media.url }
 });
 } catch (error) {
 console.error('删除待上传文件失败:', error);
 }
 }
 }
 pendingMedias.value = [];
};
const handleImageUpload = (event) => {
 const files = Array.from(event.target.files);
 if (files.length > 0)
 uploadFiles('image', files);
 event.target.value = '';
};
const handleFileUpload = (event) => {
 const files = Array.from(event.target.files);
 if (files.length > 0)
 uploadFiles('file', files);
 event.target.value = '';
};
const startRecording = async () => {
 try {
 const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
 mediaRecorder.value = new MediaRecorder(stream, { mimeType: 'audio/webm' });
 audioChunks.value = [];
 mediaRecorder.value.ondataavailable = (event) => {
 audioChunks.value.push(event.data);
 };
 mediaRecorder.value.onstop = async () => {
 const webmBlob = new Blob(audioChunks.value, { type: 'audio/webm' });
 const wavBlob = await convertWebmToWav(webmBlob);
 await processAudio(wavBlob);
 };
 mediaRecorder.value.start();
 isRecording.value = true;
 recordingTime.value = 0;
 recordingInterval = setInterval(() => { recordingTime.value++; }, 1000);
 }
 catch (error) {
 console.error('录音失败:', error);
 alert('无法访问麦克风，请检查权限');
 }
};
const stopRecording = () => {
 if (mediaRecorder.value && isRecording.value) {
 mediaRecorder.value.stop();
 isRecording.value = false;
 if (recordingInterval) {
 clearInterval(recordingInterval);
 recordingInterval = null;
 }
 mediaRecorder.value.stream.getTracks().forEach(track => track.stop());
 }
};
const convertWebmToWav = async (webmBlob) => {
 return new Promise((resolve, reject) => {
 const audioContext = new (window.AudioContext || window.webkitAudioContext)();
 const fileReader = new FileReader();
 fileReader.onload = async (e) => {
 try {
 const arrayBuffer = e.target.result;
 const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
 const wavBlob = audioBufferToWav(audioBuffer);
 resolve(wavBlob);
 }
 catch (error) {
 reject(error);
 }
 finally {
 audioContext.close();
 }
 };
 fileReader.onerror = reject;
 fileReader.readAsArrayBuffer(webmBlob);
 });
};
const audioBufferToWav = (audioBuffer) => {
 const targetSampleRate = 16000;
 const numberOfChannels = audioBuffer.numberOfChannels;
 const sourceSampleRate = audioBuffer.sampleRate;
 let data;
 if (numberOfChannels > 1) {
 const channels = [];
 for (let i = 0; i < numberOfChannels; i++) {
 channels.push(audioBuffer.getChannelData(i));
 }
 data = new Float32Array(audioBuffer.length);
 for (let i = 0; i < audioBuffer.length; i++) {
 let sum = 0;
 for (let j = 0; j < numberOfChannels; j++) {
 sum += channels[j][i];
 }
 data[i] = sum / numberOfChannels;
 }
 }
 else {
 data = audioBuffer.getChannelData(0);
 }
 let resampledData;
 if (sourceSampleRate !== targetSampleRate) {
 const ratio = targetSampleRate / sourceSampleRate;
 const newLength = Math.floor(data.length * ratio);
 resampledData = new Float32Array(newLength);
 for (let i = 0; i < newLength; i++) {
 const sourceIndex = i / ratio;
 const floorIndex = Math.floor(sourceIndex);
 const ceilIndex = Math.min(floorIndex + 1, data.length - 1);
 const fraction = sourceIndex - floorIndex;
 resampledData[i] = data[floorIndex] * (1 - fraction) + data[ceilIndex] * fraction;
 }
 }
 else {
 resampledData = data;
 }
 const length = resampledData.length * 2 + 44;
 const buffer = new ArrayBuffer(length);
 const view = new DataView(buffer);
 let pos = 0;
 const setUint32 = (value) => { view.setUint32(pos, value, true); pos += 4; };
 const setUint16 = (value) => { view.setUint16(pos, value, true); pos += 2; };
 setUint32(0x46464952);
 setUint32(length - 8);
 setUint32(0x45564157);
 pos += 4;
 setUint16(1);
 setUint16(1);
 setUint32(targetSampleRate);
 setUint32(targetSampleRate * 2);
 setUint16(2);
 setUint16(16);
 pos += 2;
 setUint32(0x61746164);
 setUint32(length - pos - 4);
 for (let i = 0; i < resampledData.length; i++) {
 const sample = Math.max(-1, Math.min(1, resampledData[i]));
 const intSample = sample < 0 ? sample * 32768 : sample * 32767;
 view.setInt16(pos, intSample, true);
 pos += 2;
 }
 return new Blob([buffer], { type: 'audio/wav' });
};
const processAudio = async (audioBlob) => {
 try {
 const token = localStorage.getItem('token');
 const formData = new FormData();
 formData.append('audio', audioBlob, 'recording.wav');
 const data = await service.post('/speech-to-text', formData, {
 headers: { 'Authorization': token || '' }
 });
 if (data.code === 200 && data.data) {
 inputMessage.value += (inputMessage.value.trim() ? ' ' : '') + data.data;
 nextTick(() => {
 const inputEl = document.querySelector('.input-field');
 if (inputEl)
 inputEl.focus();
 });
 }
 else {
 alert(data.message || '语音转文本失败');
 }
 }
 catch (error) {
 console.error('语音转文本失败:', error);
 alert('语音转文本失败');
 }
};
</script>

<template>
  <div class="chat-layout">
    <header class="chat-header">
      <div class="header-left">
        <!-- 折叠按钮：轻量涟漪 + 磁性 -->
        <button class="sidebar-toggle magent" data-ripple="true" @click="sidebarOpen = !sidebarOpen">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
        <span class="logo" aria-hidden="true">
          <!-- Logo 换成哥特字体 A 徽章 + 朱砂瞳孔小点，与登录页呼应 -->
          <span class="logo__glyph">𝔄</span>
          <span class="logo__pupil"></span>
        </span>
        <span class="title">小爱</span>
      </div>
      <div class="header-right">
          <div class="mode-selector">
            <button
              :class="['mode-btn', 'magent', { active: currentMode === 'fast' }]"
              data-ripple="true"
              @click="currentMode = 'fast'"
              title="快速模式：直接响应，速度快"
            >
              <span class="mode-btn__icon">⚡</span>
              <span>快速模式</span>
            </button>
            <button
              :class="['mode-btn', 'magent', { active: currentMode === 'expert' }]"
              data-ripple="true"
              @click="currentMode = 'expert'"
              title="专家模式：深度分析，支持联网搜索和图片分析"
            >
              <span class="mode-btn__icon">🔬</span>
              <span>专家模式</span>
            </button>
          </div>
          <!-- 插件市场入口：跳转 /market 浏览/安装 MCP 插件 -->
          <button class="market-btn magent" data-ripple="true" @click="router.push('/market')" title="插件市场：浏览并安装 MCP 插件">
            <span class="market-btn__icon">📦</span>
            <span>插件市场</span>
          </button>
          <span class="username">{{ currentUser }}</span>
          <button class="logout-btn magent" data-ripple="true" @click="handleLogout">退出登录</button>
        </div>
    </header>

    <div class="chat-body">
      <aside class="sidebar" :class="{ 'closed': !sidebarOpen }">
        <div class="sidebar-header">
          <button class="new-session-btn magent" data-ripple="true" @click="createNewSession">+ 新建会话</button>
        </div>
        <div class="session-list">
          <div
            v-for="session in sessions"
            :key="session.id"
            :class="['session-item', 'tilt', { active: currentSessionId === session.id }]"
            @click="selectSession(session)"
          >
            <!-- 用 SVG 替代 emoji：更精致的「对话卷轴」图标 -->
            <svg class="session-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <span class="session-title">{{ session.title || session.id }}</span>
            <button class="session-delete magent" data-ripple="true" @click.stop="confirmDeleteSession(session)" title="删除会话">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                <line x1="10" y1="11" x2="10" y2="17"/>
                <line x1="14" y1="11" x2="14" y2="17"/>
              </svg>
            </button>
          </div>
        </div>
      </aside>

      <div class="chat-content">
        <div v-if="isLoadingMore && messages.length > 1" class="loading-more">加载中...</div>
        <div class="chat-messages" ref="chatContainer" @scroll="handleScroll">
          <div v-for="(msg, index) in messages" :key="index"
               :class="['message', msg.type, { 'msg-streaming': msg.type === 'bot' && index === messages.length - 1 && isLoading }]">
            <div class="message-bubble tilt" :data-role="msg.type">
              <div v-if="msg.type === 'system'" class="system-message">
                {{ msg.content }}
              </div>
              
              <template v-else-if="msg.type === 'user'">
                <div v-if="msg.messageType === 'IMAGE' && (msg.mediaUrls || msg.mediaUrl)" class="media-section">
                  <div class="media-grid">
                    <div v-for="(url, idx) in (msg.mediaUrls || [msg.mediaUrl])" :key="idx" class="image-wrapper" @click="openImagePreview(url)">
                      <img :src="url" alt="图片" class="message-image" @load="imageLoaded" />
                      <div class="image-overlay">
                        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="white" stroke-width="2">
                          <circle cx="12" cy="12" r="3"/>
                          <path d="M15 12l3.09-3.09a1.5 1.5 0 0 1 2.12 2.12L12 15"/>
                          <path d="M9 12l-3.09 3.09a1.5 1.5 0 0 1-2.12-2.12L12 9"/>
                        </svg>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="msg.messageType === 'FILE' && (msg.mediaUrls || msg.mediaUrl)" class="media-section">
                  <div class="media-list">
                    <a v-for="(url, idx) in (msg.mediaUrls || [msg.mediaUrl])" :key="idx" :href="url" target="_blank" class="file-card">
                      <div class="file-icon">📄</div>
                      <div class="file-info">
                        <span class="file-name">{{ (msg.fileNames && msg.fileNames[idx]) || msg.fileName || msg.content }}</span>
                      </div>
                    </a>
                  </div>
                </div>
                <span v-if="msg.content" class="message-text">{{ msg.content }}</span>
                <div v-if="msg.extractedText" class="extracted-container">
                  <button class="extracted-toggle" @click="toggleExtracted(index)">
                    <svg v-if="!expandedExtracted[index]" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="12 5 12 19"/>
                      <polyline points="5 12 19 12"/>
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    <span>{{ expandedExtracted[index] ? '收起提取内容' : '查看提取内容' }}</span>
                  </button>
                  <div v-if="expandedExtracted[index]" class="extracted-content-box">
                    <span class="extracted-label">【提取内容】</span>
                    <span class="extracted-text">{{ msg.extractedText }}</span>
                  </div>
                </div>
              </template>

              <template v-else>
                <!-- 搜索状态和思考过程互斥显示 -->
                <!-- 正在搜索时显示搜索状态 -->
                <div v-if="msg.searchStatus?.status === 'searching'" class="search-status">
                  <div class="search-status-searching">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" class="search-spinner">
                      <circle cx="11" cy="11" r="8"/>
                      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                    <span>正在搜索：{{ msg.searchStatus.keywords?.join(' ') }}</span>
                  </div>
                </div>
                
                <!-- 思考过程：合并「工具调用」+「深度思考」，统一折叠面板（默认折叠） -->
                <div v-if="(msg.thinkingSteps && msg.thinkingSteps.length > 0) || (msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0)"
                     :class="['collapsible-panel', 'thinking-panel']">
                  <div class="collapsible-header" @click="toggleThinking(index)">
                    <!-- 哥特齿轮+灯泡+朱砂血滴的思考徽章（AI 生成装饰图） -->
                    <img src="/assets/thinking-emblem.jpg" class="thinking-emblem" :class="{ 'thinking-spinner': msg.isThinking }" alt="" />
                    <span class="collapsible-title">
                      {{ msg.isThinking ? '思考中...' : '思考过程' }}
                      <template v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0">
                        · 工具调用 {{ msg.thinkingSteps.length }} 步
                      </template>
                      <template v-if="msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0 && msg.thinkingSteps && msg.thinkingSteps.length > 0">
                        + 深度思考
                      </template>
                      <template v-else-if="msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0">
                        · 深度思考
                      </template>
                      <!-- 耗时：优先用流结束时固定的 endTime，流进行中则实时显示 -->
                      <template v-if="msg.thinkingStartTime">
                        · 耗时 {{ (((msg.thinkingEndTime || Date.now()) - msg.thinkingStartTime) / 1000).toFixed(1) }}s
                      </template>
                    </span>
                    <svg :class="['collapsible-chevron', { 'collapsed': !expandedThinking[index] }]" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="9 18 15 12 9 6"/>
                    </svg>
                  </div>
                  <div v-if="expandedThinking[index]" class="collapsible-body">
                    <!-- ① 工具调用步骤列表 -->
                    <template v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0">
                      <div v-for="(step, stepIdx) in msg.thinkingSteps" :key="stepIdx" class="thinking-step">
                        <!-- 步骤编号和分析文本 -->
                        <div class="thinking-step-header">
                          <span class="thinking-step-num">{{ stepIdx + 1 }}</span>
                          <div class="thinking-step-content">
                            <div class="thinking-step-analysis">{{ step.analysis }}</div>
                            <div v-if="step.purpose" class="thinking-step-purpose">目的：{{ step.purpose }}</div>
                          </div>
                        </div>
                        <!-- 工具调用摘要 + 搜索结果（每步可多个工具，每个工具是小折叠栏） -->
                        <div v-if="step.tools && step.tools.length > 0" class="thinking-step-tools">
                          <div v-for="(tool, toolIdx) in step.tools" :key="toolIdx" class="tool-collapsible">
                            <!-- 小折叠栏头部：工具摘要（可点击展开/收起搜索结果） -->
                            <div class="tool-summary" :class="{ 'tool-running': tool.status === 'running', 'tool-error': tool.status === 'error' }"
                                 :style="{ cursor: (tool.results || tool.rawResult) ? 'pointer' : 'default' }"
                                 @click="(tool.results || tool.rawResult) && toggleTools(index, stepIdx, toolIdx)">
                              <template v-if="tool.tool === 'web_search'">
                                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                                </svg>
                                <span>
                                  <template v-if="tool.status === 'running'">正在搜索...</template>
                                  <template v-else>{{ tool.summary || `已搜索 ${tool.resultCount} 个网页` }}</template>
                                  <template v-if="tool.durationMs"> · {{ (tool.durationMs / 1000).toFixed(1) }}s</template>
                                </span>
                              </template>
                              <template v-else-if="tool.tool === 'memory_search'">
                                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
                                </svg>
                                <span>
                                  <template v-if="tool.status === 'running'">正在检索记忆...</template>
                                  <template v-else>{{ tool.summary || `已读取 ${tool.resultCount} 个记忆片段` }}</template>
                                  <template v-if="tool.durationMs"> · {{ (tool.durationMs / 1000).toFixed(1) }}s</template>
                                </span>
                              </template>
                              <template v-else>
                                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                                  <rect x="3" y="3" width="18" height="18" rx="2"/>
                                </svg>
                                <span>
                                  {{ tool.summary || tool.tool }}
                                  <template v-if="tool.durationMs"> · {{ (tool.durationMs / 1000).toFixed(1) }}s</template>
                                </span>
                              </template>
                              <!-- 有搜索结果时显示展开/收起箭头 -->
                              <svg v-if="(tool.results || tool.rawResult) && (tool.results || tool.rawResult).length > 0"
                                   :class="['tool-chevron', { 'collapsed': !expandedTools[`${index}-${stepIdx}-${toolIdx}`] }]"
                                   viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="9 18 15 12 9 6"/>
                              </svg>
                            </div>
                            <!-- 搜索结果超链接列表（小折叠栏内容，默认折叠） -->
                            <div v-if="(tool.results || tool.rawResult) && (tool.results || tool.rawResult).length > 0 && expandedTools[`${index}-${stepIdx}-${toolIdx}`]"
                                 class="search-links-list">
                              <a v-for="(result, rIdx) in (tool.results || tool.rawResult)" :key="rIdx"
                                 :href="result.url" target="_blank" rel="noopener noreferrer"
                                 class="search-link-item">
                                <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2">
                                  <path d="M7 17l9.2-9.2M8.7 7.4h7.9v7.9"/>
                                </svg>
                                <span>{{ result.title || result.url }}</span>
                              </a>
                            </div>
                          </div>
                        </div>
                      </div>
                      <!-- 工具/思考之间的分隔线（只有两者都存在时才显示） -->
                      <div v-if="msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0" class="thinking-divider"></div>
                    </template>
                    <!-- ② 深度思考推理链：作为最后一步，渲染方式与工具调用步骤一致（卡片 + renderMarkdown） -->
                    <template v-if="msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0">
                      <div class="thinking-step thinking-step-deep">
                        <!-- 卡片头部（可点击展开/收起深度思考正文） -->
                        <div class="thinking-step-header" style="cursor: pointer"
                             @click="msg.expandedDeepReasoning = !msg.expandedDeepReasoning">
                          <!-- 步骤编号：用琥珀金渐变填充，和工具步骤的冷蓝编号区分 -->
                          <span class="thinking-step-num step-num-deep">
                            {{ (msg.thinkingSteps && msg.thinkingSteps.length > 0) ? msg.thinkingSteps.length + 1 : 1 }}
                          </span>
                          <div class="thinking-step-content">
                            <div class="thinking-step-title">
                              深度思考推理
                              <span class="step-status">
                                <template v-if="msg.isThinking">思考中...</template>
                                <template v-else-if="msg.expandedDeepReasoning">收起</template>
                                <template v-else>展开</template>
                              </span>
                            </div>
                          </div>
                          <!-- 小折叠箭头 -->
                          <svg :class="['step-chevron', { 'collapsed': !msg.expandedDeepReasoning }]"
                               viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="9 18 15 12 9 6"/>
                          </svg>
                        </div>
                        <!-- 正文：默认折叠（v-if 控制），展开后用 renderMarkdown 渲染 -->
                        <div v-if="msg.expandedDeepReasoning" class="thinking-step-body">
                          <div class="thinking-step-analysis" v-html="renderMarkdown(msg.deepThinkingReasoning)"></div>
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
                
                <!-- 正式回复内容 -->
                <span v-if="msg.content" class="message-text" v-html="renderMarkdown(msg.content)"></span>
              </template>
            </div>
          </div>
        </div>

        <div class="chat-input-area">
          <div v-if="pendingMedias.length > 0" class="pending-preview">
            <div class="pending-medias">
              <div v-for="(media, idx) in pendingMedias" :key="idx" class="pending-item">
                <span class="pending-label">
                  <template v-if="media.type === 'IMAGE'">🖼️</template>
                  <template v-else>📎</template>
                  {{ media.name }}
                </span>
                <button class="pending-remove" @click="removePendingMedia(idx)">✕</button>
              </div>
            </div>
            <button class="pending-clear-all" @click="clearAllPendingMedias">清除全部</button>
          </div>

          <div class="chat-input">
            <div class="input-tools">
              <div class="tool-btn-wrapper">
                <input type="file" accept="image/*" class="tool-input" id="image-input" @change="handleImageUpload" multiple />
                <label for="image-input" class="tool-btn magent" :class="{ disabled: isLoading }" data-ripple="true">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                  </svg>
                </label>
              </div>

              <div class="tool-btn-wrapper">
                <input type="file" class="tool-input" id="file-input" @change="handleFileUpload" multiple />
                <label for="file-input" class="tool-btn magent" :class="{ disabled: isLoading }" data-ripple="true">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                  </svg>
                </label>
              </div>

              <div class="tool-btn-wrapper">
                <button class="tool-btn magent" :class="{ recording: isRecording }" :disabled="isLoading" data-ripple="true"
                  @click="isRecording ? stopRecording() : startRecording()">
                  <svg v-if="!isRecording" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <path d="M19 9v6a2 2 0 0 1-2 2h-2"/>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="6" y="4" width="4" height="16"/>
                    <rect x="14" y="4" width="4" height="16"/>
                  </svg>
                </button>
                <span v-if="isRecording" class="recording-time">{{ recordingTime }}s</span>
              </div>
            </div>
            <input type="text" v-model="inputMessage" placeholder="今夜，你想聊些什么…" class="input-field"
              @keyup.enter="sendMessage()" :disabled="isLoading" />
            <button class="send-btn magent" data-ripple="true" :disabled="isLoading" @click="sendMessage()">
              <span class="send-btn__shine" aria-hidden="true"></span>
              <span class="send-btn__label">{{ isLoading ? '发送中' : '发送' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showDeleteConfirm" class="confirm-modal" @click="cancelDeleteSession">
      <div class="modal-content tilt" @click.stop>
        <div class="modal-header">
          <h3>确认删除</h3>
        </div>
        <div class="modal-body">
          <p>确定要删除这个会话吗？删除后将无法恢复，包括相关的消息、文件和记忆数据。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel magent" data-ripple="true" @click="cancelDeleteSession">取消</button>
          <button class="btn-confirm magent" data-ripple="true" @click="deleteSession">确认删除</button>
        </div>
      </div>
    </div>

    <div v-if="previewImage" class="image-preview-modal" @click="closeImagePreview">
      <div class="preview-content tilt" @click.stop>
        <button class="preview-close magent" data-ripple="true" @click="closeImagePreview">✕</button>
        <img :src="previewImage" alt="预览" class="preview-image" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ================================================================
 * ChatView —「哥特月光」主题
 * 语义与原模板结构 100% 兼容，只换皮肤与动效
 * ================================================================ */

/* ---------- 1. 外层容器：全屏 + 顶部 header 发光分割 ---------- */
.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  /* 透明底色，透出 body 的「天幕+星屑+月晕」层 */
  background: transparent;
  color: var(--text-primary);
  position: relative;
}

/* ---------- 2. 顶部导航栏：午夜紫黑玻璃 + 月光边线 + 哥特字体标题 ---------- */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 28px;
  position: relative;
  z-index: 10;
  /* 毛玻璃：午夜深靛 + 极淡紫辉光 */
  background: linear-gradient(
    180deg,
    rgba(10, 12, 38, 0.78) 0%,
    rgba(15, 18, 52, 0.55) 100%
  );
  backdrop-filter: blur(18px) saturate(130%);
  -webkit-backdrop-filter: blur(18px) saturate(130%);
  /* 顶部细边线：月光紫 */
  border-bottom: 1px solid var(--line-glow);
  /* 柔和月光阴影条 */
  box-shadow: 0 1px 0 rgba(231, 230, 255, 0.04) inset,
              0 12px 40px -20px rgba(139, 124, 255, 0.35);
}

.header-left { display: flex; align-items: center; gap: 14px; }

/* 侧栏折叠按钮：真朱红小点缀边圈 */
.sidebar-toggle {
  background: rgba(169, 156, 255, 0.08);
  border: 1px solid var(--line-glow);
  color: var(--moonlight-100);
  font-size: 18px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 10px;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.sidebar-toggle:hover {
  background: rgba(200, 16, 46, 0.12);
  border-color: var(--line-crimson);
  color: var(--crimson-100);
  transform: translateY(-1px);
  box-shadow: 0 0 0 1px var(--line-crimson),
              0 8px 24px -12px rgba(200, 16, 46, 0.4);
}

/* Logo + 标题：哥特 display 字体 + 朱红眼点（与登录页呼应的 𝔄 徽章） */
.logo {
  font-size: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  position: relative;
  background:
    radial-gradient(circle at 30% 28%, rgba(231, 230, 255, 0.72), rgba(169, 156, 255, 0.28) 55%, transparent 78%),
    linear-gradient(135deg, rgba(169, 156, 255, 0.7), rgba(139, 124, 255, 0.85));
  border: 1px solid rgba(255, 255, 255, 0.28);
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.18) inset,
    0 16px 40px -20px rgba(139, 124, 255, 0.8);
}
.logo__glyph {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 700;
  font-size: 24px;
  color: var(--text-inverse);
  text-shadow: 0 1px 0 rgba(255,255,255,0.35);
  transform: translateY(-1px);
}
.logo__pupil {
  position: absolute;
  top: 9px; right: 11px;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--crimson-500);
  box-shadow: 0 0 10px rgba(200, 16, 46, 0.75);
}
.title {
  /* 展示字体：Cormorant Garamond，贴合哥特贵族感 */
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 3px;
  background: linear-gradient(180deg, #fff 0%, #c8c2ff 70%, #9a8cff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  position: relative;
}
/* 「真朱红」小点缀：标题最后一个字下方一丝朱砂（爱尔奎特瞳色） */
.title::after {
  content: '';
  position: absolute;
  right: -6px;
  top: 10px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--crimson-500);
  box-shadow: 0 0 12px 2px rgba(200, 16, 46, 0.55);
}

.header-right { display: flex; align-items: center; gap: 16px; }

.username {
  font-size: 13px;
  color: var(--moonlight-100);
  background: rgba(169, 156, 255, 0.1);
  border: 1px solid var(--line-glow);
  padding: 6px 14px;
  border-radius: 999px;
  font-weight: 500;
  letter-spacing: 0.5px;
}

/* 退出登录：细边框胶囊，hover 透出朱砂感 */
.logout-btn {
  background: transparent;
  border: 1px solid var(--line-glow);
  color: var(--moonlight-100);
  padding: 8px 18px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.logout-btn:hover {
  background: rgba(200, 16, 46, 0.12);
  border-color: var(--line-crimson);
  color: var(--crimson-100);
  transform: translateY(-1px);
}

/* 插件市场入口：月光紫细边框胶囊，hover 透出月光感 */
.market-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--line-glow);
  color: var(--moonlight-100);
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.market-btn__icon {
  font-size: 14px;
  line-height: 1;
}
.market-btn:hover {
  background: rgba(139, 124, 255, 0.14);
  border-color: var(--moonlight-300);
  color: #fff;
  transform: translateY(-1px);
  box-shadow: 0 8px 22px -10px rgba(139, 124, 255, 0.55);
}

/* ---------- 3. 模式切换（快速 / 专家）：「月相双相」切换 ---------- */
.mode-selector {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: rgba(169, 156, 255, 0.08);
  border: 1px solid var(--line-glow);
  border-radius: 999px;
  box-shadow: inset 0 1px 0 rgba(231, 230, 255, 0.04);
}
.mode-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 7px 16px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-base) var(--ease-out-expo);
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: 0.8px;
  position: relative;
}
.mode-btn__icon {
  filter: drop-shadow(0 0 4px rgba(169,156,255,0.45));
  display: inline-flex;
  font-size: 13px;
}
.mode-btn:hover { color: var(--moonlight-100); }

/* 激活态：月光渐变 + 高光边 */
.mode-btn.active {
  color: var(--text-inverse);
  background:
    linear-gradient(135deg, var(--silver-halo) 0%, var(--moonlight-300) 60%, var(--moonlight-400) 100%);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.5) inset,
    0 8px 22px -10px rgba(139, 124, 255, 0.65);
}
/* 专家模式激活时，再加一个琥珀内边（呼应深度思考色调） */
.mode-btn.active:nth-child(2) {
  background: linear-gradient(135deg, #fff4d6 0%, var(--amber-400) 100%);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.5) inset,
    0 8px 22px -10px rgba(217, 164, 65, 0.7);
}

/* ---------- 4. 主区域布局（sidebar + chat content） ---------- */
.chat-body { flex: 1; display: flex; overflow: hidden; }

/* ====== Sidebar：深夜蓝 + 玻璃质感 + 选中态「朱砂条」 ====== */
.sidebar {
  width: 288px;
  display: flex;
  flex-direction: column;
  transition: width var(--dur-slow) var(--ease-out-expo);
  /* AI 生成的哥特侧边装饰背景 + 深色半透明叠层 + 毛玻璃 */
  background:
    /* 最上层深色叠层（保证会话列表文字可读性） */
    linear-gradient(180deg,
      rgba(14, 17, 48, 0.82) 0%,
      rgba(21, 26, 68, 0.72) 100%),
    /* AI 生成的哥特装饰底图（紫蓝渐变 + 哥特花窗 + 星屑 + 朱砂红竖线） */
    url('/assets/sidebar-gothic.jpg');
  background-size: cover;
  background-position: center center;
  backdrop-filter: blur(20px) saturate(130%);
  -webkit-backdrop-filter: blur(20px) saturate(130%);
  border-right: 1px solid var(--line-glow);
  position: relative;
  overflow: hidden;
}
/* sidebar 左侧极细朱红装饰线（呼应真祖瞳色） */
.sidebar::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 2px;
  background: linear-gradient(180deg,
    transparent 0%,
    rgba(200, 16, 46, 0.55) 20%,
    rgba(200, 16, 46, 0.25) 80%,
    transparent 100%);
  opacity: 0.8;
}
.sidebar.closed { width: 76px; }

.sidebar-header { padding: 20px; border-bottom: 1px solid var(--line-soft); }
.sidebar.closed .sidebar-header { padding: 20px 12px; }

/* 新建会话按钮：月光渐变 + 月晕辉光 */
.new-session-btn {
  width: 100%;
  background: linear-gradient(135deg, var(--moonlight-400) 0%, var(--moonlight-500) 55%, #6a58ff 100%);
  color: var(--text-inverse);
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 13px 16px;
  border-radius: 14px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  letter-spacing: 1px;
  transition: all var(--dur-base) var(--ease-out-expo);
  position: relative;
  box-shadow:
    0 0 0 1px rgba(169, 156, 255, 0.5) inset,
    0 10px 30px -10px rgba(139, 124, 255, 0.7);
}
/* 按钮左上高光（拟物微光） */
.new-session-btn::before {
  content: '';
  position: absolute;
  top: 1px; left: 10%; right: 10%;
  height: 40%;
  border-radius: 12px 12px 0 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.35), rgba(255,255,255,0));
  pointer-events: none;
}
.new-session-btn:hover {
  transform: translateY(-2px);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.7) inset,
    0 18px 40px -14px rgba(139, 124, 255, 0.85);
}

.session-list { flex: 1; overflow-y: auto; padding: 14px 12px; }

.session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  cursor: pointer;
  transition: all var(--dur-base) var(--ease-out-expo);
  position: relative;
  margin-bottom: 6px;
  color: var(--text-secondary);
  border: 1px solid transparent;
}
.session-item:hover {
  background: rgba(169, 156, 255, 0.08);
  border-color: var(--line-soft);
  transform: translateX(3px);
  color: var(--moonlight-100);
}
/* 选中态：紫辉光玻璃 + 左侧朱砂指示条（像真祖指甲划过的痕迹） */
.session-item.active {
  color: var(--text-primary);
  background: linear-gradient(135deg,
    rgba(169, 156, 255, 0.18) 0%,
    rgba(139, 124, 255, 0.10) 100%);
  border: 1px solid var(--line-glow);
  box-shadow: var(--shadow-glow);
}
.session-item.active::before {
  content: '';
  position: absolute;
  left: 0; top: 20%; bottom: 20%;
  width: 3px;
  border-radius: 0 4px 4px 0;
  background: linear-gradient(180deg, var(--crimson-400), var(--crimson-500));
  box-shadow: 0 0 10px rgba(200, 16, 46, 0.6);
}
.sidebar.closed .session-item { justify-content: center; padding: 14px 8px; }
.session-icon { font-size: 20px; filter: drop-shadow(0 0 4px rgba(169,156,255,0.5)); }
.session-title {
  flex: 1;
  font-size: 14px;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  letter-spacing: 0.3px;
}
.sidebar.closed .session-title { display: none; }

/* 删除按钮：hover 时显朱砂色 */
.session-delete {
  opacity: 0;
  visibility: hidden;
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 5px;
  border-radius: 8px;
  transition: all var(--dur-fast) var(--ease-out-expo);
}
.session-item:hover .session-delete { opacity: 1; visibility: visible; }
.session-delete:hover {
  color: var(--crimson-100);
  background: rgba(200, 16, 46, 0.15);
  transform: rotate(-6deg) scale(1.1);
}
.sidebar.closed .session-delete { display: none; }

/* ---------- 5. 聊天内容区：半透明月光雾 + 卡片流 ---------- */
.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background:
    linear-gradient(180deg, rgba(20, 23, 60, 0.28), rgba(8, 9, 26, 0.28));
  position: relative;
  /* 右上角月晕柔化（只在内容区局部再叠一层，增加层次） */
  overflow: hidden;
}

/* 「月光雾」装饰层：内容区中部一块极柔的银紫光晕 */
.chat-content::before {
  content: '';
  position: absolute;
  top: -20%;
  right: -10%;
  width: 540px;
  height: 540px;
  background: radial-gradient(circle,
    rgba(231, 230, 255, 0.14) 0%,
    rgba(139, 124, 255, 0.06) 35%,
    transparent 70%);
  pointer-events: none;
  filter: blur(6px);
  animation: contentHalo 12s ease-in-out infinite alternate;
}
@keyframes contentHalo {
  from { transform: translate(0, 0) scale(1); }
  to   { transform: translate(-24px, 18px) scale(1.08); }
}

.loading-more {
  text-align: center;
  padding: 14px;
  color: var(--text-tertiary);
  font-size: 13px;
  letter-spacing: 2px;
}
.chat-messages {
  flex: 1;
  padding: 32px 8% 20px;
  overflow-y: auto;
  position: relative;
  z-index: 1;
  scroll-behavior: smooth;
}

/* ---------- 6. 消息气泡 ---------- */
.message {
  margin-bottom: 28px;
  display: flex;
  animation: msgIn var(--dur-base) var(--ease-out-expo) both;
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
.message.user { justify-content: flex-end; }

/* 3D 微倾斜容器：过渡时间要覆盖 hover 与 JS tilt 复位；用 transform-style 保留层级 */
.message-bubble.tilt {
  transition:
    transform 340ms var(--ease-out-expo),
    box-shadow 340ms var(--ease-out-expo),
    border-color 340ms var(--ease-out-expo);
  transform-style: preserve-3d;
  will-change: transform;
}

/* 通用气泡基底：圆角「哥特灯笼」形 + 玻璃 */
.message-bubble {
  max-width: min(72%, 860px);
  padding: 16px 20px;
  font-size: 15px;
  line-height: 1.78;
  position: relative;
}

/* 流式打字光标：当最后一条 bot 消息仍在 isLoading 时，显示在 .message-text 之后 */
.msg-streaming .message-bubble .message-text::after,
.msg-streaming .message-bubble :deep(.msg-caret) {
  content: '';
  display: inline-block;
  vertical-align: -2px;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  background: linear-gradient(180deg, var(--moonlight-300), var(--crimson-400));
  box-shadow: 0 0 8px rgba(139,124,255,0.55), 0 0 10px rgba(200,16,46,0.35);
  border-radius: 2px;
  animation: caretBlink 1s steps(1) infinite;
}
@keyframes caretBlink {
  0%, 49%  { opacity: 1; }
  50%, 100% { opacity: 0; }
}

/* 消息进入时的「月相错开」错落：逐条轻微不同动画延迟（第 n 条） */
.message:nth-child(2) { animation-delay: 0.02s; }
.message:nth-child(3) { animation-delay: 0.04s; }
.message:nth-child(4) { animation-delay: 0.06s; }
.message:nth-child(5) { animation-delay: 0.08s; }
.message:nth-child(6) { animation-delay: 0.10s; }

/* 用户气泡：朱砂描边 + 月光紫渐变玻璃（高贵傲慢感） */
.message.user .message-bubble {
  background: linear-gradient(135deg,
    rgba(200, 16, 46, 0.22) 0%,
    rgba(139, 124, 255, 0.42) 60%,
    rgba(169, 156, 255, 0.28) 100%);
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: var(--moonlight-100);
  border-radius: 20px 20px 6px 22px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow:
    0 0 0 1px rgba(200, 16, 46, 0.18) inset,
    0 16px 40px -20px rgba(200, 16, 46, 0.4),
    0 16px 40px -20px rgba(139, 124, 255, 0.5);
}

/* 用户侧的上传文件/图卡片：更浅的玻璃色 */
.message.user .file-card {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.message.user .file-name { color: var(--moonlight-100); }
.message.user .file-icon { background: rgba(255, 255, 255, 0.18); }
.message.user .extracted-toggle {
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: rgba(255, 255, 255, 0.9);
}
.message.user .extracted-toggle:hover { background: rgba(255, 255, 255, 0.22); }
.message.user .extracted-content-box {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.14);
}
.message.user .extracted-label { color: rgba(231, 230, 255, 0.75); }
.message.user .extracted-text { color: var(--moonlight-100); }

/* 助手气泡：午夜玻璃 + 月光软边 */
.message.bot .message-bubble {
  background: linear-gradient(180deg,
    rgba(21, 26, 68, 0.72) 0%,
    rgba(14, 17, 48, 0.76) 100%);
  color: var(--text-primary);
  border-radius: 22px 22px 22px 6px;
  border: 1px solid var(--line-glow);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.03) inset,
    0 24px 60px -30px rgba(0, 0, 0, 0.75),
    0 16px 40px -20px rgba(139, 124, 255, 0.15);
}

/* 系统消息：分隔符式月光细线 + 衬线斜体小字 */
.message.system .message-bubble {
  background: transparent;
  color: var(--text-tertiary);
  border-radius: 999px;
  text-align: center;
  padding: 10px 18px;
  border: 1px dashed var(--line-soft);
  max-width: none;
  margin: 6px auto;
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}
.system-message {
  font-size: 13px;
  color: inherit;
  font-style: italic;
  font-family: var(--font-display);
  letter-spacing: 2px;
}

/* ---------- 7. 图片 / 文件媒体卡片 ---------- */
.media-section { margin-bottom: 14px; }
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
  max-width: 380px;
}
.image-wrapper {
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.45), 0 0 0 1px var(--line-glow);
  max-width: 340px;
  cursor: zoom-in;
  position: relative;
  transition: transform var(--dur-base) var(--ease-out-expo),
              box-shadow var(--dur-base) var(--ease-out-expo);
}
.image-wrapper::after {
  /* 四角小光角（像复古拍立得照片） */
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(231,230,255,0.2), transparent 40%),
    linear-gradient(315deg, rgba(200,16,46,0.12), transparent 40%);
}
.image-wrapper:hover {
  transform: translateY(-3px) scale(1.02);
  box-shadow: 0 18px 38px rgba(0, 0, 0, 0.55), 0 0 0 1px var(--line-crimson);
}
.message-image {
  max-width: 100%;
  max-height: 340px;
  display: block;
  object-fit: cover;
}
.image-overlay {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center,
    rgba(8, 9, 26, 0.2) 0%, rgba(8, 9, 26, 0.55) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out-expo);
}
.image-wrapper:hover .image-overlay { opacity: 1; }

.media-list { display: flex; flex-direction: column; gap: 10px; }

/* 文件卡片：羊皮纸色 + 月光边 */
.file-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg,
    rgba(231, 230, 255, 0.06),
    rgba(139, 124, 255, 0.08));
  border-radius: 12px;
  text-decoration: none;
  transition: all var(--dur-base) var(--ease-out-expo);
  border: 1px solid var(--line-soft);
}
.file-card:hover {
  background: rgba(169, 156, 255, 0.14);
  border-color: var(--line-glow);
  transform: translateY(-2px);
  box-shadow: var(--shadow-glow);
}
.file-icon {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(169,156,255,0.2), rgba(139,124,255,0.35));
  border-radius: 10px;
  font-size: 20px;
  border: 1px solid var(--line-glow);
}
.file-info { flex: 1; min-width: 0; }
.file-name {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
  display: block;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}

/* ---------- 8. Markdown 正文美化 ---------- */
.message-text {
  display: block;
  word-break: break-word;
  overflow-wrap: anywhere;
}
/* 助手文本里的 markdown 排版（通过 v-html 注入）：
   这里用 :deep() 穿透 scoped，因为 marked() 生成的是纯 HTML。 */
.message-text :deep(p)      { margin: 0 0 10px; }
.message-text :deep(p:last-child) { margin-bottom: 0; }
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3) {
  font-family: var(--font-display);
  color: var(--silver-halo);
  letter-spacing: 1px;
  margin: 18px 0 10px;
  line-height: 1.4;
}
.message-text :deep(h1) { font-size: 22px; }
.message-text :deep(h2) { font-size: 19px; border-bottom: 1px solid var(--line-soft); padding-bottom: 6px; }
.message-text :deep(h3) { font-size: 16px; color: var(--moonlight-300); }
.message-text :deep(blockquote) {
  border-left: 3px solid var(--crimson-500);
  background: rgba(200, 16, 46, 0.08);
  padding: 10px 14px;
  border-radius: 0 10px 10px 0;
  color: var(--moonlight-100);
  font-style: italic;
  margin: 10px 0;
}
.message-text :deep(code) {
  font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
  background: rgba(8, 9, 26, 0.6);
  border: 1px solid var(--line-glow);
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--silver-halo);
}
.message-text :deep(pre) {
  background: linear-gradient(180deg, rgba(8,9,26,0.9), rgba(14,17,48,0.9));
  border: 1px solid var(--line-glow);
  border-radius: 12px;
  padding: 14px 16px;
  margin: 12px 0;
  overflow-x: auto;
  box-shadow: 0 12px 30px -18px rgba(139, 124, 255, 0.6);
}
.message-text :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
}
.message-text :deep(ul),
.message-text :deep(ol) { padding-left: 22px; margin: 10px 0; }
.message-text :deep(li) { margin: 4px 0; }
.message-text :deep(strong) {
  background: linear-gradient(135deg, var(--silver-halo), var(--amber-400));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-weight: 700;
  padding: 0 2px;
}
.message-text :deep(hr) {
  border: none;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line-glow), transparent);
  margin: 18px 0;
}
.message-text :deep(a) {
  color: var(--moonlight-300);
  text-decoration: none;
  border-bottom: 1px dashed rgba(200, 207, 255, 0.3);
}
.message-text :deep(a:hover) {
  color: var(--silver-halo);
  border-bottom-color: var(--silver-halo);
}

/* Markdown 表格：夜光下的「羊皮纸帐簿」样式 */
.message-text :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 14px 0;
  font-size: 13.5px;
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(8,9,26,0.55), rgba(14,17,48,0.5));
  border: 1px solid var(--line-glow);
  box-shadow: 0 14px 30px -18px rgba(139,124,255,0.45);
}
.message-text :deep(thead) {
  background: linear-gradient(135deg, rgba(200,16,46,0.14), rgba(139,124,255,0.18));
}
.message-text :deep(th) {
  font-family: var(--font-display);
  letter-spacing: 1.5px;
  font-weight: 700;
  color: var(--moonlight-100);
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-glow);
}
.message-text :deep(td) {
  padding: 9px 12px;
  border-bottom: 1px dashed var(--line-soft);
  color: var(--text-secondary);
}
.message-text :deep(tbody tr:last-child td) { border-bottom: none; }
.message-text :deep(tbody tr:hover) {
  background: rgba(169,156,255,0.08);
}
.message-text :deep(kbd) {
  background: rgba(8,9,26,0.7);
  border: 1px solid var(--line-glow);
  color: var(--silver-halo);
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
  box-shadow: 0 1px 0 rgba(231,230,255,0.08) inset;
}
.message-text :deep(del) {
  color: var(--text-tertiary);
  text-decoration-color: var(--crimson-400);
}
.message-text :deep(input[type="checkbox"]) {
  accent-color: var(--moonlight-500);
  margin-right: 6px;
}

/* ---------- 9. 提取内容折叠（用户图/文件 OCR 提取） ---------- */
.extracted-container { margin-top: 12px; }
.extracted-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  background: rgba(169, 156, 255, 0.1);
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  transition: all var(--dur-fast) var(--ease-out-expo);
}
.extracted-toggle:hover {
  background: rgba(169, 156, 255, 0.22);
  color: var(--moonlight-100);
  border-color: var(--line-glow);
}
.extracted-content-box {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(8, 9, 26, 0.35);
  border: 1px dashed var(--line-glow);
  animation: fadeDrop var(--dur-base) var(--ease-out-expo) both;
}
@keyframes fadeDrop {
  from { opacity: 0; transform: translateY(-6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.extracted-label {
  color: var(--moonlight-300);
  font-weight: 600;
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  letter-spacing: 1px;
}
.extracted-text {
  color: var(--text-secondary);
  word-break: break-all;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

/* ---------- 10. 搜索状态提示 ---------- */
.search-status { margin-top: 12px; padding: 10px 14px; border-radius: 10px; font-size: 13px; }
.search-status-searching {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.25);
  color: #9ec3ff;
}
.search-status-completed {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #86efac;
}
.search-spinner { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------- 11. 折叠面板：工具调用 & 深度思考 ---------- */
.collapsible-panel {
  margin-top: 14px;
  border-radius: 14px;
  overflow: hidden;
  position: relative;
  animation: panelIn 380ms var(--ease-out-quint) both;
}
@keyframes panelIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.collapsible-body {
  /* 面板展开时做一下 stagger 感：子元素逐次显现（用内置 animation + 序号） */
  overflow: hidden;
}
.collapsible-body > * {
  animation: subIn 300ms var(--ease-out-expo) both;
}
.collapsible-body > *:nth-child(1) { animation-delay: 0.02s; }
.collapsible-body > *:nth-child(2) { animation-delay: 0.06s; }
.collapsible-body > *:nth-child(3) { animation-delay: 0.10s; }
.collapsible-body > *:nth-child(4) { animation-delay: 0.14s; }
@keyframes subIn {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.collapsible-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: background var(--dur-fast) var(--ease-out-expo);
}
.collapsible-title { flex: 1; }
.collapsible-chevron {
  transition: transform var(--dur-base) var(--ease-out-expo);
}
.collapsible-chevron.collapsed { transform: rotate(-90deg); }
.collapsible-body {
  padding: 4px 14px 14px;
  border-top: 1px solid var(--line-soft);
  padding-top: 10px;
}

/* 思考过程面板（合并工具调用 + 深度思考）：琥珀金主色（回忆之光） */
.thinking-panel {
  background: linear-gradient(180deg,
    rgba(217, 164, 65, 0.12),
    rgba(217, 164, 65, 0.04));
  border: 1px solid rgba(217, 164, 65, 0.28);
  border-left: 3px solid var(--amber-500);
  box-shadow: 0 14px 34px -24px rgba(217, 164, 65, 0.55);
}
.thinking-panel .collapsible-header { color: #f1d28a; }
.thinking-panel .collapsible-header:hover { background: rgba(217, 164, 65, 0.14); }
.thinking-panel .collapsible-body { border-top-color: rgba(217, 164, 65, 0.22); }

/* 工具步骤 ↔ 深度思考之间的分隔线（仅当两者都存在时显示） */
.thinking-divider {
  height: 1px;
  margin: 14px 4px 12px;
  background: linear-gradient(90deg,
    transparent, rgba(217, 164, 65, 0.45) 30%, rgba(217, 164, 65, 0.45) 70%, transparent);
  position: relative;
}
.thinking-divider::after {
  /* 分隔线中间的小圆点，强化"阶段分界"感 */
  content: '';
  position: absolute;
  top: -2px; left: 50%;
  transform: translateX(-50%);
  width: 4px; height: 4px;
  background: var(--amber-500);
  border-radius: 50%;
  box-shadow: 0 0 6px rgba(217, 164, 65, 0.7);
}

/* 思考过程徽章：AI 生成的哥特齿轮+灯泡+朱砂血滴 logo */
.thinking-emblem {
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: 50%;
  border: 1px solid rgba(217, 164, 65, 0.5);
  box-shadow: 0 0 12px rgba(217, 164, 65, 0.45),
              0 0 0 1px rgba(255, 230, 160, 0.25) inset;
  flex-shrink: 0;
  background: #0a0d24;
}
/* 思考中时徽章旋转（替代原来的 SVG spinner） */
.thinking-emblem.thinking-spinner {
  animation: spin 1.6s linear infinite;
  filter: drop-shadow(0 0 6px rgba(200, 16, 46, 0.6));
}

/* ---------- 12. 步骤 & 工具小卡片 ---------- */
.thinking-step {
  padding: 12px 14px;
  margin-bottom: 10px;
  background: linear-gradient(180deg,
    rgba(30, 58, 138, 0.24),
    rgba(30, 64, 175, 0.14));
  border-radius: 12px;
  border: 1px solid rgba(59, 130, 246, 0.22);
}
.thinking-step:last-child { margin-bottom: 0; }
.thinking-step-header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.thinking-step-num {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--moonlight-400), var(--moonlight-500));
  color: var(--text-inverse);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-display);
  box-shadow: 0 0 0 1px rgba(255,255,255,0.3) inset;
}
.thinking-step-content { flex: 1; min-width: 0; }
.thinking-step-analysis {
  color: #e6eeff;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking-step-purpose {
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: 12px;
  font-style: italic;
  font-family: var(--font-display);
  letter-spacing: 1px;
}

/* 深度思考步骤卡片：琥珀金底（回忆之光），与工具步骤的冷蓝形成对比 */
.thinking-step-deep {
  background: linear-gradient(180deg,
    rgba(217, 164, 65, 0.14),
    rgba(193, 133, 24, 0.08));
  border-color: rgba(217, 164, 65, 0.32);
}
/* 深度思考的步骤编号：琥珀金渐变圆，和工具步骤的月光蓝圆区分 */
.step-num-deep {
  background: linear-gradient(135deg, #e8a73d, #b2701a);
  color: #1a1a1a;
  box-shadow: 0 0 0 1px rgba(255, 230, 160, 0.55) inset,
              0 0 12px rgba(217, 164, 65, 0.45);
}
/* 步骤子标题（如"深度思考推理"）：哥特衬线 + 字母间距 */
.thinking-step-title {
  font-family: var(--font-display);
  font-weight: 600;
  letter-spacing: 1.2px;
  color: #f1d28a;
  margin-bottom: 6px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.thinking-step-title::before {
  /* 小装饰点：哥特风格，两个并列琥珀金小点 */
  content: '✦';
  color: var(--amber-400);
  font-size: 11px;
}
/* 步骤内部状态标签（展开/收起/思考中） */
.step-status {
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 1px;
  padding: 1px 8px;
  margin-left: 6px;
  border-radius: 999px;
  background: rgba(217, 164, 65, 0.18);
  color: #f1d28a;
  font-family: var(--font-body);
  font-style: normal;
}
/* 步骤内部小折叠箭头：默认朝下，collapsed 时朝右 */
.step-chevron {
  flex-shrink: 0;
  color: rgba(217, 164, 65, 0.7);
  transition: transform 220ms var(--ease-out-expo);
}
.step-chevron.collapsed { transform: rotate(90deg); }
/* 步骤正文容器（可折叠）：展开时的内容区 */
.thinking-step-body {
  margin-top: 8px;
  padding-left: 36px;
}
/* 深度思考步骤内的 analysis：renderMarkdown 输出 HTML，去掉 pre-wrap 让块级元素正常折叠 */
.thinking-step-deep .thinking-step-analysis {
  white-space: normal;
  color: #f4e5c3;
  font-size: 14px;
  line-height: 1.82;
}
/* 深度思考内 Markdown 粗体：用金色渐变（与消息气泡的 strong 一致） */
.thinking-step-deep .thinking-step-analysis :deep(strong) {
  background: linear-gradient(135deg, #fff3d0, var(--amber-400));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-weight: 700;
}
/* 深度思考内 Markdown 列表/段落间距微调 */
.thinking-step-deep .thinking-step-analysis :deep(p) { margin: 0 0 6px; }
.thinking-step-deep .thinking-step-analysis :deep(ul),
.thinking-step-deep .thinking-step-analysis :deep(ol) { padding-left: 18px; margin: 6px 0; }
.thinking-step-deep .thinking-step-analysis :deep(code) {
  background: rgba(8, 9, 26, 0.55);
  padding: 1px 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: #e8d59a;
}
.thinking-step-tools {
  margin-top: 10px;
  padding-left: 36px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-right: 14px;
  margin-bottom: 4px;
}
.tool-summary svg { opacity: 0.8; }
.tool-summary.tool-running {
  color: #9ec3ff;
  animation: pulseSoft 1.6s ease-in-out infinite;
}
.tool-summary.tool-error { color: var(--crimson-100); }
@keyframes pulseSoft {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.45; }
}

/* 工具小折叠卡片 */
.tool-collapsible {
  border-radius: 10px;
  background: rgba(8, 9, 26, 0.38);
  border: 1px solid var(--line-soft);
  overflow: hidden;
}
.tool-collapsible .tool-summary {
  width: 100%;
  padding: 6px 10px;
  border-radius: 10px;
  margin: 0;
  transition: background var(--dur-fast) var(--ease-out-expo);
}
.tool-collapsible .tool-summary:hover { background: rgba(59, 130, 246, 0.12); }
.tool-chevron {
  transition: transform var(--dur-base) var(--ease-out-expo);
  margin-left: auto;
}
.tool-chevron.collapsed { transform: rotate(-90deg); }

.search-links-list {
  margin-top: 6px;
  padding: 6px 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.search-link-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--moonlight-300);
  text-decoration: none;
  line-height: 1.4;
  word-break: break-all;
  padding: 4px 8px;
  border-radius: 8px;
  transition: all var(--dur-fast) var(--ease-out-expo);
}
.search-link-item:hover {
  color: var(--silver-halo);
  background: rgba(169, 156, 255, 0.12);
}
.search-link-item svg { flex-shrink: 0; opacity: 0.7; }

/* 深度思考正文：暖琥珀衬线体，给人「念日记」的回忆感 */
.reasoning-content {
  color: #f7e5b5;
  font-size: 13.5px;
  line-height: 1.85;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-body);
  letter-spacing: 0.2px;
}

/* ---------- 13. 聊天输入区：浮岛玻璃 ---------- */
.chat-input-area {
  padding: 10px 0 22px;
  position: relative;
  z-index: 2;
}
.chat-input-area::before {
  /* 输入区上方的柔边月光光带（暗示"分界线"，替代生硬 box-shadow） */
  content: '';
  position: absolute;
  left: 5%; right: 5%; top: -10px;
  height: 2px;
  background: linear-gradient(90deg,
    transparent, var(--line-glow) 50%, transparent);
  filter: blur(2px);
}

.pending-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 6% 0;
  font-size: 13px;
  flex-wrap: wrap;
}
.pending-medias {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  flex: 1;
}
.pending-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pending-label {
  color: var(--moonlight-100);
  background: rgba(169, 156, 255, 0.14);
  border: 1px solid var(--line-glow);
  padding: 6px 14px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.pending-remove {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 16px;
  padding: 4px;
  line-height: 1;
  border-radius: 6px;
  transition: all var(--dur-fast) var(--ease-out-expo);
}
.pending-remove:hover {
  color: var(--crimson-100);
  background: rgba(200, 16, 46, 0.15);
  transform: rotate(90deg);
}
.pending-clear-all {
  background: rgba(200, 16, 46, 0.12);
  border: 1px solid var(--line-crimson);
  color: var(--crimson-100);
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out-expo);
  font-weight: 500;
  letter-spacing: 1px;
}
.pending-clear-all:hover {
  background: rgba(200, 16, 46, 0.22);
  transform: translateY(-1px);
}

/* 输入条外层：悬浮玻璃岛 */
.chat-input {
  margin: 12px 6% 0;
  padding: 10px 14px;
  display: flex;
  gap: 12px;
  align-items: center;
  border-radius: 22px;
  background: linear-gradient(180deg,
    rgba(21, 26, 68, 0.75),
    rgba(8, 9, 26, 0.88));
  border: 1px solid var(--line-glow);
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.04) inset,
    0 20px 50px -24px rgba(0, 0, 0, 0.8),
    0 10px 40px -18px rgba(139, 124, 255, 0.3);
  transition: box-shadow var(--dur-base) var(--ease-out-expo),
              border-color var(--dur-base) var(--ease-out-expo);
}
.chat-input:focus-within {
  border-color: rgba(231, 230, 255, 0.38);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.2) inset,
    0 0 0 4px rgba(169, 156, 255, 0.12),
    0 22px 52px -20px rgba(0, 0, 0, 0.85),
    0 14px 50px -22px rgba(139, 124, 255, 0.45);
}

.input-tools { display: flex; align-items: center; gap: 6px; }
.tool-input { display: none; }
.tool-btn-wrapper { display: flex; align-items: center; gap: 4px; position: relative; }

.tool-btn {
  width: 42px;
  height: 42px;
  border: 1px solid var(--line-soft);
  background: rgba(169, 156, 255, 0.06);
  color: var(--text-secondary);
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.tool-btn:hover:not(.disabled):not(:disabled) {
  background: rgba(169, 156, 255, 0.16);
  color: var(--silver-halo);
  border-color: var(--line-glow);
  transform: translateY(-2px);
  box-shadow: 0 10px 22px -14px rgba(139, 124, 255, 0.7);
}
.tool-btn.disabled, .tool-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.tool-btn.recording {
  background: linear-gradient(135deg, rgba(200,16,46,0.4), rgba(226,59,89,0.55));
  color: #fff;
  border-color: var(--line-crimson);
  animation: recordBeat 1.2s ease-in-out infinite;
}
@keyframes recordBeat {
  0%, 100% { box-shadow: 0 0 0 0 rgba(200, 16, 46, 0.45); }
  50%      { box-shadow: 0 0 0 8px rgba(200, 16, 46, 0); }
}
.recording-time {
  font-size: 12px;
  color: var(--crimson-100);
  white-space: nowrap;
  font-weight: 700;
  font-family: var(--font-display);
  letter-spacing: 1.5px;
}

.input-field {
  flex: 1;
  padding: 12px 14px;
  border: 1px solid transparent;
  border-radius: 14px;
  font-size: 15px;
  color: var(--text-primary);
  background: transparent;
  transition: all var(--dur-fast) var(--ease-out-expo);
  font-family: inherit;
}
.input-field::placeholder {
  color: var(--text-tertiary);
  font-style: italic;
  letter-spacing: 1px;
  font-family: var(--font-display);
}
.input-field:focus {
  outline: none;
  background: rgba(8, 9, 26, 0.35);
  border-color: var(--line-glow);
}
.input-field:disabled { color: var(--text-tertiary); cursor: not-allowed; }

/* 发送按钮：朱砂主调 + 月光内高光（真祖红瞳的"决定性"） */
.send-btn {
  background: linear-gradient(135deg, var(--crimson-500) 0%, #a10c22 55%, var(--moonlight-500) 100%);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 12px 28px;
  border-radius: 16px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 2px;
  font-family: var(--font-display);
  transition: all var(--dur-base) var(--ease-out-expo);
  position: relative;
  overflow: hidden;
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.25) inset,
    0 12px 28px -12px rgba(200, 16, 46, 0.7),
    0 10px 28px -12px rgba(139, 124, 255, 0.5);
}
.send-btn::before {
  content: '';
  position: absolute;
  top: 1px; left: 14px; right: 14px; height: 36%;
  border-radius: 14px 14px 0 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.35), rgba(255,255,255,0));
  pointer-events: none;
  z-index: 2;
}
.send-btn__shine {
  position: absolute;
  top: 0; left: -80%;
  width: 55%; height: 100%;
  background: linear-gradient(115deg,
    transparent,
    rgba(255, 255, 255, 0.35) 50%,
    transparent);
  transform: skewX(-20deg);
  z-index: 1;
  pointer-events: none;
  filter: blur(1px);
}
.send-btn:hover:not(:disabled) .send-btn__shine {
  animation: shine 900ms var(--ease-out-quint);
}
@keyframes shine {
  0%   { left: -80%; opacity: 0; }
  15%  { opacity: 1; }
  100% { left: 130%; opacity: 0; }
}
.send-btn__label {
  position: relative;
  z-index: 3;
}
.send-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.45) inset,
    0 18px 40px -14px rgba(200, 16, 46, 0.85),
    0 14px 40px -14px rgba(139, 124, 255, 0.7);
}
.send-btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* ---------- 14. 删除确认弹窗：午夜玻璃 + 朱砂确认 ---------- */
.confirm-modal {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(circle at 50% 40%, rgba(200, 16, 46, 0.22), transparent 55%),
    rgba(4, 5, 16, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.22s var(--ease-out-expo);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.modal-content {
  background: linear-gradient(180deg, rgba(21, 26, 68, 0.95), rgba(8, 9, 26, 0.98));
  border-radius: 22px;
  width: 440px;
  max-width: 90%;
  overflow: hidden;
  border: 1px solid var(--line-glow);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.04) inset,
    0 30px 80px -30px rgba(0, 0, 0, 0.9),
    0 20px 60px -20px rgba(200, 16, 46, 0.3);
  animation: slideUp 0.32s var(--ease-out-expo);
}
@keyframes slideUp {
  from { transform: translateY(26px) scale(0.98); opacity: 0; }
  to   { transform: translateY(0) scale(1);        opacity: 1; }
}

.modal-header {
  padding: 22px 24px;
  border-bottom: 1px solid var(--line-soft);
  background: linear-gradient(135deg,
    rgba(200, 16, 46, 0.12), transparent 60%);
}
.modal-header h3 {
  margin: 0;
  font-size: 20px;
  color: var(--moonlight-100);
  font-family: var(--font-display);
  letter-spacing: 2px;
  font-weight: 600;
}
.modal-body { padding: 22px 24px; }
.modal-body p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14.5px;
  line-height: 1.8;
}

.modal-footer {
  padding: 18px 24px;
  border-top: 1px solid var(--line-soft);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
.btn-cancel {
  padding: 10px 24px;
  border: 1px solid var(--line-glow);
  border-radius: 12px;
  background: rgba(169, 156, 255, 0.06);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-base) var(--ease-out-expo);
  letter-spacing: 1px;
}
.btn-cancel:hover {
  background: rgba(169, 156, 255, 0.16);
  color: var(--moonlight-100);
  transform: translateY(-1px);
}

.btn-confirm {
  padding: 10px 24px;
  border: 1px solid rgba(255,255,255,0.25);
  border-radius: 12px;
  background: linear-gradient(135deg, var(--crimson-500), #8f0a1e);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 2px;
  transition: all var(--dur-base) var(--ease-out-expo);
  box-shadow: 0 10px 26px -12px rgba(200, 16, 46, 0.8);
}
.btn-confirm:hover {
  transform: translateY(-1px);
  box-shadow: 0 16px 34px -14px rgba(200, 16, 46, 0.95);
}

/* ---------- 15. 图片预览：全屏夜幕 + 银月画框 ---------- */
.image-preview-modal {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(circle at 50% 50%, rgba(169, 156, 255, 0.2), rgba(4, 5, 16, 0.96) 70%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  animation: fadeIn 0.22s var(--ease-out-expo);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.preview-content {
  position: relative;
  max-width: 92%;
  max-height: 92%;
  padding: 28px;
  border-radius: 24px;
  background: linear-gradient(180deg,
    rgba(21, 26, 68, 0.7),
    rgba(8, 9, 26, 0.85));
  border: 1px solid var(--line-glow);
  box-shadow: 0 30px 90px -20px rgba(0, 0, 0, 0.9),
              0 20px 60px -24px rgba(139, 124, 255, 0.6);
  animation: slideUp 0.3s var(--ease-out-expo);
}
.preview-close {
  position: absolute;
  top: 6px;
  right: 10px;
  background: rgba(231, 230, 255, 0.1);
  border: 1px solid var(--line-glow);
  color: var(--moonlight-100);
  font-size: 22px;
  cursor: pointer;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-base) var(--ease-out-expo);
}
.preview-close:hover {
  background: rgba(200, 16, 46, 0.18);
  border-color: var(--line-crimson);
  color: var(--crimson-100);
  transform: rotate(90deg) scale(1.05);
}
.preview-image {
  max-width: 100%;
  max-height: 80vh;
  border-radius: 18px;
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.14),
    0 20px 60px rgba(0, 0, 0, 0.7);
}
</style>