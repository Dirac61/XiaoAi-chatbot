package com.example.xiaoi.service.impl;

import com.example.xiaoi.service.TokenService;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class TokenServiceImpl implements TokenService {

    private final Map<String, String> tokenStorage = new ConcurrentHashMap<>();

    @Override
    public void setToken(String token, String userId, long expireHours) {
        tokenStorage.put("token:" + token, userId);
    }

    @Override
    public String getUserId(String token) {
        return tokenStorage.get("token:" + token);
    }

    @Override
    public void removeToken(String token) {
        tokenStorage.remove("token:" + token);
    }
}