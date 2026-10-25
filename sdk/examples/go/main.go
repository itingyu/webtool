package main

// 外部插件示例（Go）：一行 JSON 进、一行 JSON 出
import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

type in struct {
	Op  string                 `json:"op"`
	Ctx map[string]interface{} `json:"ctx"`
	Hit map[string]interface{} `json:"hit"`
}

type out struct {
	Ok       bool                   `json:"ok,omitempty"`
	Protocol int                    `json:"protocol,omitempty"`
	Name     string                 `json:"name,omitempty"`
	Hit      map[string]interface{} `json:"hit,omitempty"`
	Bypass   map[string]interface{} `json:"bypass,omitempty"`
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 0, 1<<20), 16<<20)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()

	for sc.Scan() {
		var m in
		if json.Unmarshal(sc.Bytes(), &m) != nil {
			fmt.Fprintln(w, "{}")
			w.Flush()
			continue
		}
		var r out
		switch m.Op {
		case "ping":
			r = out{Ok: true, Protocol: 1, Name: "go_example"}
		case "inspect":
			text, _ := m.Ctx["text"].(string)
			low := strings.ToLower(text)
			if strings.Contains(low, "cf-challenge") || strings.Contains(low, "just a moment") {
				r.Hit = map[string]interface{}{"kind": "waf", "sign": "cf-challenge", "why": "质询页"}
			}
		case "bypass":
			u, _ := m.Ctx["url"].(string)
			r.Bypass = map[string]interface{}{"how": "换移动端入口",
				"url": strings.Replace(u, "www.", "m.", 1), "retry": true}
		}
		b, _ := json.Marshal(r)
		fmt.Fprintln(w, string(b))
		w.Flush()
	}
}
