package main

import (
	"embed"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/handler"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/queue"
)

//go:embed web
var webEmbed embed.FS

func main() {
	cfg := config.DefaultConfig()

	// 创建 Hub
	h := hub.New(cfg.HeartbeatTimeout)
	go h.Run()

	// 创建离线队列
	q := queue.NewOfflineQueue(cfg.OfflineQueueSize)

	// 创建 WS 处理器
	wsHandler := handler.NewWSHandler(h, cfg, q)
	agentsHandler := handler.NewAgentsHandler(h, cfg)
	filesHandler := handler.NewFilesHandler(cfg)

	// H1 RunRegistry + WebSocket event stream
	runWSHub := handler.NewRunWSHub()
	runRegistry := handler.NewRunRegistry(runWSHub)

	webRoot, err := fs.Sub(webEmbed, "web")
	if err != nil {
		log.Fatalf("[Gateway] web embed 失败: %v", err)
	}
	webServer := http.FileServer(http.FS(webRoot))

	// 注册路由
	http.Handle("/ws", wsHandler)
	http.Handle("/v1/agents", agentsHandler)
	http.Handle("/files", filesHandler)
	http.Handle("/files/", filesHandler)
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok","online":%d,"port":%d}`, h.Len(), cfg.Port)
	})

	// H0 RunRegistry HTTP
	http.HandleFunc("GET /v1/health", runRegistry.HandleHealth)
	http.HandleFunc("POST /v1/runs", runRegistry.HandleCreateRun)
	http.HandleFunc("GET /v1/runs/{run_id}", runRegistry.HandleGetRun)
	http.HandleFunc("POST /v1/runs/{run_id}/events", runRegistry.HandlePostEvent)

	// H1 WebSocket event stream
	http.HandleFunc("GET /v1/ws/runs", runRegistry.ServeWS)

	http.Handle("/", webServer)

	// 优雅退出
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		log.Println("[Gateway] 收到退出信号...")
		h.Stop()
		os.Exit(0)
	}()

	// 启动
	addr := fmt.Sprintf(":%d", cfg.Port)
	log.Printf("╔══════════════════════════════════╗")
	log.Printf("║  灵机计划 Gateway v0.1.0          ║")
	log.Printf("║  监听: %s                    ║", addr)
	log.Printf("║  鉴权: %v                      ║", cfg.AuthToken != "")
	log.Printf("║  网页: http://localhost%s        ║", addr)
	log.Printf("╚══════════════════════════════════╝")

	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("[Gateway] 启动失败: %v", err)
	}
}
