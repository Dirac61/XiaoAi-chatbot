package com.example.xiaoi.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.xiaoi.entity.User;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserMapper extends BaseMapper<User> {
}