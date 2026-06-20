package writer

import (
	"context"
	"database/sql"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// Message 是一条聊天消息
type Message struct {
	Platform   string `json:"platform"`
	SessionID  string `json:"session_id"`
	SenderName string `json:"sender_name"`
	SenderID   string `json:"sender_id"`
	Content    string `json:"content"`
	MsgType    string `json:"msg_type"`
	Timestamp  int64  `json:"timestamp"`
	IsSelf     bool   `json:"is_self"`
}

// Session 是一条会话记录
type Session struct {
	SessionID   string `json:"session_id"`
	Platform    string `json:"platform"`
	PeerName    string `json:"peer_name"`
	PeerID      string `json:"peer_id"`
	LastMessage string `json:"last_message"`
	LastTime    float64 `json:"last_time"`
	AvatarURL   string `json:"avatar_url"`
}

const (
	DefaultBatchSize    = 100
	DefaultFlushInterval = 500 * time.Millisecond
)

// BatchWriter 批量写入 SQLite（WAL 模式）
type BatchWriter struct {
	DB           *sql.DB  // 暴露给查询API使用
	msgs         chan []Message
	sessions     chan []Session
	batchMsgs    []Message
	batchSessions []Session
	mu           sync.Mutex
	ticker       *time.Ticker
	ctx          context.Context
	cancel       context.CancelFunc
}

func New(dbPath string) (*BatchWriter, error) {
	db, err := sql.Open("sqlite", dbPath+"?_journal_mode=WAL&_synchronous=NORMAL&_busy_timeout=3000")
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	db.SetMaxOpenConns(1)
	ctx, cancel := context.WithCancel(context.Background())
	return &BatchWriter{
		DB:       db,
		msgs:     make(chan []Message, 256),
		sessions: make(chan []Session, 64),
		ticker:   time.NewTicker(DefaultFlushInterval),
		ctx:      ctx,
		cancel:   cancel,
	}, nil
}

func (bw *BatchWriter) SubmitMessages(msgs []Message) {
	if len(msgs) > 0 {
		bw.msgs <- msgs
	}
}

func (bw *BatchWriter) SubmitSessions(sessions []Session) {
	if len(sessions) > 0 {
		bw.sessions <- sessions
	}
}

func (bw *BatchWriter) Run() error {
	initSQL := []string{
		`CREATE TABLE IF NOT EXISTS messages (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			session_id TEXT NOT NULL,
			platform TEXT NOT NULL DEFAULT '',
			sender_name TEXT DEFAULT '',
			sender_id TEXT DEFAULT '',
			content TEXT DEFAULT '',
			msg_type TEXT DEFAULT 'text',
			is_self INTEGER DEFAULT 0,
			is_auto INTEGER DEFAULT 0,
			timestamp REAL DEFAULT 0,
			UNIQUE(session_id, sender_id, content, timestamp)
		)`,
		`CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, timestamp)`,
		`CREATE TABLE IF NOT EXISTS sessions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			session_id TEXT UNIQUE NOT NULL,
			platform TEXT DEFAULT '',
			peer_name TEXT DEFAULT '',
			peer_id TEXT DEFAULT '',
			last_message TEXT DEFAULT '',
			last_time REAL DEFAULT 0,
			unread_count INTEGER DEFAULT 0,
			is_pinned INTEGER DEFAULT 0,
			is_muted INTEGER DEFAULT 0,
			avatar_url TEXT DEFAULT ''
		)`,
		`PRAGMA journal_mode=WAL`,
		`PRAGMA wal_autocheckpoint=200`,  // 200 页 ≈ 800KB 即自动合并
		`PRAGMA synchronous=NORMAL`,
	}
	for _, s := range initSQL {
		if _, err := bw.DB.Exec(s); err != nil {
			return fmt.Errorf("init db: %w", err)
		}
	}

	// L3: 定期 WAL checkpoint（每 60 秒，PASSIVE 不阻塞读写）
	checkpointTicker := time.NewTicker(60 * time.Second)
	defer checkpointTicker.Stop()
	go func() {
		for range checkpointTicker.C {
			bw.DB.Exec("PRAGMA wal_checkpoint(PASSIVE)")
		}
	}()

	for {
		select {
		case <-bw.ctx.Done():
			bw.flush()
			// L4: 关闭前强制 WAL checkpoint
			if _, err := bw.DB.Exec("PRAGMA wal_checkpoint(TRUNCATE)"); err != nil {
				fmt.Printf("关闭前 WAL checkpoint 失败: %v\n", err)
			}
			return bw.DB.Close()
		case msgs := <-bw.msgs:
			bw.batchMsgs = append(bw.batchMsgs, msgs...)
		case sessions := <-bw.sessions:
			bw.batchSessions = append(bw.batchSessions, sessions...)
		case <-bw.ticker.C:
			bw.flush()
		}
	}
}

func (bw *BatchWriter) flush() {
	bw.mu.Lock()
	defer bw.mu.Unlock()
	if len(bw.batchMsgs) == 0 && len(bw.batchSessions) == 0 {
		return
	}
	tx, err := bw.DB.Begin()
	if err != nil {
		return
	}
	// 批量写消息
	if len(bw.batchMsgs) >= DefaultBatchSize || bw.batchMsgs != nil {
		for len(bw.batchMsgs) > 0 {
			n := len(bw.batchMsgs)
			if n > DefaultBatchSize {
				n = DefaultBatchSize
			}
			chunk := bw.batchMsgs[:n]
			bw.batchMsgs = bw.batchMsgs[n:]
			stmt, _ := tx.Prepare(`INSERT OR IGNORE INTO messages
				(session_id, platform, sender_name, sender_id, content, msg_type, is_self, is_auto, timestamp)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
			for _, m := range chunk {
				isSelf := 0
				if m.IsSelf {
					isSelf = 1
				}
				stmt.Exec(m.SessionID, m.Platform, m.SenderName, m.SenderID,
					m.Content, m.MsgType, isSelf, 0, m.Timestamp)
			}
		}
	}
	// 批量写会话
	if len(bw.batchSessions) >= DefaultBatchSize || bw.batchSessions != nil {
		for len(bw.batchSessions) > 0 {
			n := len(bw.batchSessions)
			if n > DefaultBatchSize {
				n = DefaultBatchSize
			}
			chunk := bw.batchSessions[:n]
			bw.batchSessions = bw.batchSessions[n:]
			stmt, _ := tx.Prepare(`INSERT INTO sessions
				(session_id, platform, peer_name, peer_id, last_message, last_time, avatar_url)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(session_id) DO UPDATE SET
					peer_name=excluded.peer_name,
					peer_id=excluded.peer_id,
					last_message=excluded.last_message,
					last_time=excluded.last_time,
					avatar_url=CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE avatar_url END`)
			for _, s := range chunk {
				stmt.Exec(s.SessionID, s.Platform, s.PeerName, s.PeerID,
					s.LastMessage, s.LastTime, s.AvatarURL)
			}
		}
	}
	tx.Commit()
}

func (bw *BatchWriter) Shutdown() {
	bw.cancel()
}
