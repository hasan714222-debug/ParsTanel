package manage

import (
	"encoding/json"
	"os"
	"sync"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

type tunnelMeta struct {
	Country string `json:"country"`
}

var metaMu sync.Mutex

func metaPath() string { return app.ConfigDir + "/meta.json" }

func loadMeta() map[string]tunnelMeta {
	m := map[string]tunnelMeta{}
	if data, err := os.ReadFile(metaPath()); err == nil {
		json.Unmarshal(data, &m)
	}
	return m
}

func saveMeta(m map[string]tunnelMeta) {
	if err := os.MkdirAll(app.ConfigDir, 0755); err != nil {
		return
	}
	data, _ := json.MarshalIndent(m, "", "  ")
	os.WriteFile(metaPath(), data, 0644)
}

func TunnelCountry(name string) string {
	metaMu.Lock()
	defer metaMu.Unlock()
	return loadMeta()[name].Country
}

func deleteTunnelMeta(name string) {
	metaMu.Lock()
	defer metaMu.Unlock()
	m := loadMeta()
	delete(m, name)
	saveMeta(m)
}
