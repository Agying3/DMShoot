package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"dmshoot-go/internal/writer"
	"dmshoot-go/internal/worker"
)

// BroadcastMessage 统一 WS 广播消息类型
type BroadcastMessage struct {
	Type string      `json:"type"` // "new_message" | "send_command"
	Data interface{} `json:"data"`
}

var (
	dbPath string // 由 DMSHOOT_DB env 或自动发现决定
	port   = ":9800"

	upgrader = websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
	wsClients sync.Map
	broadcast chan BroadcastMessage

	batchWriter *writer.BatchWriter
	registry    *worker.Registry
)

func main() {
	// 命令行参数
	if len(os.Args) > 1 {
		port = ":" + os.Args[1]
	}

	// DB 路径优先级: DMSHOOT_DB env > exe-relative > cwd-relative
	if p := os.Getenv("DMSHOOT_DB"); p != "" {
		dbPath = p
	} else {
		dbPath = discoverDBPath()
	}

	// 初始化 SQLite 批量写入器
	var err error
	batchWriter, err = writer.New(dbPath)
	if err != nil {
		log.Fatalf("数据库初始化失败: %v", err)
	}
	go func() {
		if err := batchWriter.Run(); err != nil {
			log.Printf("批量写入器退出: %v", err)
		}
	}()

	// 消息广播通道
	broadcast = make(chan BroadcastMessage, 2048)
	go broadcastLoop()

	// 平台注册表
	registry = worker.NewRegistry()

	// HTTP 路由
	r := gin.Default()
	r.Use(gin.LoggerWithFormatter(func(p gin.LogFormatterParams) string {
		return fmt.Sprintf("[go-msg] %s %s %d %s\n",
			p.TimeStamp.Format("15:04:05"), p.Method, p.StatusCode, p.Path)
	}))

	api := r.Group("/api")
	api.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok", "uptime": time.Now().Unix()})
	})

	// ── 数据库操作 ──
	api.POST("/db/messages/save", handleDBSaveMessages)
	api.GET("/db/messages", handleDBGetMessages)
	api.POST("/db/sessions/upsert", handleDBUpsertSessions)
	api.GET("/db/sessions", handleDBGetSessions)
	api.POST("/db/sessions/delete", handleDBDeleteSessions)
	api.GET("/db/config", handleDBGetConfig)
	api.POST("/db/config", handleDBSaveConfig)

	api.POST("/send", handleSend)
	worker.RegisterRoutes(api, registry, func(cfg worker.Config) worker.PlatformWorker {
		return &worker.NoopWorker{}
	})

	r.GET("/ws", handleWebSocket)

	// 优雅关闭
	srv := &http.Server{Addr: port, Handler: r}
	go func() {
		log.Printf("[go-msg] 启动于 http://127.0.0.1%s (DB: %s)", port, dbPath)
		if err := srv.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("服务启动失败: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("[go-msg] 正在关闭...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	registry.Shutdown()
	batchWriter.Shutdown()
	srv.Shutdown(ctx)
	log.Println("[go-msg] 已关闭")
}

// ── 数据库查询 API ──

type MessageRow struct {
	SessionID  string  `json:"session_id"`
	SenderName string  `json:"sender_name"`
	SenderID   string  `json:"sender_id"`
	Content    string  `json:"content"`
	MsgType    string  `json:"msg_type"`
	Timestamp  float64 `json:"timestamp"`
	IsSelf     bool    `json:"is_self"`
	IsAuto     bool    `json:"is_auto"`
}

type SessionRow struct {
	SessionID   string  `json:"session_id"`
	Platform    string  `json:"platform"`
	PeerName    string  `json:"peer_name"`
	PeerID      string  `json:"peer_id"`
	LastMessage string  `json:"last_message"`
	LastTime    float64 `json:"last_time"`
	AvatarURL   string  `json:"avatar_url"`
}

func handleDBSaveMessages(c *gin.Context) {
	var msgs []MessageRow
	if err := c.ShouldBindJSON(&msgs); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	wMsgs := make([]writer.Message, len(msgs))
	for i, m := range msgs {
		wMsgs[i] = writer.Message{
			SessionID: m.SessionID, SenderName: m.SenderName,
			SenderID: m.SenderID, Content: m.Content,
			MsgType: m.MsgType, Timestamp: int64(m.Timestamp), IsSelf: m.IsSelf,
		}
	}
	batchWriter.SubmitMessages(wMsgs)
	c.JSON(200, gin.H{"saved": len(wMsgs)})
}

func handleDBGetMessages(c *gin.Context) {
	sessionID := c.Query("session_id")
	limit := 50
	if l := c.Query("limit"); l != "" {
		fmt.Sscanf(l, "%d", &limit)
	}
	rows, err := batchWriter.DB.Query(
		"SELECT session_id, sender_name, sender_id, content, msg_type, timestamp, is_self, is_auto FROM messages WHERE session_id=? ORDER BY timestamp ASC LIMIT ?",
		sessionID, limit,
	)
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()
	var msgs []MessageRow
	for rows.Next() {
		var m MessageRow
		var isSelf, isAuto int
		rows.Scan(&m.SessionID, &m.SenderName, &m.SenderID, &m.Content, &m.MsgType, &m.Timestamp, &isSelf, &isAuto)
		m.IsSelf = isSelf == 1
		m.IsAuto = isAuto == 1
		msgs = append(msgs, m)
	}
	c.JSON(200, msgs)
}

func handleDBUpsertSessions(c *gin.Context) {
	var sessions []SessionRow
	if err := c.ShouldBindJSON(&sessions); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	wSessions := make([]writer.Session, len(sessions))
	for i, s := range sessions {
		wSessions[i] = writer.Session{
			SessionID: s.SessionID, Platform: s.Platform,
			PeerName: s.PeerName, PeerID: s.PeerID,
			LastMessage: s.LastMessage, LastTime: s.LastTime, AvatarURL: s.AvatarURL,
		}
	}
	batchWriter.SubmitSessions(wSessions)
	c.JSON(200, gin.H{"saved": len(wSessions)})
}

func handleDBGetSessions(c *gin.Context) {
	platform := c.Query("platform")
	var rows *sql.Rows
	var err error
	if platform != "" {
		rows, err = batchWriter.DB.Query(
			"SELECT session_id, platform, peer_name, peer_id, last_message, last_time, avatar_url FROM sessions WHERE platform=? ORDER BY last_time DESC",
			platform,
		)
	} else {
		rows, err = batchWriter.DB.Query(
			"SELECT session_id, platform, peer_name, peer_id, last_message, last_time, avatar_url FROM sessions ORDER BY last_time DESC",
		)
	}
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()
	var sessions []SessionRow
	for rows.Next() {
		var s SessionRow
		rows.Scan(&s.SessionID, &s.Platform, &s.PeerName, &s.PeerID, &s.LastMessage, &s.LastTime, &s.AvatarURL)
		sessions = append(sessions, s)
	}
	c.JSON(200, sessions)
}

func handleDBDeleteSessions(c *gin.Context) {
	var req struct {
		Platform string `json:"platform"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	_, err := batchWriter.DB.Exec("DELETE FROM sessions WHERE platform=?", req.Platform)
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	_, _ = batchWriter.DB.Exec("DELETE FROM messages WHERE session_id LIKE ?", req.Platform+":%")
	c.JSON(200, gin.H{"status": "deleted"})
}

func handleDBGetConfig(c *gin.Context) {
	row := batchWriter.DB.QueryRow("SELECT value FROM config WHERE key='app_config'")
	var raw string
	if err := row.Scan(&raw); err != nil {
		c.JSON(200, gin.H{})
		return
	}
	c.Data(200, "application/json", []byte(raw))
}

func handleDBSaveConfig(c *gin.Context) {
	raw, _ := c.GetRawData()
	_, err := batchWriter.DB.Exec(
		"INSERT OR REPLACE INTO config (key, value) VALUES ('app_config', ?)", string(raw),
	)
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	c.JSON(200, gin.H{"status": "ok"})
}

func handleSend(c *gin.Context) {
	var req struct {
		Platform   string `json:"platform"    binding:"required"`
		SessionID  string `json:"session_id"  binding:"required"`
		Content    string `json:"content"     binding:"required"`
		SenderName string `json:"sender_name"`
		SenderID   string `json:"sender_id"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	if req.SenderName == "" {
		req.SenderName = "我"
	}
	if req.SenderID == "" {
		req.SenderID = "self"
	}

	// 1. 写入 outgoing 消息到 DB（is_self=1）
	outMsg := writer.Message{
		Platform:   req.Platform,
		SessionID:  req.SessionID,
		SenderName: req.SenderName,
		SenderID:   req.SenderID,
		Content:    req.Content,
		MsgType:    "text",
		Timestamp:  time.Now().Unix(),
		IsSelf:     true,
	}
	batchWriter.SubmitMessages([]writer.Message{outMsg})

	// 2. 通过 WebSocket 广播 send_command，让 Python 端实际调用平台 API
	sendCmd := map[string]interface{}{
		"platform":   req.Platform,
		"session_id": req.SessionID,
		"content":    req.Content,
		"sender_name": req.SenderName,
	}
	PushCommand("send_command", sendCmd)

	log.Printf("[send] %s → %s: %s", req.Platform, req.SessionID, req.Content[:min(len(req.Content), 30)])
	c.JSON(200, gin.H{"status": "queued"})
}

func handleWebSocket(c *gin.Context) {
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Printf("WS 升级失败: %v", err)
		return
	}
	addr := conn.RemoteAddr().String()
	wsClients.Store(addr, conn)
	log.Printf("[ws] 客户端连接: %s (当前 %d)", addr, clientCount())
	defer func() {
		wsClients.Delete(addr)
		conn.Close()
		log.Printf("[ws] 客户端断开: %s (剩余 %d)", addr, clientCount())
	}()
	// 心跳保活
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			break
		}
	}
}

