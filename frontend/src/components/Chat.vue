<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const messages = ref([
  { type: 'system', content: '欢迎使用XiaoAi，发送消息开始聊天' }
])

const inputMessage = ref('')
const isLoading = ref(false)
const isLoadingMore = ref(false)
const hasMore = ref(true)
const pageNum = ref(1)
const pageSize = ref(20)
const chatContainer = ref(null)

const loadMessages = async (page = 1) => {
  if (isLoadingMore.value) return
  
  isLoadingMore.value = true
  
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/session/messages/page?sessionId=1&pageNum=${page}&pageSize=${pageSize.value}`, {
      headers: {
        'Authorization': token || ''
      }
    })
    
    if (response.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      router.push('/')
      return
    }
    
    const data = await response.json()
    
    if (data.code === 200 && data.data) {
      const newMessages = data.data.messages || []
      
      const formattedMessages = newMessages.map(msg => ({
        type: msg.role === 'user' ? 'user' : 'bot',
        content: msg.content
      }))
      
      if (page === 1) {
        messages.value = [...formattedMessages.reverse()]
      } else {
        messages.value = [...formattedMessages.reverse(), ...messages.value]
      }
      
      hasMore.value = data.data.hasNext || false
      pageNum.value = page
    }
  } catch (error) {
    console.error('加载消息失败:', error)
  } finally {
    isLoadingMore.value = false
  }
}

const handleScroll = async () => {
  const container = chatContainer.value
  if (!container || isLoadingMore.value) return
  
  if (container.scrollTop < 50 && hasMore.value) {
    await loadMessages(pageNum.value + 1)
  }
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

onMounted(async () => {
  await loadMessages(1)
})
</script>

<template>
  <div class="chat-container" ref="chatContainer" @scroll="handleScroll">
    <div v-if="isLoadingMore && messages.length > 1" class="loading-more">
      加载中...
    </div>
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
      <el-input 
        v-model="inputMessage" 
        placeholder="输入消息..."
        @keyup.enter="sendMessage"
        class="input-field"
        :disabled="isLoading"
      />
      <el-button type="primary" @click="sendMessage" class="send-btn" :loading="isLoading">
        {{ isLoading ? '发送中' : '发送' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
  overflow: hidden;
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
  box-shadow: 0 -2px 4px rgba(0, 0, 0, 0.05);
}

.input-field {
  flex: 1;
}

.send-btn {
  width: 80px;
}
</style>