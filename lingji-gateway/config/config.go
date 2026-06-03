package config

import (
	"os"
	"strconv"
	"time"
)

// Config Gateway 全部配置
type Config struct {
	Port             int
	AuthToken        string   // 鉴权令牌（空 = 关闭鉴权）
	HeartbeatTimeout time.Duration
	OfflineQueueSize int
	MaxMessageSize   int64
	FileMaxSizeBytes int64         // G6 单文件上限（默认 50MB）
	FileTTL          time.Duration // G6 临时文件 TTL（默认 1h）
	FileMaxDownloads int           // G6 单链下载次数上限（默认 10）
	FileStoreDir     string        // G6 临时文件目录
}

// DefaultConfig 返回默认配置 + 环境变量覆盖
func DefaultConfig() *Config {
	return &Config{
		Port:             envInt("LINGJI_PORT", 8765),
		AuthToken:        os.Getenv("LINGJI_AUTH_TOKEN"),
		HeartbeatTimeout: envDuration("LINGJI_HEARTBEAT_TIMEOUT", 120*time.Second),
		OfflineQueueSize: 100,
		MaxMessageSize:   65536, // 64KB
		FileMaxSizeBytes: envInt64("LINGJI_FILE_MAX_BYTES", 50*1024*1024),
		FileTTL:          envDuration("LINGJI_FILE_TTL", time.Hour),
		FileMaxDownloads: envInt("LINGJI_FILE_MAX_DOWNLOADS", 10),
		FileStoreDir:     os.Getenv("LINGJI_FILE_STORE_DIR"),
	}
}

func envInt64(key string, defaultVal int64) int64 {
	if s := os.Getenv(key); s != "" {
		if v, err := strconv.ParseInt(s, 10, 64); err == nil {
			return v
		}
	}
	return defaultVal
}

func envDuration(key string, defaultVal time.Duration) time.Duration {
	if s := os.Getenv(key); s != "" {
		if d, err := time.ParseDuration(s); err == nil {
			return d
		}
	}
	return defaultVal
}

func envInt(key string, defaultVal int) int {
	if s := os.Getenv(key); s != "" {
		if v, err := strconv.Atoi(s); err == nil {
			return v
		}
	}
	return defaultVal
}
