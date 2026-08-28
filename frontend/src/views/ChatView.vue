<script setup>import { nextTick, onMounted, ref, reactive, watch } from 'vue';
import { useRouter } from 'vue-router';
import service from '../api/index.js';
import { marked } from 'marked';

// Markdown渲染函数
const renderMarkdown = (text) => {
  if (!text) return '';
  return marked(text, { breaks: true });
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
 await loadSessions();
 if (sessions.value.length === 0) {
 await createNewSession();
 }
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
    deepThinkingReasoning: '',
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
    // 深度思考推理链全文（独立于步骤列表，单独折叠显示）
    deepThinkingReasoning: ''
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
        <button class="sidebar-toggle" @click="sidebarOpen = !sidebarOpen">☰</button>
        <span class="logo">🤖</span>
        <span class="title">小爱</span>
      </div>
      <div class="header-right">
          <div class="mode-selector">
            <button 
              :class="['mode-btn', { active: currentMode === 'fast' }]" 
              @click="currentMode = 'fast'"
              title="快速模式：直接响应，速度快"
            >
              ⚡ 快速模式
            </button>
            <button 
              :class="['mode-btn', { active: currentMode === 'expert' }]" 
              @click="currentMode = 'expert'"
              title="专家模式：深度分析，支持联网搜索和图片分析"
            >
              🔬 专家模式
            </button>
          </div>
          <span class="username">{{ currentUser }}</span>
          <button class="logout-btn" @click="handleLogout">退出登录</button>
        </div>
    </header>

    <div class="chat-body">
      <aside class="sidebar" :class="{ 'closed': !sidebarOpen }">
        <div class="sidebar-header">
          <button class="new-session-btn" @click="createNewSession">+ 新建会话</button>
        </div>
        <div class="session-list">
          <div
            v-for="session in sessions"
            :key="session.id"
            :class="['session-item', { active: currentSessionId === session.id }]"
            @click="selectSession(session)"
          >
            <span class="session-icon">💬</span>
            <span class="session-title">{{ session.title || session.id }}</span>
            <button class="session-delete" @click.stop="confirmDeleteSession(session)" title="删除会话">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18"/>
                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
              </svg>
            </button>
          </div>
        </div>
      </aside>

      <div class="chat-content">
        <div v-if="isLoadingMore && messages.length > 1" class="loading-more">加载中...</div>
        <div class="chat-messages" ref="chatContainer" @scroll="handleScroll">
          <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.type]">
            <div class="message-bubble">
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
                
                <!-- 工具调用结果面板（折叠栏，默认折叠） -->
                <div v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0" class="collapsible-panel tools-panel">
                  <div class="collapsible-header" @click="toggleThinkingSteps(index)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                    </svg>
                    <span class="collapsible-title">
                      工具调用结果
                      · 共 {{ msg.thinkingSteps.length }} 步
                      <template v-if="msg.thinkingStartTime && !msg.isThinking">
                        · 耗时 {{ ((Date.now() - msg.thinkingStartTime) / 1000).toFixed(1) }}s
                      </template>
                    </span>
                    <svg :class="['collapsible-chevron', { 'collapsed': !expandedSteps[index] }]" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="9 18 15 12 9 6"/>
                    </svg>
                  </div>
                  <div v-if="expandedSteps[index]" class="collapsible-body">
                    <!-- 步骤列表 -->
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
                  </div>
                </div>

                <!-- 深度思考推理链面板（折叠栏，默认折叠） -->
                <div v-if="msg.deepThinkingReasoning && msg.deepThinkingReasoning.length > 0" class="collapsible-panel reasoning-panel">
                  <div class="collapsible-header" @click="toggleReasoning(index)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'thinking-spinner': msg.isThinking }">
                      <path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.3A7 7 0 0 0 12 2z"/>
                    </svg>
                    <span class="collapsible-title">
                      {{ msg.isThinking ? '深度思考中...' : '深度思考过程' }}
                    </span>
                    <svg :class="['collapsible-chevron', { 'collapsed': !expandedReasoning[index] }]" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="9 18 15 12 9 6"/>
                    </svg>
                  </div>
                  <div v-if="expandedReasoning[index]" class="collapsible-body">
                    <div class="reasoning-content">{{ msg.deepThinkingReasoning }}</div>
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
                <label for="image-input" class="tool-btn" :class="{ disabled: isLoading }">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                  </svg>
                </label>
              </div>

              <div class="tool-btn-wrapper">
                <input type="file" class="tool-input" id="file-input" @change="handleFileUpload" multiple />
                <label for="file-input" class="tool-btn" :class="{ disabled: isLoading }">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                  </svg>
                </label>
              </div>

              <div class="tool-btn-wrapper">
                <button class="tool-btn" :class="{ recording: isRecording }" :disabled="isLoading"
                  @click="isRecording ? stopRecording() : startRecording()">
                  <svg v-if="!isRecording" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <path d="M19 9v6a2 2 0 0 1-2 2h-2"/>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="6" y="4" width="4" height="16"/>
                    <rect x="14" y="4" width="4" height="16"/>
                  </svg>
                </button>
                <span v-if="isRecording" class="recording-time">{{ recordingTime }}s</span>
              </div>
            </div>
            <input type="text" v-model="inputMessage" placeholder="输入消息..." class="input-field"
              @keyup.enter="sendMessage()" :disabled="isLoading" />
            <button class="send-btn" :disabled="isLoading" @click="sendMessage()">
              {{ isLoading ? '发送中' : '发送' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showDeleteConfirm" class="confirm-modal" @click="cancelDeleteSession">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>确认删除</h3>
        </div>
        <div class="modal-body">
          <p>确定要删除这个会话吗？删除后将无法恢复，包括相关的消息、文件和记忆数据。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="cancelDeleteSession">取消</button>
          <button class="btn-confirm" @click="deleteSession">确认删除</button>
        </div>
      </div>
    </div>

    <div v-if="previewImage" class="image-preview-modal" @click="closeImagePreview">
      <div class="preview-content" @click.stop>
        <button class="preview-close" @click="closeImagePreview">✕</button>
        <img :src="previewImage" alt="预览" class="preview-image" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  background-color: #f5f7fa;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3);
  position: relative;
  z-index: 10;
}

.header-left { display: flex; align-items: center; gap: 12px; }
.sidebar-toggle {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: white;
  font-size: 20px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  transition: all 0.2s;
}
.sidebar-toggle:hover { background: rgba(255, 255, 255, 0.25); transform: scale(1.05); }
.logo { font-size: 32px; }
.title { font-size: 22px; font-weight: 700; letter-spacing: 2px; }

.header-right { display: flex; align-items: center; gap: 16px; }
.username { font-size: 14px; opacity: 0.9; background: rgba(255, 255, 255, 0.15); padding: 6px 14px; border-radius: 20px; font-weight: 500; }

.logout-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 8px 20px;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
}
.logout-btn:hover { 
  background: rgba(255, 255, 255, 0.3); 
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 255, 255, 0.2);
}

