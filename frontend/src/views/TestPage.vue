<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const goToChat = () => {
  localStorage.setItem('token', 'test-token')
  localStorage.setItem('username', 'test-user')
  router.push('/chat')
}
</script>

<template>
  <div style="padding: 50px;">
    <h1>测试页面</h1>
    <p>Token: {{ localStorage.getItem('token') }}</p>
    <p>Username: {{ localStorage.getItem('username') }}</p>
    <button @click="goToChat">Go to Chat</button>
    <button @click="router.push('/')">Go to Login</button>
  </div>
</template>