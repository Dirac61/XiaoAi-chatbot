<script setup>
import { ref } from 'vue'

const messages = ref([
  { type: 'system', content: '欢迎使用XiaoAi，发送消息开始聊天' }
])

const inputMessage = ref('')
const isLoading = ref(false)

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
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ message: messages.value[messages.value.length - 2].content })
    })
    
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
  <div class="chat-container">
    <div class="chat-header">
      <h2>XiaoAi 聊天</h2>
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
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
}

.chat-header {
  padding: 20px;
  background-color: #409eff;
  color: white;
  text-align: center;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.chat-header h2 {
  margin: 0;
  font-size: 24px;
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