/* 模式选择器样式 */
.mode-selector {
  display: flex;
  gap: 8px;
  background: rgba(255, 255, 255, 0.1);
  padding: 4px;
  border-radius: 20px;
}

.mode-btn {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.8);
  padding: 6px 14px;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.mode-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: white;
}

.mode-btn.active {
  background: rgba(255, 255, 255, 0.25);
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.chat-body { flex: 1; display: flex; overflow: hidden; }

.sidebar {
  width: 280px;
  background-color: white;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  transition: all 0.35s ease;
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.04);
}
.sidebar.closed { width: 72px; }
.sidebar-header { padding: 20px; border-bottom: 1px solid #f1f5f9; }
.sidebar.closed .sidebar-header { padding: 20px 12px; }

.new-session-btn {
  width: 100%;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  border: none;
  padding: 14px 16px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}
.new-session-btn:hover { 
  opacity: 0.95; 
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45);
}

.session-list { flex: 1; overflow-y: auto; padding: 12px; }
.session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.25s;
  position: relative;
  margin-bottom: 6px;
}
.session-item:hover { 
  background-color: #f8fafc;
  transform: translateX(4px);
}
.session-item.active { 
  background: linear-gradient(135deg, #e0e7ff 0%, #ddd6fe 100%);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}
.sidebar.closed .session-item { justify-content: center; padding: 14px 8px; }
.session-icon { font-size: 20px; }
.session-title {
  flex: 1;
  font-size: 14px;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.sidebar.closed .session-title { display: none; }

.session-delete {
  opacity: 0;
  visibility: hidden;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.2s;
}
.session-item:hover .session-delete {
  opacity: 1;
  visibility: visible;
}
.session-delete:hover {
  color: #ef4444;
  background-color: #fef2f2;
}
.sidebar.closed .session-delete { display: none; }

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
}

.loading-more { text-align: center; padding: 12px; color: #94a3b8; font-size: 14px; }
.chat-messages { flex: 1; padding: 24px; overflow-y: auto; }

.message { margin-bottom: 24px; display: flex; }
.message.user { justify-content: flex-end; }
.message.user .message-bubble {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  border-radius: 20px 20px 6px 20px;
}
.message.user .file-card {
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.25);
}
.message.user .file-name { color: white; }
.message.user .file-icon { background: rgba(255, 255, 255, 0.2); }
.message.user .extracted-toggle {
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.9);
}
.message.user .extracted-toggle:hover {
  background: rgba(255, 255, 255, 0.25);
}
.message.user .extracted-content-box {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
}
.message.user .extracted-label { color: rgba(255, 255, 255, 0.8); }
.message.user .extracted-text { color: white; }
.message.bot .message-bubble {
  background-color: white;
  color: #334155;
  border-radius: 20px 20px 20px 6px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.message.system .message-bubble {
  background-color: #f1f5f9;
  color: #64748b;
  border-radius: 10px;
  text-align: center;
}
.message-bubble {
  max-width: 68%;
  padding: 16px 20px;
  font-size: 15px;
  line-height: 1.7;
}

.system-message {
  font-size: 13px;
  color: #94a3b8;
}

.media-section {
  margin-bottom: 12px;
}

.image-wrapper {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  max-width: 320px;
  cursor: zoom-in;
  position: relative;
  transition: all 0.3s;
}
.image-wrapper:hover {
  transform: scale(1.02);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}
.message-image {
  max-width: 100%;
  max-height: 320px;
  display: block;
  object-fit: cover;
}
.image-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: linear-gradient(to top, rgba(0,0,0,0.6), transparent);
  padding: 20px;
  display: flex;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}
.image-wrapper:hover .image-overlay {
  opacity: 1;
}

.file-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: #f8fafc;
  border-radius: 12px;
  text-decoration: none;
  transition: all 0.25s;
  border: 1px solid #e2e8f0;
}
.file-card:hover {
  background: #e0e7ff;
  border-color: #6366f1;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.15);
}
.file-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e0e7ff;
  border-radius: 10px;
  font-size: 22px;
}
.file-info { flex: 1; }
.file-name {
  font-size: 14px;
  color: #334155;
  font-weight: 500;
}

