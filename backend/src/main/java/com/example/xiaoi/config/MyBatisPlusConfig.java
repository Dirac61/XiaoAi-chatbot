package com.example.xiaoi.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * MyBatis Plus 配置类
 * 注册分页插件，使分页查询功能生效
 */
@Configuration
public class MyBatisPlusConfig {

    /**
     * 创建 MyBatis Plus 拦截器链
     * 添加分页拦截器，支持 Page 分页查询
     * 注意：必须手动注册此 Bean，否则分页查询不生效
     * @return MybatisPlusInterceptor 实例
     */
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // 注册 MySQL 分页拦截器，使 Page<> 分页查询生效
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}