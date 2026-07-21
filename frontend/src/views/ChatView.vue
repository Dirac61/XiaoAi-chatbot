<script setup>import { nextTick, onMounted, ref, reactive, watch } from 'vue';
import { useRouter } from 'vue-router';
import service from '../api/index.js';
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
const previewImage = ref(null);
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
 const formattedMessages = newMessages.map(msg => ({
 type: msg.role === 'user' ? 'user' : 'bot',
 content: msg.content,
 messageType: msg.messageType || 'TEXT',
 mediaUrl: msg.mediaUrl,
 mediaUrls: msg.mediaUrls,
 fileNames: msg.fileNames,
 extractedText: msg.extractedText,
 searchResults: msg.searchResults
 }));
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
  const botMessageIndex = messages.value.push({ type: 'bot', content: '', searchResults: null }) - 1;
  isLoading.value = true;
  scrollToBottom();
  try {
    const token = localStorage.getItem('token');
    const requestBody = {
      message: hasPending ? (capturedText || finalFileNames.join(', ')) : capturedText,
      messageType: capturedType,
      sessionId: currentSessionId.value
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
 try {
 while (true) {
 const { done, value } = await reader.read();
 if (done)
 break;
 lineBuffer += decoder.decode(value, { stream: true });
 let newlineIdx;
 while ((newlineIdx = lineBuffer.indexOf('\n')) >= 0) {
 const line = lineBuffer.substring(0, newlineIdx).trim();
 lineBuffer = lineBuffer.substring(newlineIdx + 1);
 if (!line)
 continue;
 if (line.startsWith('{')) {
 try {
 const jsonChunk = JSON.parse(line);
 if (jsonChunk.type === 'content') {
 messages.value[botMessageIndex].content += jsonChunk.data;
 }
 else if (jsonChunk.type === 'search_results') {
 messages.value[botMessageIndex].searchResults = JSON.stringify(jsonChunk.data);
 }
 }
 catch (e) {
 messages.value[botMessageIndex].content += line;
 }
 }
 else {
 messages.value[botMessageIndex].content += line;
 }
 scrollToBottom();
 }
 }
 const remaining = lineBuffer.trim();
 if (remaining) {
 if (remaining.startsWith('{')) {
 try {
 const jsonChunk = JSON.parse(remaining);
 if (jsonChunk.type === 'content') {
 messages.value[botMessageIndex].content += jsonChunk.data;
 }
 else if (jsonChunk.type === 'search_results') {
 messages.value[botMessageIndex].searchResults = JSON.stringify(jsonChunk.data);
 }
 }
 catch (e) {
 messages.value[botMessageIndex].content += remaining;
 }
 }
 else {
 messages.value[botMessageIndex].content += remaining;
 }
 }
 } finally {
 reader.releaseLock();
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
                <span class="message-text">{{ msg.content }}</span>
                <div v-if="msg.searchResults && getSearchResults(msg.searchResults).length > 0" class="search-container">
                  <button class="search-toggle" @click="toggleSearch(index)">
                    <svg v-if="!expandedSearch[index]" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="11" cy="11" r="8"/>
                      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="6" x2="6" y2="18"/>
                      <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                    <span>{{ expandedSearch[index] ? '收起搜索结果' : '查看搜索结果' }}</span>
                  </button>
                  <div v-if="expandedSearch[index]" class="search-content-box">
                    <span class="search-label">【搜索结果】</span>
                    <div class="search-list">
                      <a v-for="(result, idx) in getSearchResults(msg.searchResults)" :key="idx" :href="result.url" target="_blank" class="search-item">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                          <polyline points="16 18 22 12 16 6"/>
                          <line x1="22" y1="12" x2="10" y2="12"/>
                        </svg>
                        <div class="search-item-content">
                          <span class="search-item-title">{{ result.title }}</span>
                          <span class="search-item-url">{{ result.url }}</span>
                        </div>
                      </a>
                    </div>
                  </div>
                </div>
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

.search-container {
  margin-top: 12px;
}
.search-toggle {
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
.search-toggle:hover {
  background: #e2e8f0;
  color: #334155;
}
.search-content-box {
  margin-top: 8px;
  padding: 14px;
  background-color: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  animation: fadeIn 0.2s;
}
.search-label { 
  color: #64748b; 
  font-weight: 600; 
  display: block; 
  margin-bottom: 10px; 
  font-size: 12px;
}
.search-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.search-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: white;
  border-radius: 8px;
  text-decoration: none;
  color: #3b82f6;
  font-size: 14px;
  transition: all 0.2s;
  border: 1px solid #e2e8f0;
}
.search-item:hover {
  background: #dbeafe;
  border-color: #3b82f6;
  transform: translateX(4px);
}
.search-item-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.search-item-title {
  font-weight: 600;
  color: #1e40af;
  font-size: 14px;
}
.search-item-url {
  font-size: 12px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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