.message-text { display: block; word-break: break-all; }

.extracted-container {
  margin-top: 12px;
}
.extracted-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #64748b;
  transition: all 0.2s;
}
.extracted-toggle:hover {
  background: #e2e8f0;
  color: #334155;
}
.extracted-content-box {
  margin-top: 8px;
  padding: 14px;
  background-color: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  animation: fadeIn 0.2s;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.extracted-label { 
  color: #64748b; 
  font-weight: 600; 
  display: block; 
  margin-bottom: 6px; 
  font-size: 12px;
}
.extracted-text { 
  color: #475569; 
  word-break: break-all; 
  font-size: 14px;
  line-height: 1.7;
}

/* 搜索状态样式 */
.search-status {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}
.search-status-searching {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f0f9ff;
  color: #0369a1;
}
.search-status-completed {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f0fdf4;
  color: #059669;
}
.search-spinner {
  animation: spin 1s linear infinite;
}

/* 折叠面板通用样式（工具调用结果 + 深度思考过程共用） */
.collapsible-panel {
  margin-top: 12px;
  border-radius: 10px;
  overflow: hidden;
}
.collapsible-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.15s;
}
.collapsible-title {
  flex: 1;
}
.collapsible-chevron {
  transition: transform 0.2s;
}
.collapsible-chevron.collapsed {
  transform: rotate(-90deg);
}
.collapsible-body {
  padding: 0 14px 12px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  padding-top: 10px;
}

/* 工具调用结果面板：蓝色系 */
.tools-panel {
  background: #eff6ff;
  border-left: 3px solid #3b82f6;
}
.tools-panel .collapsible-header {
  color: #2563eb;
}
.tools-panel .collapsible-header:hover {
  background: rgba(59, 130, 246, 0.08);
}
.tools-panel .collapsible-body {
  border-top-color: rgba(59, 130, 246, 0.2);
}

/* 深度思考面板：琥珀色系 */
.reasoning-panel {
  background: #fef3c7;
  border-left: 3px solid #f59e0b;
}
.reasoning-panel .collapsible-header {
  color: #d97706;
}
.reasoning-panel .collapsible-header:hover {
  background: rgba(245, 158, 11, 0.08);
}
.reasoning-panel .collapsible-body {
  border-top-color: rgba(245, 158, 11, 0.2);
}

