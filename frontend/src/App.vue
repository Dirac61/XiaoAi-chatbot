<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue';

/* =========================================================
 * App.vue — 全局壳（负责：天幕装饰层 + 入场帘幕 + 光标辉光）
 * 说明：所有装饰元素都是 pointer-events:none，不阻挡业务交互
 * 动效全部 CSS 驱动，JS 只负责：
 *   1) 更新 --mx/--my CSS 变量让 .cursor-glow 跟随鼠标（节流）
 *   2) 入场帘幕结束后从 DOM 移除 curtain，省一帧合成
 *   3) 绑定全局点击涟漪到 [data-ripple] 元素（发送按钮、新建会话、确认按钮等）
 * ========================================================= */

const showCurtain = ref(true);
let rafId = null;
let pendingX = null;
let pendingY = null;
let removeListeners = null;

/* 光标跟随：用 rAF 节流，避免 mousemove 触发频繁重绘 */
const onMouseMove = (e) => {
  pendingX = e.clientX;
  pendingY = e.clientY;
  if (rafId == null) {
    rafId = requestAnimationFrame(() => {
      rafId = null;
      if (pendingX == null || pendingY == null) return;
      // 以百分比写入 --mx/--my，支持不同屏幕尺寸
      const vw = window.innerWidth || 1;
      const vh = window.innerHeight || 1;
      const px = (pendingX / vw) * 100;
      const py = (pendingY / vh) * 100;
      document.documentElement.style.setProperty('--mx', `${px.toFixed(2)}%`);
      document.documentElement.style.setProperty('--my', `${py.toFixed(2)}%`);
      pendingX = null;
      pendingY = null;
    });
  }
};

/* 全局点击涟漪：对 data-ripple=true 的元素创建一个 .ripple span（不依赖 Vue 模板） */
const onClickCapture = (e) => {
  // 从 target 向上找第一个带 data-ripple 的元素
  let host = e.target;
  while (host && host !== document.body) {
    if (host.nodeType === 1 && host.getAttribute && host.getAttribute('data-ripple') === 'true') break;
    host = host.parentNode;
  }
  if (!host) return;
  const rect = host.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const span = document.createElement('span');
  span.className = 'ripple';
  // 以点击位置为圆心
  span.style.width = `${size}px`;
  span.style.height = `${size}px`;
  span.style.left = `${e.clientX - rect.left - size / 2}px`;
  span.style.top = `${e.clientY - rect.top - size / 2}px`;
  if (!host.classList.contains('ripple-host')) host.classList.add('ripple-host');
  host.appendChild(span);
  // 动画结束后移除，避免 DOM 堆积
  const clean = () => {
    span.removeEventListener('animationend', clean);
    if (span.parentNode) span.parentNode.removeChild(span);
  };
  span.addEventListener('animationend', clean);
};

onMounted(() => {
  /* 入场帘幕：动画结束即移除 */
  const curtainEl = document.getElementById('app-reveal-curtain');
  if (curtainEl) {
    const cleanup = () => {
      curtainEl.removeEventListener('animationend', cleanup);
      showCurtain.value = false;
      // 再兜底一次从 DOM 移除，避免 z-index 仍在
      if (curtainEl.parentNode) curtainEl.parentNode.removeChild(curtainEl);
    };
    curtainEl.addEventListener('animationend', cleanup);
  }

  /* 节流的鼠标跟随 + 点击涟漪 */
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduce) {
    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('click', onClickCapture, true);
    removeListeners = () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('click', onClickCapture, true);
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
    };
  } else {
    /* 减少动效偏好：关闭鼠标辉光显示 */
    const glow = document.querySelector('.cursor-glow');
    if (glow) glow.style.display = 'none';
  }
});

onBeforeUnmount(() => { if (removeListeners) removeListeners(); });
</script>

<template>
  <!-- 天幕装饰层（纯视觉，都不拦截事件） -->
  <div class="stars-layer" aria-hidden="true"></div>
  <!-- moon-halo 已移除：body 背景图 bg-gothic-moonlit.jpg 自带右上角月亮+朱砂红环，不再需要额外层 -->
  <div class="noise-layer" aria-hidden="true"></div>
  <div class="cursor-glow" aria-hidden="true"></div>

  <!-- 入场帘幕（首次进入揭开，动画结束即移除） -->
  <div
    v-if="showCurtain"
    id="app-reveal-curtain"
    class="reveal-curtain"
    aria-hidden="true"
  ></div>

  <!-- 业务页面 -->
  <router-view />
</template>

<style>
/* App 仅负责最外层 shell；主题 / 组件样式由 style.css + 各页面 scoped 承担 */
html, body, #app { width: 100%; height: 100%; }
</style>
