package com.example.xiaoi;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@MapperScan("com.example.xiaoi.mapper")
@EnableAsync
@EnableScheduling
public class XiaoAiApplication {

    public static void main(String[] args) {
        SpringApplication.run(XiaoAiApplication.class, args);
    }
}