func broadcastLoop() {
	for msg := range broadcast {
		wsClients.Range(func(_, v interface{}) bool {
			conn := v.(*websocket.Conn)
			conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
			if err := conn.WriteJSON(msg); err != nil {
				conn.Close()
			}
			return true
		})
	}
}

func clientCount() int {
	count := 0
	wsClients.Range(func(_, _ interface{}) bool { count++; return true })
	return count
}

// PushMessage 外部模块推送消息到广播通道
func PushMessage(msg writer.Message) {
	select {
	case broadcast <- BroadcastMessage{Type: "new_message", Data: msg}:
	default:
	}
}

// PushMessages 批量推送
func PushMessages(msgs []writer.Message) {
	batchWriter.SubmitMessages(msgs)
	for _, m := range msgs {
		PushMessage(m)
	}
}

// PushCommand 推送控制指令到广播通道
func PushCommand(cmdType string, data interface{}) {
	select {
	case broadcast <- BroadcastMessage{Type: cmdType, Data: data}:
	default:
	}
}

// discoverDBPath 在无 DMSHOOT_DB env 时自动发现 SQLite 路径
func discoverDBPath() string {
	exe, _ := os.Executable()
	exeDir := filepath.Dir(exe)
	cwd, _ := os.Getwd()

	// 候选路径：exe 目录下的相对路径 > 工作目录下的相对路径
	candidates := []string{
		filepath.Join(exeDir, "dmshoot", "data", "dmshoot.db"),
		filepath.Join(exeDir, "data", "dmshoot.db"),
		filepath.Join(exeDir, "dmshoot.db"),
		filepath.Join(cwd, "dmshoot", "data", "dmshoot.db"),
		filepath.Join(cwd, "data", "dmshoot.db"),
		filepath.Join(cwd, "dmshoot.db"),
	}
	for _, p := range candidates {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "dmshoot.db" // 最后的兜底
}