.thinking-spinner {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 步骤列表样式 */
.thinking-step {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #f0f7ff;
  border-radius: 8px;
  border: 1px solid rgba(59, 130, 246, 0.12);
}
.thinking-step:last-child {
  margin-bottom: 0;
}
.thinking-step-header {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.thinking-step-num {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #3b82f6;
  color: white;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
}
.thinking-step-content {
  flex: 1;
  min-width: 0;
}
.thinking-step-analysis {
  color: #1e3a5f;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking-step-purpose {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  font-style: italic;
}
.thinking-step-tools {
  margin-top: 8px;
  padding-left: 32px;
}
.tool-summary {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #64748b;
  margin-right: 14px;
  margin-bottom: 4px;
}
.tool-summary svg {
  opacity: 0.7;
}
.tool-summary.tool-running {
  color: #3b82f6;
  animation: pulse 1.5s ease-in-out infinite;
}
.tool-summary.tool-error {
  color: #ef4444;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
/* 工具项容器（小折叠栏） */
.tool-collapsible {
  margin-bottom: 6px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.5);
  overflow: hidden;
}
.tool-collapsible .tool-summary {
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s;
}
.tool-collapsible .tool-summary:hover {
  background: rgba(59, 130, 246, 0.06);
}
/* 小折叠栏箭头 */
.tool-chevron {
  transition: transform 0.2s;
  margin-left: auto;
}
.tool-chevron.collapsed {
  transform: rotate(-90deg);
}
/* 搜索结果超链接列表 */
.search-links-list {
  margin-top: 4px;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.search-link-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #2563eb;
  text-decoration: none;
  line-height: 1.4;
  word-break: break-all;
  transition: color 0.15s;
}
.search-link-item:hover {
  color: #1d4ed8;
  text-decoration: underline;
}
.search-link-item svg {
  flex-shrink: 0;
  opacity: 0.6;
}
.reasoning-content {
  color: #78350f;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.chat-input-area {
  background-color: white;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.06);
}

.pending-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px 0 24px;
  font-size: 13px;
}
.pending-label {
  background-color: #e0e7ff;
  color: #6366f1;
  padding: 8px 14px;
  border-radius: 16px;
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
  color: #94a3b8;
  cursor: pointer;
  font-size: 18px;
  padding: 4px;
  line-height: 1;
  border-radius: 6px;
  transition: all 0.2s;
}
.pending-remove:hover { 
  color: #ef4444; 
  background-color: #fef2f2;
}
.pending-medias {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.pending-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pending-clear-all {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #ef4444;
  padding: 8px 14px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}
.pending-clear-all:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
  max-width: 360px;
}
.media-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-input {
  padding: 16px 24px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.input-tools { display: flex; align-items: center; gap: 8px; }
.tool-input { display: none; }
.tool-btn-wrapper {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-btn {
  width: 44px;
  height: 44px;
  border: none;
  background-color: #f1f5f9;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s;
  color: #64748b;
}
.tool-btn:hover:not(.disabled):not(:disabled) { 
  background-color: #e0e7ff;
  color: #6366f1;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}
.tool-btn.disabled, .tool-btn:disabled { 
  opacity: 0.4; 
  cursor: not-allowed; 
}
.tool-btn.recording {
  background-color: #ef4444;
  color: white;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  50% { transform: scale(1.05); box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
  100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

.recording-time { 
  font-size: 12px; 
  color: #ef4444; 
  white-space: nowrap;
  font-weight: 600;
}

.input-field {
  flex: 1;
  padding: 14px 20px;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  font-size: 15px;
  background-color: #fafafa;
  transition: all 0.25s;
}
.input-field:focus { 
  outline: none; 
  border-color: #6366f1; 
  background-color: white;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
}
.input-field:disabled { 
  background-color: #f1f5f9; 
  color: #94a3b8;
}

.send-btn {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  border: none;
  padding: 14px 32px;
  border-radius: 16px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  transition: all 0.3s;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}
.send-btn:hover:not(:disabled) { 
  opacity: 0.95; 
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45);
}
.send-btn:disabled { 
  opacity: 0.5; 
  cursor: not-allowed; 
}

.confirm-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.2s;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: white;
  border-radius: 20px;
  width: 420px;
  max-width: 90%;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  animation: slideUp 0.3s;
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.modal-header {
  padding: 24px;
  border-bottom: 1px solid #f1f5f9;
}
.modal-header h3 {
  margin: 0;
  font-size: 20px;
  color: #1e293b;
}

.modal-body {
  padding: 24px;
}
.modal-body p {
  margin: 0;
  color: #64748b;
  font-size: 15px;
  line-height: 1.7;
}

.modal-footer {
  padding: 20px 24px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  padding: 12px 28px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  background: white;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s;
}
.btn-cancel:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.btn-confirm {
  padding: 12px 28px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
}
.btn-confirm:hover {
  opacity: 0.95;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(239, 68, 68, 0.4);
}

.image-preview-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  animation: fadeIn 0.2s;
}

.preview-content {
  position: relative;
  max-width: 90%;
  max-height: 90%;
  padding: 20px;
}

.preview-close {
  position: absolute;
  top: -40px;
  right: 0;
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  font-size: 28px;
  cursor: pointer;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.preview-close:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.1);
}

.preview-image {
  max-width: 100%;
  max-height: 80vh;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
</style>