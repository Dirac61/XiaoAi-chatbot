<script setup>import { nextTick, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
const router = useRouter();
const currentUser = ref('');
const messages = ref([
 { type: 'system', content: '欢迎使用小爱，发送消息开始聊天' }
]);
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
const showDeleteConfirm = ref(false);
const sessionToDelete = ref(null);
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
 const response = await fetch('/api/sessions', {
 headers: { 'Authorization': token || '' }
 });
 if (response.status === 401) {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
 return;
 }
 const data = await response.json();
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
 const response = await fetch('/api/session/new', {
 method: 'POST',
 headers: {
 'Content-Type': 'application/json',
 'Authorization': token || ''
 }
 });
 const data = await response.json();
 if (data.code === 200) {
 currentSessionId.value = data.data.sessionId;
 messages.value = [{ type: 'system', content: '欢迎使用小爱，发送消息开始聊天' }];
 await loadSessions();
 }
 } catch (error) {
 console.error('创建会话失败:', error);
 }
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
 const response = await fetch(`/api/session/messages/page?sessionId=${currentSessionId.value}&pageNum=${page}&pageSize=${pageSize.value}`, {
 headers: { 'Authorization': token || '' }
 });
 if (response.status === 401) {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
 return;
 }
 const data = await response.json();
 if (data.code === 200 && data.data) {
 const newMessages = data.data.messages || [];
 const formattedMessages = newMessages.map(msg => ({
 type: msg.role === 'user' ? 'user' : 'bot',
 content: msg.content,
 messageType: msg.messageType || 'TEXT',
 mediaUrl: msg.mediaUrl,
 extractedText: msg.extractedText
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
 if (page > 1 && container) {
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
 const response = await fetch(`/api/session/delete/${sessionId}`, {
 method: 'DELETE',
 headers: { 'Authorization': token || '' }
 });
 const data = await response.json();
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
const sendMessage = async () => {
 const hasPending = pendingMedia.value !== null;
 const textContent = inputMessage.value.trim();
 if (!textContent && !hasPending)
 return;
 if (isLoading.value)
 return;
 const finalMessageType = hasPending ? pendingMedia.value.type : 'TEXT';
 const finalMediaUrl = hasPending ? pendingMedia.value.url : null;
 const finalFileName = hasPending ? pendingMedia.value.name : null;
 const displayContent = finalFileName
 ? (textContent ? textContent : '')
 : textContent;
 const capturedType = finalMessageType;
 const capturedUrl = finalMediaUrl;
 const capturedText = textContent;
 inputMessage.value = '';
 pendingMedia.value = null;
 messages.value.push({
 type: 'user',
 content: displayContent,
 messageType: capturedType,
 mediaUrl: capturedUrl,
 fileName: finalFileName
 });
 const botMessageIndex = messages.value.push({ type: 'bot', content: '' }) - 1;
 isLoading.value = true;
 try {
 const token = localStorage.getItem('token');
 const response = await fetch('/api/chat', {
 method: 'POST',
 headers: {
 'Content-Type': 'application/json',
 'Authorization': token || ''
 },
 body: JSON.stringify({
 message: finalFileName ? (capturedText || finalFileName) : capturedText,
 messageType: capturedType,
 mediaUrl: capturedUrl,
 sessionId: currentSessionId.value
 })
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
 while (true) {
 const { done, value } = await reader.read();
 if (done)
 break;
 messages.value[botMessageIndex].content += decoder.decode(value, { stream: true });
 }
 }
 catch (error) {
 messages.value[botMessageIndex].content = `请求失败: ${error.message}`;
 }
 finally {
 isLoading.value = false;
 }
};
const uploadFile = async (type, file) => {
 if (isLoading.value)
 return;
 const maxSize = type === 'image' ? MAX_IMAGE_SIZE : MAX_FILE_SIZE;
 if (file.size > maxSize) {
 alert(`${type === 'image' ? '图片' : '文件'}大小超过限制（最大${type === 'image' ? '10MB' : '50MB'}）`);
 return;
 }
 try {
 const token = localStorage.getItem('token');
 const formData = new FormData();
 formData.append('file', file);
 const response = await fetch(`/api/upload/${type}`, {
 method: 'POST',
 headers: { 'Authorization': token || '' },
 body: formData
 });
 const data = await response.json();
 if (data.code === 200) {
 pendingMedia.value = {
 type: type === 'image' ? 'IMAGE' : 'FILE',
 url: data.data,
 name: file.name
 };
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
const removePendingMedia = () => {
 pendingMedia.value = null;
};
const handleImageUpload = (event) => {
 const file = event.target.files[0];
 if (file)
 uploadFile('image', file);
 event.target.value = '';
};
const handleFileUpload = (event) => {
 const file = event.target.files[0];
 if (file)
 uploadFile('file', file);
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
 const response = await fetch('/api/speech-to-text', {
 method: 'POST',
 headers: { 'Authorization': token || '' },
 body: formData
 });
 const data = await response.json();
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
                <div v-if="msg.messageType === 'IMAGE' && msg.mediaUrl" class="media-section">
                  <div class="image-wrapper">
                    <img :src="msg.mediaUrl" alt="图片" class="message-image" />
                  </div>
                </div>
                <div v-if="msg.messageType === 'FILE' && msg.mediaUrl" class="media-section">
                  <a :href="msg.mediaUrl" target="_blank" class="file-card">
                    <div class="file-icon">📄</div>
                    <div class="file-info">
                      <span class="file-name">{{ msg.fileName || msg.content }}</span>
                    </div>
                  </a>
                </div>
                <span v-if="msg.content" class="message-text">{{ msg.content }}</span>
                <span v-if="msg.extractedText" class="extracted-text">
                  <span class="extracted-label">【提取内容】</span>
                  <span class="extracted-content">{{ msg.extractedText }}</span>
                </span>
              </template>

              <template v-else>
                <span class="message-text">{{ msg.content }}</span>
              </template>
            </div>
          </div>
        </div>

        <div class="chat-input-area">
          <div v-if="pendingMedia" class="pending-preview">
            <span class="pending-label">
              <template v-if="pendingMedia.type === 'IMAGE'">🖼️</template>
              <template v-else>📎</template>
              {{ pendingMedia.name }}
            </span>
            <button class="pending-remove" @click="removePendingMedia">✕</button>
          </div>

          <div class="chat-input">
            <div class="input-tools">
              <input type="file" accept="image/*" class="tool-input" id="image-input" @change="handleImageUpload" />
              <label for="image-input" class="tool-btn" :class="{ disabled: isLoading }">🖼️</label>

              <input type="file" class="tool-input" id="file-input" @change="handleFileUpload" />
              <label for="file-input" class="tool-btn" :class="{ disabled: isLoading }">📎</label>

              <button class="tool-btn" :class="{ recording: isRecording }" :disabled="isLoading"
                @click="isRecording ? stopRecording() : startRecording()">
                {{ isRecording ? '⏹️' : '🎤' }}
              </button>
              <span v-if="isRecording" class="recording-time">{{ recordingTime }}s</span>
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
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  background-color: #f0f2f5;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
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
  padding: 6px 10px;
  border-radius: 6px;
  transition: background 0.2s;
}
.sidebar-toggle:hover { background: rgba(255, 255, 255, 0.25); }
.logo { font-size: 28px; }
.title { font-size: 20px; font-weight: 700; letter-spacing: 1px; }

.header-right { display: flex; align-items: center; gap: 16px; }
.username { font-size: 14px; opacity: 0.9; background: rgba(255, 255, 255, 0.15); padding: 4px 12px; border-radius: 12px; }

.logout-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
}
.logout-btn:hover { background: rgba(255, 255, 255, 0.3); transform: translateY(-1px); }

.chat-body { flex: 1; display: flex; overflow: hidden; }

.sidebar {
  width: 260px;
  background-color: white;
  border-right: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.05);
}
.sidebar.closed { width: 64px; }
.sidebar-header { padding: 16px; border-bottom: 1px solid #f0f0f0; }
.sidebar.closed .sidebar-header { padding: 16px 8px; }

.new-session-btn {
  width: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}
.new-session-btn:hover { 
  opacity: 0.9; 
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.session-item:hover { 
  background-color: #f5f7fa;
  transform: translateX(2px);
}
.session-item.active { 
  background-color: #e8f0fe;
  box-shadow: 0 2px 4px rgba(64, 158, 255, 0.15);
}
.sidebar.closed .session-item { justify-content: center; padding: 12px 8px; }
.session-icon { font-size: 18px; }
.session-title {
  flex: 1;
  font-size: 14px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sidebar.closed .session-title { display: none; }

.session-delete {
  opacity: 0;
  visibility: hidden;
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}
.session-item:hover .session-delete {
  opacity: 1;
  visibility: visible;
}
.session-delete:hover {
  color: #f56c6c;
  background-color: #fef0f0;
}
.sidebar.closed .session-delete { display: none; }

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
}

.loading-more { text-align: center; padding: 10px; color: #999; font-size: 14px; }
.chat-messages { flex: 1; padding: 24px; overflow-y: auto; }

.message { margin-bottom: 20px; display: flex; }
.message.user { justify-content: flex-end; }
.message.user .message-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 18px 18px 4px 18px;
}
.message.user .file-card {
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.message.user .file-name { color: white; }
.message.user .file-icon { background: rgba(255, 255, 255, 0.2); }
.message.user .extracted-text {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
}
.message.user .extracted-label { color: rgba(255, 255, 255, 0.8); }
.message.user .extracted-content { color: white; }
.message.bot .message-bubble {
  background-color: white;
  color: #333;
  border-radius: 18px 18px 18px 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.message.system .message-bubble {
  background-color: #f0f0f0;
  color: #666;
  border-radius: 8px;
  text-align: center;
}
.message-bubble {
  max-width: 70%;
  padding: 14px 18px;
  font-size: 15px;
  line-height: 1.6;
}

.system-message {
  font-size: 13px;
  color: #999;
}

.media-section {
  margin-bottom: 10px;
}

.image-wrapper {
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  max-width: 300px;
}
.message-image {
  max-width: 100%;
  max-height: 300px;
  display: block;
  object-fit: cover;
}

.file-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 10px;
  text-decoration: none;
  transition: all 0.2s;
  border: 1px solid #e8e8e8;
}
.file-card:hover {
  background: #e8f0fe;
  border-color: #409eff;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.15);
}
.file-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e8f0fe;
  border-radius: 8px;
  font-size: 20px;
}
.file-info { flex: 1; }
.file-name {
  font-size: 14px;
  color: #333;
  font-weight: 500;
}

.message-text { display: block; word-break: break-all; }

.extracted-text { 
  display: block; 
  margin: 10px 0 0 0; 
  padding: 10px 14px; 
  background-color: #f5f7fa; 
  border-radius: 8px; 
  font-size: 13px; 
  line-height: 1.6; 
  border: 1px solid #e8e8e8;
}
.extracted-label { 
  color: #666; 
  font-weight: 600; 
  display: block; 
  margin-bottom: 4px; 
  font-size: 12px;
}
.extracted-content { 
  color: #444; 
  word-break: break-all; 
}

.chat-input-area {
  background-color: white;
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.06);
}

.pending-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 24px 0 24px;
  font-size: 13px;
}
.pending-label {
  background-color: #e8f0fe;
  color: #409eff;
  padding: 6px 12px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.pending-remove {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 16px;
  padding: 2px;
  line-height: 1;
  border-radius: 4px;
  transition: all 0.2s;
}
.pending-remove:hover { 
  color: #f56c6c; 
  background-color: #fef0f0;
}

.chat-input {
  padding: 12px 24px 18px 24px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.input-tools { display: flex; align-items: center; gap: 6px; }
.tool-input { display: none; }

.tool-btn {
  width: 40px;
  height: 40px;
  border: none;
  background-color: #f5f7fa;
  border-radius: 8px;
  cursor: pointer;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.tool-btn:hover:not(.disabled):not(:disabled) { 
  background-color: #e4e7ed;
  transform: translateY(-1px);
}
.tool-btn.disabled, .tool-btn:disabled { 
  opacity: 0.5; 
  cursor: not-allowed; 
}
.tool-btn.recording {
  background-color: #f56c6c;
  color: white;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4); }
  50% { transform: scale(1.05); box-shadow: 0 0 0 6px rgba(245, 108, 108, 0); }
  100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(245, 108, 108, 0); }
}

.recording-time { 
  font-size: 12px; 
  color: #f56c6c; 
  white-space: nowrap;
  font-weight: 600;
  margin-left: 4px;
}

.input-field {
  flex: 1;
  padding: 14px 18px;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  font-size: 15px;
  background-color: #fafafa;
  transition: all 0.2s;
}
.input-field:focus { 
  outline: none; 
  border-color: #667eea; 
  background-color: white;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}
.input-field:disabled { 
  background-color: #f0f0f0; 
  color: #999;
}

.send-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 14px 28px;
  border-radius: 12px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: all 0.3s;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}
.send-btn:hover:not(:disabled) { 
  opacity: 0.9; 
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}
.send-btn:disabled { 
  opacity: 0.6; 
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
  border-radius: 16px;
  width: 400px;
  max-width: 90%;
  overflow: hidden;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  animation: slideUp 0.3s;
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid #f0f0f0;
}
.modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: #333;
}

.modal-body {
  padding: 24px;
}
.modal-body p {
  margin: 0;
  color: #666;
  font-size: 15px;
  line-height: 1.6;
}

.modal-footer {
  padding: 16px 24px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  padding: 10px 24px;
  border: 1px solid #d9d9d9;
  border-radius: 8px;
  background: white;
  color: #666;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-cancel:hover {
  background: #f5f5f5;
  border-color: #ccc;
}

.btn-confirm {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #f56c6c 0%, #ee4d4d 100%);
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-confirm:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
</style>