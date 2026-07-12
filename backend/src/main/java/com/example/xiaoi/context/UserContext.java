package com.example.xiaoi.context;

import com.example.xiaoi.entity.User;

public class UserContext {

    private static final ThreadLocal<User> userThreadLocal = new ThreadLocal<>();

    public static void setUser(User user) {
        userThreadLocal.set(user);
    }

    public static User getUser() {
        return userThreadLocal.get();
    }

    public static Long getUserId() {
        User user = userThreadLocal.get();
        return user != null ? user.getId() : null;
    }

    public static String getUsername() {
        User user = userThreadLocal.get();
        return user != null ? user.getUsername() : null;
    }

    public static void clear() {
        userThreadLocal.remove();
    }
}