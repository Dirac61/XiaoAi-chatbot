package com.example.xiaoi.service;

import com.example.xiaoi.entity.User;

import java.util.Map;

public interface UserService {

    Map<String, Object> login(String username, String password);
}