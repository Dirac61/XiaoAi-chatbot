package com.example.xiaoi;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.example.xiaoi.mapper")
public class XiaoAiApplication {

    public static void main(String[] args) {
        SpringApplication.run(XiaoAiApplication.class, args);
    }
}