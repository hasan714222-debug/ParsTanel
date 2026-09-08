package manage

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

type GameEndpoint struct {
	Game   string
	Region string
	Host   string
	Note   string
}

var gameListFile = app.ConfigDir + "/game-endpoints.list"

func defaultGameEndpoints() []GameEndpoint {
	return []GameEndpoint{
		{"Dota 2", "Europe West", "185.25.183.1", "Valve Luxembourg"},
		{"Dota 2", "Europe East", "155.133.238.1", "Valve Vienna"},
		{"Dota 2", "Dubai", "185.25.180.1", "Valve Dubai"},
		{"CS2 / CSGO", "Europe West", "155.133.240.1", "Valve Frankfurt"},
		{"CS2 / CSGO", "Europe East", "155.133.238.1", "Valve Vienna"},
		{"CS2 / CSGO", "Dubai", "185.25.180.1", "Valve Dubai"},
		{"Valorant", "Europe", "104.18.32.1", "Riot EU edge"},
		{"League of Legends", "Europe West", "162.249.72.1", "Riot EUW"},
		{"PUBG", "Europe", "52.58.0.1", "AWS Frankfurt"},
		{"PUBG", "Middle East", "157.241.0.1", "AWS Bahrain"},
		{"Rainbow Six Siege", "Europe", "185.38.0.1", "Ubisoft EU"},
		{"Call of Duty", "Europe", "52.58.0.1", "Activision EU edge"},
		{"eFootball", "Europe", "35.156.0.1", "Konami EU"},
		{"Fortnite", "Europe", "18.194.0.1", "Epic EU"},
		{"Apex Legends", "Europe", "162.254.192.1", "EA EU"},
		{"Rocket League", "Europe", "35.156.0.1", "Psyonix EU"},
		{"Minecraft (Hypixel)", "Europe", "172.65.230.1", "Hypixel EU"},
		{"GTA Online", "Europe", "192.81.241.1", "Rockstar EU"},
	}
}

func LoadGameEndpoints() []GameEndpoint {
	data, err := os.ReadFile(gameListFile)
	if err != nil {
		_ = saveGameEndpoints(defaultGameEndpoints())
		return defaultGameEndpoints()
	}
	eps := parseGameEndpoints(string(data))
	if len(eps) == 0 {
		return defaultGameEndpoints()
	}
	return eps
}

func parseGameEndpoints(text string) []GameEndpoint {
	var out []GameEndpoint
	sc := bufio.NewScanner(strings.NewReader(text))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Split(line, "|")
		if len(f) < 3 {
			continue
		}
		ep := GameEndpoint{
			Game:   strings.TrimSpace(f[0]),
			Region: strings.TrimSpace(f[1]),
			Host:   strings.TrimSpace(f[2]),
		}
		if len(f) >= 4 {
			ep.Note = strings.TrimSpace(f[3])
		}
		if ep.Game == "" || ep.Host == "" {
			continue
		}
		out = append(out, ep)
	}
	return out
}

func saveGameEndpoints(eps []GameEndpoint) error {
	if err := os.MkdirAll(app.ConfigDir, 0755); err != nil {
		return err
	}
	var b strings.Builder
	b.WriteString("# Game latency endpoints — one per line: game|region|host|note\n")
	b.WriteString("# Addresses are best-effort; replace them with hosts you have verified.\n")
	for _, e := range eps {
		fmt.Fprintf(&b, "%s|%s|%s|%s\n", e.Game, e.Region, e.Host, e.Note)
	}
	return os.WriteFile(gameListFile, []byte(b.String()), 0644)
}

type GamePing struct {
	AvgMS   float64
	LossPct float64
	OK      bool
}

var (
	rePingRTT  = regexp.MustCompile(`=\s*[0-9.]+/([0-9.]+)/`)
	rePingLoss = regexp.MustCompile(`([0-9.]+)% packet loss`)
)

func parsePing(out string) GamePing {
	var g GamePing
	if m := rePingLoss.FindStringSubmatch(out); m != nil {
		g.LossPct, _ = strconv.ParseFloat(m[1], 64)
	} else {
		g.LossPct = 100
	}
	if m := rePingRTT.FindStringSubmatch(out); m != nil {
		g.AvgMS, _ = strconv.ParseFloat(m[1], 64)
		g.OK = true
	}
	return g
}

func pingHost(host string, count int) GamePing {
	cmd := exec.Command("ping", "-c", strconv.Itoa(count), "-i", "0.2", "-W", "2", "-q", host)
	out, _ := cmd.CombinedOutput()
	return parsePing(string(out))
}

type GameRating struct {
	Label    string
	Severity int
}

func RateEstimatedPing(ms int) GameRating {
	switch {
	case ms < 60:
		return GameRating{"excellent", 0}
	case ms < 90:
		return GameRating{"good", 0}
	case ms < 130:
		return GameRating{"playable", 1}
	case ms < 180:
		return GameRating{"rough", 1}
	default:
		return GameRating{"bad", 2}
	}
}

var playerLatencies = []struct {
	Where string
	MS    int
}{
	{"Fibre", 10},
	{"ADSL", 25},
	{"Mobile 4G", 45},
	{"Remote province", 60},
}