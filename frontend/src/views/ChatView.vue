<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const currentUser = ref('')
const messages = ref([
  { type: 'system', content: '欢迎使用小爱，发送消息开始聊天' }
])
const inputMessage = ref('')
const isLoading = ref(false)

onMounted(() => {
  const token = localStorage.getItem('token')
  const username = localStorage.getItem('username')
  currentUser.value = username || ''
  
  if (!token) {
    router.push('/')
  }
})

const handleLogout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/')
}

const sendMessage = async () => {
  if (!inputMessage.value.trim() || isLoading.value) return
  
  messages.value.push({
    type: 'user',
    content: inputMessage.value
  })
  
  const botMessageIndex = messages.value.push({
    type: 'bot',
    content: ''
  }) - 1
  
  inputMessage.value = ''
  isLoading.value = true
  
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': token || ''
      },
      body: JSON.stringify({ message: messages.value[messages.value.length - 2].content })
    })
    
    if (response.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      router.push('/')
      return
    }
    
    if (!response.ok) {
      throw new Error('请求失败')
    }
    
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      let chunk = decoder.decode(value, { stream: true })
      messages.value[botMessageIndex].content += chunk
    }
  } catch (error) {
    messages.value[botMessageIndex].content = `请求失败: ${error.message}`
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="chat-layout">
    <header class="chat-header">
      <div class="header-left">
        <span class="logo">🤖</span>
        <span class="title">小爱</span>
      </div>
      <div class="header-right">
        <span class="username">{{ currentUser }}</span>
        <button class="logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </header>
    <div class="chat-content">
      <div class="chat-messages">
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

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
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