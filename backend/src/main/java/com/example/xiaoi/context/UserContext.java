package com.example.xiaoi.context;

import com.example.xiaoi.entity.User;

/**
 * 用户上下文工具类
 * 使用 ThreadLocal 存储当前请求的用户信息，供整个请求链路使用
 * 
 * 工作流程：
 * 1. TokenInterceptor 在 preHandle 中解析 Token，获取用户信息并调用 setUser()
 * 2. Controller/Service 层通过 getUserId()/getUser() 获取当前用户
 * 3. TokenInterceptor 在 afterCompletion 中调用 clear() 清理，防止内存泄漏
 */
public class UserContext {

    /** ThreadLocal 存储当前线程的用户信息 */
    private static final ThreadLocal<User> userThreadLocal = new ThreadLocal<>();

    /** 设置当前用户 */
    public static void setUser(User user) {
        userThreadLocal.set(user);
    }

    /** 获取当前用户 */
    public static User getUser() {
        return userThreadLocal.get();
    }

    /** 获取当前用户 ID（常用快捷方法） */
    public static Long getUserId() {
        User user = userThreadLocal.get();
        return user != null ? user.getId() : null;
    }

    /** 获取当前用户名 */
    public static String getUsername() {
        User user = userThreadLocal.get();
        return user != null ? user.getUsername() : null;
    }

    /** 清理用户上下文（必须在请求结束时调用，防止内存泄漏） */
    public static void clear() {
        userThreadLocal.remove();
    }
}