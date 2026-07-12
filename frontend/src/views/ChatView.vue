<script setup>import { onMounted, ref } from 'vue';
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
 headers: {
 'Authorization': token || ''
 }
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
 if (!currentSessionId.value || isLoadingMore.value) return;
 
 isLoadingMore.value = true;
 
 try {
 const token = localStorage.getItem('token');
 const response = await fetch(`/api/session/messages/page?sessionId=${currentSessionId.value}&pageNum=${page}&pageSize=${pageSize.value}`, {
 headers: {
 'Authorization': token || ''
 }
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
 content: msg.content
 }));
 
 if (page === 1) {
 messages.value = [...formattedMessages.reverse()];
 } else {
 messages.value = [...formattedMessages.reverse(), ...messages.value];
 }
 
 hasMore.value = data.data.hasNext || false;
 pageNum.value = page;
 }
 } catch (error) {
 console.error('加载消息失败:', error);
 } finally {
 isLoadingMore.value = false;
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
 if (!container || isLoadingMore.value) return;
 
 if (container.scrollTop < 50 && hasMore.value) {
 await loadMessages(pageNum.value + 1);
 }
};
const handleLogout = () => {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
};
const sendMessage = async () => {
 if (!inputMessage.value.trim() || isLoading.value)
 return;
 messages.value.push({
 type: 'user',
 content: inputMessage.value
 });
 const botMessageIndex = messages.value.push({
 type: 'bot',
 content: ''
 }) - 1;
 inputMessage.value = '';
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
 message: messages.value[messages.value.length - 2].content,
 sessionId: currentSessionId.value
 })
 });
 if (response.status === 401) {
 localStorage.removeItem('token');
 localStorage.removeItem('username');
 router.push('/');
 return;
 }
 if (!response.ok) {
 throw new Error('请求失败');
 }
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
 let chunk = decoder.decode(value, { stream: true });
 messages.value[botMessageIndex].content += chunk;
 }
 }
 catch (error) {
 messages.value[botMessageIndex].content = `请求失败: ${error.message}`;
 }
 finally {
 isLoading.value = false;
 }
};
</script>

<template>
  <div class="chat-layout">
    <header class="chat-header">
      <div class="header-left">
        <button class="sidebar-toggle" @click="sidebarOpen = !sidebarOpen">
          ☰
        </button>
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
          <button class="new-session-btn" @click="createNewSession">
            + 新建会话
          </button>
        </div>
        <div class="session-list">
          <div 
            v-for="session in sessions" 
            :key="session.id"
            :class="['session-item', { active: currentSessionId === session.id }]"
            @click="selectSession(session)"
          >
            <span class="session-icon">💬</span>
            <span class="session-id">{{ session.id }}</span>
          </div>
        </div>
      </aside>
      
      <div class="chat-content">
        <div v-if="isLoadingMore && messages.length > 1" class="loading-more">
          加载中...
        </div>
        <div class="chat-messages" ref="chatContainer" @scroll="handleScroll">
          <div 
            v-for="(msg, index) in messages" 
            :key="index"
            :class="['message', msg.type]"
          >
            <span class="message-content">{{ msg.content }}</span>
          </div>
        </div>
        <div class="chat-input">
          <input 
            type="text" 
            v-model="inputMessage"
            placeholder="输入消息..." 
            class="input-field"
            @keyup.enter="sendMessage"
          />
          <button class="send-btn" :disabled="isLoading" @click="sendMessage">
            {{ isLoading ? '发送中' : '发送' }}
          </button>
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
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sidebar-toggle {
  background: none;
  border: none;
  color: white;
  font-size: 20px;
  cursor: pointer;
  padding: 4px 8px;
}

.logo {
  font-size: 24px;
}

.title {
  font-size: 18px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.username {
  font-size: 14px;
  opacity: 0.9;
}

.logout-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.3s;
}

.logout-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.chat-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.sidebar {
  width: 250px;
  background-color: #fff;
  border-right: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  transition: width 0.3s;
}

.sidebar.closed {
  width: 60px;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e8e8e8;
}

.sidebar.closed .sidebar-header {
  padding: 16px 8px;
}

.new-session-btn {
  width: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.3s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.sidebar.closed .new-session-btn {
  padding: 10px;
  font-size: 18px;
}

.new-session-btn:hover {
  opacity: 0.9;
}

.sidebar.closed .new-session-btn span {
  display: none;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.session-item:hover {
  background-color: #f5f7fa;
}

.session-item.active {
  background-color: #e8f0fe;
}

.sidebar.closed .session-item {
  justify-content: center;
  padding: 12px 8px;
}

.session-icon {
  font-size: 16px;
}

.session-id {
  font-size: 13px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar.closed .session-id {
  display: none;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
}

.loading-more {
  text-align: center;
  padding: 10px;
  color: #999;
  font-size: 14px;
}

.chat-messages {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.message {
  margin-bottom: 15px;
  display: flex;
}

.message.user {
  justify-content: flex-end;
}

.message.user .message-content {
  background-color: #409eff;
  color: white;
  border-radius: 15px 15px 0 15px;
}

.message.bot .message-content {
  background-color: white;
  color: #333;
  border-radius: 15px 15px 15px 0;
}

.message.system .message-content {
  background-color: #f0f0f0;
  color: #666;
  border-radius: 8px;
  text-align: center;
}

.message-content {
  max-width: 70%;
  padding: 12px 18px;
  font-size: 14px;
  line-height: 1.5;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.chat-input {
  padding: 15px 20px;
  background-color: white;
  display: flex;
  gap: 10px;
}

.input-field {
  flex: 1;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
}

.input-field:focus {
  outline: none;
  border-color: #667eea;
}

.send-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: opacity 0.3s;
}

.send-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.send-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>