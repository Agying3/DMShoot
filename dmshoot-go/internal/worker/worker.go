package worker

import (
	"context"
	"time"

	"github.com/gin-gonic/gin"
)

// PlatformWorker 平台轮询工作器接口
type PlatformWorker interface {
	Run(ctx context.Context) error
	Platform() string
}

// Config 平台注册配置
type Config struct {
	Platform   string `json:"platform"    binding:"required"`
	Cookie     string `json:"cookie"      binding:"required"`
	IntervalMs int    `json:"interval_ms"`
}

// Registry 管理所有活跃的 worker
type Registry struct {
	workers map[string]PlatformWorker
	cancels map[string]context.CancelFunc
}

func NewRegistry() *Registry {
	return &Registry{
		workers: make(map[string]PlatformWorker),
		cancels: make(map[string]context.CancelFunc),
	}
}

func (r *Registry) Register(cfg Config, factory func(Config) PlatformWorker) {
	if _, ok := r.workers[cfg.Platform]; ok {
		r.Unregister(cfg.Platform)
	}
	ctx, cancel := context.WithCancel(context.Background())
	w := factory(cfg)
	r.workers[cfg.Platform] = w
	r.cancels[cfg.Platform] = cancel
	go w.Run(ctx)
}

func (r *Registry) Unregister(platform string) {
	if cancel, ok := r.cancels[platform]; ok {
		cancel()
		delete(r.cancels, platform)
	}
	delete(r.workers, platform)
}

func (r *Registry) Shutdown() {
	for p := range r.workers {
		r.Unregister(p)
	}
}

func DefaultInterval() time.Duration {
	return 3 * time.Second
}

// NoopWorker 占位 worker（平台 API 暂未实现）
type NoopWorker struct {
	platform string
}

func (n *NoopWorker) Platform() string                { return n.platform }
func (n *NoopWorker) Run(ctx context.Context) error {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
		case <-ctx.Done():
			return nil
		}
	}
}

// RegisterRoutes 注册平台管理 API
func RegisterRoutes(r *gin.RouterGroup, reg *Registry, factory func(Config) PlatformWorker) {
	r.POST("/register", func(c *gin.Context) {
		var cfg Config
		if err := c.ShouldBindJSON(&cfg); err != nil {
			c.JSON(400, gin.H{"error": err.Error()})
			return
		}
		if cfg.IntervalMs <= 0 {
			cfg.IntervalMs = 3000
		}
		reg.Register(cfg, factory)
		c.JSON(200, gin.H{"status": "ok", "platform": cfg.Platform})
	})
	r.POST("/unregister", func(c *gin.Context) {
		var req struct {
			Platform string `json:"platform" binding:"required"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(400, gin.H{"error": err.Error()})
			return
		}
		reg.Unregister(req.Platform)
		c.JSON(200, gin.H{"status": "ok"})
	})
	r.GET("/status", func(c *gin.Context) {
		platforms := make([]string, 0, len(reg.workers))
		for p := range reg.workers {
			platforms = append(platforms, p)
		}
		c.JSON(200, gin.H{"workers": len(reg.workers), "platforms": platforms})
	})
}
