package com.example.xiaoi.service;

import com.example.xiaoi.entity.User;

import java.util.Map;

/**
 * 用户服务接口
 * 提供用户登录、注册等认证相关功能
 */
public interface UserService {

    /**
     * 用户登录
     * 支持自动注册：用户名不存在时自动创建新用户
     * @param username 用户名
     * @param password 密码（明文）
     * @return 登录结果，包含 token 和用户信息
     */
    Map<String, Object> login(String username, String password);
}