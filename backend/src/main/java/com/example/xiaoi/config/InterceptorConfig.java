package com.example.xiaoi.config;

import com.example.xiaoi.interceptor.InternalApiInterceptor;
import com.example.xiaoi.interceptor.TokenInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 拦截器配置类
 * - TokenInterceptor: 对所有 /api/** 请求进行登录校验（排除内部接口）
 * - InternalApiInterceptor: 对内部接口进行密钥认证（仅 Agent 可调用）
 */
@Configuration
public class InterceptorConfig implements WebMvcConfigurer {

    @Autowired
    private TokenInterceptor tokenInterceptor;

    @Autowired
    private InternalApiInterceptor internalApiInterceptor;

    /**
     * 注册拦截器
     * TokenInterceptor 拦截所有 /api/** 请求，排除登录、健康检查和内部接口
     * InternalApiInterceptor 只拦截内部接口，进行密钥认证
     *
     * 内部接口清单（需要双向同步：①Token exclude + ②Internal add）：
     * - /api/message/update-content         : Agent 回写 assistant 消息正文 + 图片提取文本
     * - /api/message/update-search-results  : Agent 回写联网搜索结果[{title,url}]
     * - /api/message/update-expert-trace    : Agent 回写专家模式编排分析+工具执行结果expertTrace
     * - /api/memory/delete                  : Agent 删除会话向量记忆（会话删除联动）
     * - /api/mcp/internal/installed          : Agent 查询用户已安装 MCP 列表（懒加载用）
     * - /api/session/delete/**              : 用户侧正常删除会话，走 Token 校验+此处仅排除（不需要 X-Internal-Secret）
     */
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // TokenInterceptor: 用户认证拦截器（所有 /api/** 都走，除非在内部接口白名单）
        registry.addInterceptor(tokenInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/login", "/api/health",
                    "/api/message/update-content", "/api/message/update-search-results",
                    "/api/message/update-expert-trace",
                    "/api/memory/delete", "/api/session/delete/**",
                    "/api/mcp/internal/installed");

        // InternalApiInterceptor: 内部接口密钥认证拦截器（仅 Agent → 后端的回写接口）
        // 注意：只注册"需要 X-Internal-Secret 鉴权"的真正内部接口（不含 /api/session/delete/**）
        registry.addInterceptor(internalApiInterceptor)
                .addPathPatterns(
                    "/api/message/update-content",
                    "/api/message/update-search-results",
                    "/api/message/update-expert-trace",
                    "/api/memory/delete",
                    "/api/mcp/internal/installed"
                );
    }
}