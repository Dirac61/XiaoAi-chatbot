package com.example.xiaoi.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 健康检查控制器
 * 提供服务健康检查接口，用于容器探针、负载均衡健康检测等场景
 */
@RestController
public class IndexController {
    
    /**
     * 健康检查接口
     * 不经过 Token 拦截器，无需登录即可访问
     * @return "ok" 表示服务正常运行
     */
    @GetMapping("/api/health")
    public String health() {
        return "ok";
    }
}