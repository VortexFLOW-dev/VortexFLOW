// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is the agent's runtime configuration, sourced from environment
// variables (systemd loads them from /etc/vortexflow/agent.env).
type Config struct {
	// Control plane
	ServerURL  string // VORTEXFLOW_URL  — base URL, e.g. https://vf.example.com
	InstanceID string // INSTANCE_ID
	Token      string // AGENT_TOKEN

	// Behaviour
	PollInterval time.Duration // AGENT_POLL_INTERVAL (default 15s)
	InsecureTLS  bool          // AGENT_INSECURE_SKIP_VERIFY (default false)
	CACertPath   string        // AGENT_CA_CERT — extra CA PEM to trust (self-signed leader)

	// Vector integration
	ConfigPath       string   // VECTOR_CONFIG_PATH (default /etc/vector/vortexflow.yaml)
	VectorBin        string   // VECTOR_BIN (default "vector")
	ReloadCmd        []string // VECTOR_RELOAD_CMD (default: systemctl kill -s HUP vector)
	VectorInstallCmd []string // VECTOR_INSTALL_CMD ({version} placeholder); empty = no auto-update

	// Managed directory the server is allowed to write cert material into.
	// The agent runs as root, so server-supplied file paths are confined to
	// this tree — a compromised control plane cannot write arbitrary host
	// files. Must match the server's VORTEXFLOW_COMPONENT_CERTS_DIR.
	CertsDir string // VORTEXFLOW_COMPONENT_CERTS_DIR (default /etc/vortexflow/component-certs)
}

// LoadConfig reads configuration from the environment, applying defaults and
// validating that the required fields are present.
func LoadConfig() (Config, error) {
	c := Config{
		ServerURL:    strings.TrimRight(os.Getenv("VORTEXFLOW_URL"), "/"),
		InstanceID:   os.Getenv("INSTANCE_ID"),
		Token:        os.Getenv("AGENT_TOKEN"),
		PollInterval: 15 * time.Second,
		CACertPath:   os.Getenv("AGENT_CA_CERT"),
		ConfigPath:   envOr("VECTOR_CONFIG_PATH", "/etc/vector/vortexflow.yaml"),
		VectorBin:    envOr("VECTOR_BIN", "vector"),
		CertsDir: envOr(
			"VORTEXFLOW_COMPONENT_CERTS_DIR", "/etc/vortexflow/component-certs",
		),
	}

	var missing []string
	if c.ServerURL == "" {
		missing = append(missing, "VORTEXFLOW_URL")
	}
	if c.InstanceID == "" {
		missing = append(missing, "INSTANCE_ID")
	}
	if c.Token == "" {
		missing = append(missing, "AGENT_TOKEN")
	}
	if len(missing) > 0 {
		return Config{}, fmt.Errorf("missing required env: %s", strings.Join(missing, ", "))
	}

	if v := os.Getenv("AGENT_POLL_INTERVAL"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return Config{}, fmt.Errorf("invalid AGENT_POLL_INTERVAL %q: %w", v, err)
		}
		if d < time.Second {
			d = time.Second
		}
		c.PollInterval = d
	}

	if v := os.Getenv("AGENT_INSECURE_SKIP_VERIFY"); v != "" {
		c.InsecureTLS, _ = strconv.ParseBool(v)
	}

	// Reload command: a SIGHUP via systemd by default. Vector reloads on SIGHUP.
	if v := os.Getenv("VECTOR_RELOAD_CMD"); v != "" {
		c.ReloadCmd = strings.Fields(v)
	} else {
		c.ReloadCmd = []string{"systemctl", "kill", "-s", "HUP", "vector"}
	}

	// Optional Vector auto-update command ({version} placeholder). Empty =
	// report drift only, never install.
	if v := os.Getenv("VECTOR_INSTALL_CMD"); v != "" {
		c.VectorInstallCmd = strings.Fields(v)
	}

	return c, nil
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
