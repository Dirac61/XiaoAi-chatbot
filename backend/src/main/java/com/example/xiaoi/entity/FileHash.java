package com.example.xiaoi.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文件哈希去重实体类
 * 对应 file_hash 表，存储文件MD5哈希值和引用次数
 * 上传时 +1，删除时 -1，次数为 0 时删除 OSS 文件
 * MySQL 为权威数据源，Redis 为只读缓存
 */
@Data
@TableName("file_hash")
public class FileHash {

    /** 主键 ID，自增 */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 文件 MD5 哈希值（唯一索引） */
    @TableField("file_hash")
    private String fileHash;

    /** 阿里云 OSS 存储地址（完整 URL） */
    @TableField("storage_url")
    private String storageUrl;

    /** 文件类型：IMAGE/FILE */
    @TableField("file_type")
    private String fileType;

    /** 文件大小（字节） */
    @TableField("file_size")
    private Long fileSize;

    /** 原始文件扩展名（如 .pdf、.jpg） */
    @TableField("original_extension")
    private String originalExtension;

    /** 引用次数，上传+1，取消-1 */
    @TableField("ref_count")
    private Integer refCount;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdAt;

    /** 更新时间 */
    @TableField("updated_at")
    private LocalDateTime updatedAt;
}
