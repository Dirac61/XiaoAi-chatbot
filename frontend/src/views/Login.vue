<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import service from '../api/index.js'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

/* 登录：失败信息统一显示在卡片内，保持月夜氛围（不再走 alert） */
const handleLogin = async () => {
  if (!username.value || !password.value) {
    errorMessage.value = '请输入用户名与密码'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await service.post('/login', {
      username: username.value,
      password: password.value,
    })
    if (data.code === 200) {
      localStorage.setItem('token', data.data.token)
      localStorage.setItem('username', data.data.username)
      // 短暂延迟让「按钮涟漪 + 成功高亮」被用户看到
      setTimeout(() => router.push('/chat'), 260)
    } else {
      errorMessage.value = data.message || '登录失败，请检查用户名或密码'
    }
  } catch (error) {
    errorMessage.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-container">
    <!-- 装饰：真祖红色剪影月亮（左低右高，对应月相斜切） -->
    <div class="moon-deco moon-deco--a" aria-hidden="true"></div>
    <div class="moon-deco moon-deco--b" aria-hidden="true"></div>
    <div class="moon-deco moon-deco--c" aria-hidden="true"></div>

    <div class="login-card">
      <!-- LOGO：角色徽章（圆形 + 月华） -->
      <div class="brand">
        <div class="brand-mark">
          <span class="brand-mark__glyph">𝔄</span>
          <span class="brand-mark__pupil"></span>
        </div>
        <div class="brand-name">
          <div class="brand-title">小爱</div>
          <div class="brand-subtitle">Princess of the True Ancestors · 真祖月下</div>
        </div>
      </div>

      <form @submit.prevent="handleLogin" class="login-form" novalidate>
        <div class="field">
          <label for="username" class="field__label">
            <span class="field__glyph">§</span>
            <span>用户名</span>
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            placeholder="请输入您的名字…"
            class="field__input"
            autocomplete="username"
          />
        </div>

        <div class="field">
          <label for="password" class="field__label">
            <span class="field__glyph">✦</span>
            <span>密码</span>
          </label>
          <input
            id="password"
            v-model="password"
            type="password"
            placeholder="今夜之钥…"
            class="field__input"
            autocomplete="current-password"
          />
        </div>

        <!-- 错误提示：朱砂色文字 + 玻璃条 -->
        <transition name="error-fade">
          <div v-if="errorMessage" class="error-tip">
            <span class="error-tip__dot"></span>
            <span>{{ errorMessage }}</span>
          </div>
        </transition>

        <!-- 登录按钮：朱砂→月光渐变，点击涟漪 + 磁性（CSS + 全局 ripple 机制） -->
        <button
          type="submit"
          :disabled="loading"
          class="submit-btn magent"
          data-ripple="true"
        >
          <span class="submit-btn__shine" aria-hidden="true"></span>
          <span v-if="loading" class="submit-btn__loading"></span>
          <span class="submit-btn__label">
            {{ loading ? '进入夜幕…' : '踏入月下' }}
          </span>
        </button>
      </form>

      <p class="tips">首次登录将自动注册 · 月光见证你的名字</p>
    </div>
  </div>
</template>

<style scoped>
/* =============================================================
 * Login —「哥特月夜 · 登录」
 * 左中右三层月相装饰 + 居中玻璃卡片 + 朱砂按钮
 * 所有装饰层 pointer-events:none，表单不被遮挡
 * ============================================================= */
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  position: relative;
  overflow: hidden;
}

/* 三层"月相"装饰（左：真朱红瞳切月、中：满月辉光、右：残月） */
.moon-deco {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  filter: blur(2px);
  mix-blend-mode: screen;
  opacity: 0.82;
}
.moon-deco--a {
  width: 420px; height: 420px;
  left: -140px; top: 12%;
  background:
    radial-gradient(circle at 30% 30%, rgba(231,230,255,0.60), rgba(169,156,255,0.28) 45%, transparent 70%);
  animation: floatA 18s ease-in-out infinite alternate;
}
.moon-deco--b {
  width: 360px; height: 360px;
  right: -120px; bottom: -80px;
  background:
    radial-gradient(circle at 40% 60%, rgba(200,16,46,0.55), rgba(200,16,46,0.14) 50%, transparent 72%);
  animation: floatB 22s ease-in-out infinite alternate;
  box-shadow: 0 0 120px rgba(200,16,46,0.35);
}
.moon-deco--c {
  width: 260px; height: 260px;
  right: 22%; top: -60px;
  background:
    radial-gradient(circle at 70% 30%, rgba(231,230,255,0.55), transparent 60%);
  animation: floatC 26s ease-in-out infinite alternate;
  opacity: 0.7;
}
@keyframes floatA { 0%{ transform: translate3d(0,0,0) scale(1);} 100%{ transform: translate3d(28px,18px,0) scale(1.04);} }
@keyframes floatB { 0%{ transform: translate3d(0,0,0);} 100%{ transform: translate3d(-28px,-22px,0);} }
@keyframes floatC { 0%{ transform: translate3d(0,0,0) rotate(0deg);} 100%{ transform: translate3d(-22px,16px,0) rotate(6deg);} }

/* ===== 登录卡片：午夜玻璃 + 双重描边（外：月光、内极细：朱砂） ===== */
.login-card {
  position: relative;
  z-index: 2;
  width: min(460px, 100%);
  padding: 40px 36px 28px;
  border-radius: 26px;
  background:
    linear-gradient(180deg,
      rgba(21, 26, 68, 0.82) 0%,
      rgba(11, 14, 46, 0.92) 100%);
  border: 1px solid var(--line-glow);
  backdrop-filter: blur(22px) saturate(140%);
  -webkit-backdrop-filter: blur(22px) saturate(140%);
  box-shadow:
    0 0 0 1px rgba(231, 230, 255, 0.04) inset,
    0 0 0 6px rgba(200, 16, 46, 0.04),
    0 40px 90px -30px rgba(0,0,0,0.9),
    0 24px 70px -24px rgba(139, 124, 255, 0.35);
  animation: cardIn 640ms var(--ease-out-quint) both;
}
/* 卡片左上角极细朱砂"指甲痕"装饰 */
.login-card::before {
  content: '';
  position: absolute;
  left: 16px; top: -1px;
  width: 64px; height: 2px;
  background: linear-gradient(90deg, rgba(200,16,46,0.85), transparent);
  filter: drop-shadow(0 0 8px rgba(200,16,46,0.55));
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(18px) scale(0.985); }
  to   { opacity: 1; transform: translateY(0)    scale(1); }
}

