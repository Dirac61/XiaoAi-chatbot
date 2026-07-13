package com.example.xiaoi.controller;

import com.example.xiaoi.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 用户登录控制器
 * 提供登录接口，支持自动注册（用户名不存在时自动创建）
 */
@RestController
@RequestMapping("/api")
public class LoginController {

    @Autowired
    private UserService userService;

    /**
     * 用户登录接口
     * 支持自动注册：用户名不存在时自动创建新用户
     * @param request 登录请求，包含 username 和 password
     * @return 登录结果，包含 token 和用户信息
     */
    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody Map<String, String> request) {
        String username = request.get("username");
        String password = request.get("password");
        return userService.login(username, password);
    }
}