package com.example.xiaoi.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.xiaoi.entity.FileHash;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * 文件哈希去重 Mapper
 * 提供行锁查询和引用计数原子增减操作
 * SELECT ... FOR UPDATE 必须在 @Transactional 事务中使用
 */
@Mapper
public interface FileHashMapper extends BaseMapper<FileHash> {

    /**
     * 行锁查询：SELECT ... FOR UPDATE
     * 同一 file_hash 的并发请求串行化，防止竞态
     * 必须在 @Transactional 事务中调用
     */
    @Select("SELECT * FROM file_hash WHERE file_hash = #{fileHash} FOR UPDATE")
    FileHash selectForUpdate(@Param("fileHash") String fileHash);

    /**
     * 根据 storage_url 查询记录
     * 用于删除时通过 URL 反查 MD5
     */
    @Select("SELECT * FROM file_hash WHERE storage_url = #{storageUrl}")
    FileHash selectByUrl(@Param("storageUrl") String storageUrl);

    /**
     * 原子递增引用次数
     * SET ref_count = ref_count + 1
     */
    @Update("UPDATE file_hash SET ref_count = ref_count + 1 WHERE file_hash = #{fileHash}")
    int incrementRefCount(@Param("fileHash") String fileHash);

    /**
     * 原子递减引用次数（带 > 0 保护）
     * SET ref_count = ref_count - 1 WHERE ref_count > 0
     * 返回影响行数：0 表示已为 0 无需再减
     */
    @Update("UPDATE file_hash SET ref_count = ref_count - 1 WHERE file_hash = #{fileHash} AND ref_count > 0")
    int decrementRefCount(@Param("fileHash") String fileHash);

    /**
     * 查询当前引用次数
     */
    @Select("SELECT ref_count FROM file_hash WHERE file_hash = #{fileHash}")
    Integer selectRefCount(@Param("fileHash") String fileHash);
}
