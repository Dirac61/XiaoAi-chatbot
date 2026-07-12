import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Login',
    component: () => import('../views/Login.vue')
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue')
  },
  {
    path: '/test',
    name: 'Test',
    component: () => import('../views/TestPage.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router