/* ===== 品牌徽章 ===== */
.brand {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 30px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--line-soft);
}
.brand-mark {
  position: relative;
  width: 64px; height: 64px;
  border-radius: 20px;
  background:
    radial-gradient(circle at 30% 26%, rgba(231,230,255,0.62), rgba(169,156,255,0.28) 50%, transparent 72%),
    linear-gradient(135deg, rgba(169,156,255,0.6), rgba(139,124,255,0.75));
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.18) inset,
    0 20px 40px -18px rgba(139,124,255,0.75);
  display: flex; align-items: center; justify-content: center;
}
.brand-mark__glyph {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 700;
  font-size: 34px;
  color: var(--text-inverse);
  text-shadow: 0 1px 0 rgba(255,255,255,0.35);
  transform: translateY(-1px);
}
.brand-mark__pupil {
  /* 朱砂瞳孔小点（右上 1/4 处，真祖红瞳） */
  position: absolute;
  top: 14px; right: 16px;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--crimson-500);
  box-shadow: 0 0 10px rgba(200,16,46,0.75);
}
.brand-title {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 4px;
  background: linear-gradient(180deg, #fff 0%, #d9d5ff 55%, #9a8cff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  line-height: 1.1;
}
.brand-subtitle {
  margin-top: 4px;
  font-family: var(--font-display);
  font-style: italic;
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--text-tertiary);
}

/* ===== 表单字段 ===== */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.field { display: flex; flex-direction: column; gap: 8px; }
.field__label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  letter-spacing: 1.5px;
  font-weight: 500;
}
.field__glyph {
  color: var(--crimson-400);
  font-family: var(--font-display);
  font-size: 14px;
  text-shadow: 0 0 8px rgba(200,16,46,0.45);
}
.field__input {
  padding: 14px 16px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(8,9,26,0.7), rgba(11,14,46,0.55));
  border: 1px solid var(--line-soft);
  color: var(--text-primary);
  font-size: 15px;
  font-family: var(--font-body);
  letter-spacing: 0.3px;
  transition: border-color var(--dur-base) var(--ease-out-expo),
              box-shadow var(--dur-base) var(--ease-out-expo),
              background var(--dur-base) var(--ease-out-expo);
}
.field__input::placeholder {
  color: var(--text-tertiary);
  font-style: italic;
  font-family: var(--font-display);
  letter-spacing: 1px;
}
.field__input:focus {
  outline: none;
  border-color: var(--line-glow);
  background: linear-gradient(180deg, rgba(8,9,26,0.78), rgba(19,23,70,0.55));
  box-shadow:
    0 0 0 4px rgba(169, 156, 255, 0.14),
    0 18px 40px -20px rgba(139,124,255,0.6);
}

/* 错误提示：玻璃 + 朱砂细线 */
.error-tip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(200,16,46,0.14), rgba(139,124,255,0.06));
  border: 1px solid var(--line-crimson);
  color: var(--crimson-100);
  font-size: 13px;
  letter-spacing: 0.5px;
}
.error-tip__dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--crimson-500);
  box-shadow: 0 0 10px rgba(200,16,46,0.8);
  animation: pulseDot 1.4s ease-in-out infinite;
}
@keyframes pulseDot { 0%,100%{transform:scale(1); opacity:1;} 50%{transform:scale(0.85); opacity:0.65;} }
.error-fade-enter-active, .error-fade-leave-active {
  transition: opacity 280ms var(--ease-out-expo), transform 280ms var(--ease-out-expo);
}
.error-fade-enter-from, .error-fade-leave-to { opacity: 0; transform: translateY(-6px); }

/* ===== 提交按钮：朱砂 → 月光渐变 + 磁性 + 涟漪 + 左上高光 ===== */
.submit-btn {
  position: relative;
  padding: 15px 18px;
  margin-top: 4px;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.28);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 6px;
  font-family: var(--font-display);
  cursor: pointer;
  background: linear-gradient(135deg, var(--crimson-500) 0%, #a10c22 48%, var(--moonlight-500) 100%);
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.28) inset,
    0 20px 50px -20px rgba(200, 16, 46, 0.85),
    0 16px 44px -18px rgba(139, 124, 255, 0.7);
  transition:
    transform 340ms var(--ease-out-expo),
    box-shadow 340ms var(--ease-out-expo),
    opacity 240ms var(--ease-out-expo);
}
/* 左上拟物高光 */
.submit-btn__shine {
  position: absolute;
  top: 1px; left: 12%; right: 12%;
  height: 40%;
  border-radius: 14px 14px 0 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.38), rgba(255,255,255,0));
  pointer-events: none;
}
.submit-btn__loading {
  position: absolute;
  top: 50%; left: 14px;
  width: 14px; height: 14px;
  margin-top: -7px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  animation: spin 820ms linear infinite;
}
.submit-btn__label { position: relative; z-index: 1; }
.submit-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.008);
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.48) inset,
    0 28px 58px -20px rgba(200, 16, 46, 0.9),
    0 20px 52px -18px rgba(139, 124, 255, 0.78);
}
.submit-btn:disabled { opacity: 0.72; cursor: progress; }
@keyframes spin { to { transform: rotate(360deg); } }

.tips {
  margin-top: 20px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
  letter-spacing: 2px;
  font-family: var(--font-display);
  font-style: italic;
}
</style>
